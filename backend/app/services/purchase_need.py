"""Потребность закупок из годового плана продаж.

Модуль отвечает за три вещи:

1. собирает позиции финально согласованного годового плана продаж
   (товар × месяц, клиенты и менеджеры суммируются);
2. строит и сравнивает снимок источника — по нему видно, что план продаж
   пересмотрели после составления плана закупок;
3. раскладывает годовое количество сырья по месяцам пропорционально продажам
   позиции и считает, до какого месяца нужно оформить заказ с учётом срока
   доставки страны.

Покрытие считается по сырью, а не по строке плана: если одно сырьё нужно
нескольким позициям, приход и излишек у них общие (``cover_group``).

Когда заказ попадает в прошлый год (январь при сроке 90 дней — это октябрь
предыдущего года), возвращается настоящий год и месяц, а не «месяц 1».
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Product
from app.models.planning import SalesPlan, SalesPlanApproval, SalesPlanItem
from app.services.sales_plan_approval_service import current_hash

QTY = Decimal("0.001")
ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
SHARE = Decimal("0.1")
MILLI = Decimal("1000")

Key = TypeVar("Key", bound=Hashable)


def quantize_qty(value: Decimal | int | str) -> Decimal:
    """Количество — три знака, как в БД (Numeric(15, 3))."""
    return Decimal(str(value)).quantize(QTY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class NeedPosition:
    """Позиция плана продаж: сколько продаётся в каждом месяце."""

    product_id: uuid.UUID
    code: str
    name: str
    unit: str
    months: dict[int, Decimal] = field(default_factory=dict)

    @property
    def total(self) -> Decimal:
        return quantize_qty(sum(self.months.values(), ZERO))


@dataclass(frozen=True)
class NeedChange:
    """Расхождение снимка и текущей потребности."""

    product_id: uuid.UUID
    code: str
    name: str
    unit: str
    month: int
    was: Decimal | None
    now: Decimal | None
    kind: str  # added | removed | changed


@dataclass(frozen=True)
class MonthPlan:
    """Месячная потребность строки закупки и крайний месяц заказа."""

    month: int
    quantity: Decimal
    order_year: int
    order_month: int
    overdue: bool


@dataclass(frozen=True)
class CoverageEntry:
    """Месяц плана: сколько нужно, сколько перекрыто и сколько осталось докупить.

    Потребность месяца не равна объёму заказа: сырьё приходит контейнером, и
    излишек перекрывает следующие месяцы. Поэтому процент считается по покрытию
    (не выше 100), а не по приходу — ``carry`` показывает, сколько осталось на
    следующий месяц, ``remaining`` — сколько ещё нужно докупить.
    """

    month: int
    need: Decimal
    covered: Decimal
    remaining: Decimal
    carry: Decimal
    order_year: int
    order_month: int
    overdue: bool

    @property
    def share(self) -> Decimal:
        """Перекрыто, %: не больше 100 — перезатар показывать не нужно."""
        if self.need <= 0:
            return ZERO
        return (self.covered / self.need * ONE_HUNDRED).quantize(SHARE, rounding=ROUND_HALF_UP)


def annual_approval(db: Session, year: int) -> SalesPlanApproval | None:
    return (
        db.execute(select(SalesPlanApproval).where(SalesPlanApproval.year == year))
        .scalars()
        .one_or_none()
    )


def annual_state(db: Session, year: int) -> tuple[str, SalesPlanApproval | None]:
    """Состояние источника: ok | missing | revision | stale.

    `stale` — статус `approved`, но состав утверждённых планов менеджеров уже
    разошёлся с отпечатком: финальное согласование недействительно.
    """
    approval = annual_approval(db, year)
    if approval is None:
        return "missing", None
    if approval.status != "approved":
        return "revision", approval
    if approval.source_hash != current_hash(db, year):
        return "stale", approval
    return "ok", approval


def is_annual_approved(db: Session, year: int) -> bool:
    state, _ = annual_state(db, year)
    return state == "ok"


def need_positions(db: Session, year: int) -> dict[uuid.UUID, NeedPosition]:
    """Помесячная потребность по товарам из утверждённых планов менеджеров."""
    rows = db.execute(
        select(
            SalesPlanItem.product_id,
            SalesPlanItem.month,
            func.sum(SalesPlanItem.quantity),
        )
        .join(SalesPlan, SalesPlan.id == SalesPlanItem.plan_id)
        .where(SalesPlan.year == year, SalesPlan.status == "approved")
        .group_by(SalesPlanItem.product_id, SalesPlanItem.month)
    ).all()
    if not rows:
        return {}

    product_ids = {row[0] for row in rows}
    products = {
        product.id: product
        for product in db.execute(select(Product).where(Product.id.in_(product_ids))).scalars()
    }
    result: dict[uuid.UUID, NeedPosition] = {}
    for product_id, month, quantity in rows:
        product = products.get(product_id)
        if product is None:
            continue
        current = result.get(product_id)
        if current is None:
            current = NeedPosition(
                product_id=product.id,
                code=product.code,
                name=product.name,
                unit=product.unit,
            )
            result[product_id] = current
        current.months[int(month)] = quantize_qty(quantity or ZERO)
    return result


def need_hash(positions: dict[uuid.UUID, NeedPosition]) -> str:
    parts = [
        f"{position.product_id}|{month}|{quantity}"
        for position in sorted(positions.values(), key=lambda row: str(row.product_id))
        for month, quantity in sorted(position.months.items())
        if quantity > 0
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def build_snapshot(
    positions: dict[uuid.UUID, NeedPosition], approval: SalesPlanApproval | None
) -> dict[str, Any]:
    """Снимок источника для хранения в плане закупок."""
    return {
        "version": 1,
        "hash": need_hash(positions),
        "annual_approved_at": (
            approval.approved_at.isoformat() if approval and approval.approved_at else None
        ),
        "products": [
            {
                "product_id": str(position.product_id),
                "code": position.code,
                "name": position.name,
                "unit": position.unit,
                "total": str(position.total),
                "months": {
                    str(month): str(quantity)
                    for month, quantity in sorted(position.months.items())
                    if quantity > 0
                },
            }
            for position in sorted(positions.values(), key=lambda row: row.name)
        ],
    }


def snapshot_positions(snapshot: dict[str, Any] | None) -> dict[uuid.UUID, NeedPosition]:
    """Разбирает снимок обратно в позиции; битый снимок — пустой."""
    if not snapshot:
        return {}
    products = snapshot.get("products")
    if not isinstance(products, list):
        return {}
    result: dict[uuid.UUID, NeedPosition] = {}
    for row in products:
        if not isinstance(row, dict):
            continue
        try:
            product_id = uuid.UUID(str(row["product_id"]))
            months = {
                int(month): quantize_qty(quantity)
                for month, quantity in dict(row.get("months") or {}).items()
            }
        except (KeyError, TypeError, ValueError):
            continue
        result[product_id] = NeedPosition(
            product_id=product_id,
            code=str(row.get("code") or ""),
            name=str(row.get("name") or ""),
            unit=str(row.get("unit") or ""),
            months={month: quantity for month, quantity in months.items() if quantity > 0},
        )
    return result


def snapshot_approved_at(snapshot: dict[str, Any] | None) -> datetime | None:
    if not snapshot:
        return None
    value = snapshot.get("annual_approved_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def diff_positions(
    snapshot: dict[uuid.UUID, NeedPosition], current: dict[uuid.UUID, NeedPosition]
) -> list[NeedChange]:
    """Расхождение по товару и месяцу; клиенты и менеджеры не важны."""
    changes: list[NeedChange] = []
    for product_id in set(snapshot) | set(current):
        before = snapshot.get(product_id)
        after = current.get(product_id)
        info = after or before
        if info is None:
            continue
        for month in range(1, 13):
            was = before.months.get(month, ZERO) if before else ZERO
            now = after.months.get(month, ZERO) if after else ZERO
            if was == now:
                continue
            if was == ZERO:
                kind = "added"
            elif now == ZERO:
                kind = "removed"
            else:
                kind = "changed"
            changes.append(
                NeedChange(
                    product_id=product_id,
                    code=info.code,
                    name=info.name,
                    unit=info.unit,
                    month=month,
                    was=was if was > 0 else None,
                    now=now if now > 0 else None,
                    kind=kind,
                )
            )
    changes.sort(key=lambda row: (row.name, row.month))
    return changes


def order_year_month(plan_year: int, month: int, delivery_days: int) -> tuple[int, int]:
    """Крайний месяц заказа: месяц потребности минус целые месяцы доставки."""
    shift = ceil(delivery_days / 30) if delivery_days > 0 else 0
    index = plan_year * 12 + (month - 1) - shift
    return index // 12, index % 12 + 1


def split_annual(
    annual: Decimal,
    position_months: dict[int, Decimal],
    delivery_days: int,
    plan_year: int,
    today: date | None = None,
) -> list[MonthPlan]:
    """Раскладывает годовое количество по месяцам продаж позиции.

    Остаток от округления отдаётся последнему месяцу, поэтому сумма месяцев
    всегда равна годовому количеству.
    """
    total = sum(position_months.values(), ZERO)
    if annual <= 0 or total <= 0:
        return []
    months = sorted(month for month, quantity in position_months.items() if quantity > 0)
    if not months:
        return []

    current_day = today or date.today()
    remaining = quantize_qty(annual)
    result: list[MonthPlan] = []
    for index, month in enumerate(months):
        if index == len(months) - 1:
            quantity = remaining
        else:
            quantity = quantize_qty(annual * position_months[month] / total)
            quantity = min(quantity, remaining)
        quantity = max(quantity, ZERO)
        remaining = quantize_qty(remaining - quantity)
        if quantity <= 0:
            continue
        order_year, order_month = order_year_month(plan_year, month, delivery_days)
        result.append(
            MonthPlan(
                month=month,
                quantity=quantity,
                order_year=order_year,
                order_month=order_month,
                overdue=(order_year, order_month) < (current_day.year, current_day.month),
            )
        )
    return result


def split_by_norm(
    norm: Decimal,
    position_months: dict[int, Decimal],
    delivery_days: int,
    plan_year: int,
    today: date | None = None,
) -> list[MonthPlan]:
    """Потребность по месяцам от продаж и нормы расхода.

    Каждый месяц считается отдельно: продажи месяца × норма. В отличие от
    ``split_annual`` годовой объём здесь не задан — он получается суммой
    месячных потребностей, поэтому остаток округления размазывать некуда.
    """
    if norm <= 0:
        return []
    current_day = today or date.today()
    result: list[MonthPlan] = []
    for month in sorted(position_months):
        sold = position_months[month]
        if sold <= 0:
            continue
        quantity = quantize_qty(sold * norm)
        if quantity <= 0:
            continue
        order_year, order_month = order_year_month(plan_year, month, delivery_days)
        result.append(
            MonthPlan(
                month=month,
                quantity=quantity,
                order_year=order_year,
                order_month=order_month,
                overdue=(order_year, order_month) < (current_day.year, current_day.month),
            )
        )
    return result


def _milli(value: Decimal) -> int:
    """Количество в тысячных, чтобы делить без потерь на округлении."""
    return int((value * MILLI).to_integral_value(rounding=ROUND_HALF_UP))


def _from_milli(value: int) -> Decimal:
    return Decimal(value).scaleb(-3).quantize(QTY, rounding=ROUND_HALF_UP)


def _split_by_weights(weights: list[int], total: int) -> list[int]:
    """Поделить сумму пропорционально весам, остаток округления — большей доле.

    Считаем в тысячных: целые части по пропорции, а единицы, потерянные на
    округлении, отдаём строкам с самым большим остатком. Сумма всегда равна
    ``total``, и ни одна строка не получает больше своего веса.
    """
    size = sum(weights)
    if size <= 0 or total <= 0:
        return [0] * len(weights)
    parts = [total * weight // size for weight in weights]
    rest = total - sum(parts)
    if rest > 0:
        order = sorted(
            range(len(weights)),
            key=lambda index: (-((total * weights[index]) % size), index),
        )
        for index in order[:rest]:
            parts[index] += 1
    return parts


def cover_family(
    mains: dict[Key, list[MonthPlan]],
    alternatives: Sequence[Key],
    arrivals: dict[Key, dict[int, Decimal]],
    opening: Decimal = ZERO,
) -> tuple[dict[Key, list[CoverageEntry]], dict[Key, dict[int, Decimal]], Decimal]:
    """Покрытие потребности: сначала основное сырьё, затем альтернативы.

    Месяцы идут по порядку. В каждом месяце приход основных строк закрывает их
    потребность; если его не хватило, остаток закрывают альтернативы — иначе их
    приход не попал бы в план. Если альтернатива в этом месяце не понадобилась,
    её приход остаётся в запасе и ждёт следующих месяцев. Возвращаем покрытие
    по основным строкам, расход альтернатив по месяцам и общий остаток.
    """
    month_rows: dict[int, list[tuple[Key, MonthPlan]]] = {}
    for key, schedule in mains.items():
        for entry in schedule:
            month_rows.setdefault(entry.month, []).append((key, entry))

    available: dict[Key, int] = {key: 0 for key in mains}
    for key in alternatives:
        available.setdefault(key, 0)
    if mains and opening:
        available[next(iter(mains))] = _milli(opening)

    # Приход может прийти в месяц, которого нет в графике потребности: до сезона,
    # между месяцами или после последнего. Такой приход не теряем — он ждёт
    # ближайшей потребности и попадает в общий остаток.
    months = set(month_rows)
    for key in available:
        months.update(arrivals.get(key, {}))
    main_keys = list(mains)

    result: dict[Key, list[CoverageEntry]] = {key: [] for key in mains}
    used: dict[Key, dict[int, Decimal]] = {key: {} for key in alternatives}
    for month in sorted(months):
        for key in available:
            available[key] += _milli(arrivals.get(key, {}).get(month, ZERO))

        rows = sorted(month_rows.get(month, []), key=lambda pair: (-pair[1].quantity, str(pair[0])))
        if not rows:
            continue

        needs = {key: _milli(entry.quantity) for key, entry in rows}
        need_total = sum(needs.values())

        # Сначала основное сырьё. Котёл общий: запас любой основной строки может
        # закрыть потребность другой, даже если у неё самой в этом месяце
        # потребности нет. Поэтому берём наличие всех основных строк.
        taken = min(need_total, max(sum(available[key] for key in main_keys), 0))
        if taken > 0:
            parts = _split_by_weights([available[key] for key in main_keys], taken)
            for key, part in zip(main_keys, parts, strict=True):
                available[key] -= part

        shortfall = need_total - taken
        alternatives_taken = min(shortfall, max(sum(available[key] for key in alternatives), 0))
        if alternatives and alternatives_taken > 0:
            parts = _split_by_weights([available[key] for key in alternatives], alternatives_taken)
            for key, part in zip(alternatives, parts, strict=True):
                available[key] -= part
                if part > 0:
                    used[key][month] = _from_milli(part)

        carry = _from_milli(max(sum(available.values()), 0))
        covered_total = taken + alternatives_taken
        covered = _split_by_weights(list(needs.values()), covered_total)
        for (key, entry), need, part in zip(rows, list(needs.values()), covered, strict=True):
            result[key].append(
                CoverageEntry(
                    month=month,
                    need=_from_milli(need),
                    covered=_from_milli(part),
                    remaining=_from_milli(need - part),
                    carry=carry,
                    order_year=entry.order_year,
                    order_month=entry.order_month,
                    overdue=entry.overdue,
                )
            )
    left = _from_milli(max(sum(available.values()), 0)) if months else ZERO
    return result, used, left


def cover_group(
    schedules: dict[Key, list[MonthPlan]],
    arrivals: dict[int, Decimal] | None = None,
    opening: Decimal = ZERO,
) -> dict[Key, list[CoverageEntry]]:
    """Покрытие по сырью без альтернатив: общий котёл на все строки.

    Частный случай ``cover_family``: потребность закрывают приходы всех строк
    одного сырья, покрытие делится пропорционально потребности месяца.
    """
    by_month = dict(arrivals or {})
    keys = list(schedules)
    if not keys:
        return {}
    per_key: dict[Key, dict[int, Decimal]] = {key: {} for key in keys}
    per_key[keys[0]] = by_month
    entries, _used, _left = cover_family(schedules, [], per_key, opening)
    return entries


def cover_schedule(
    schedule: list[MonthPlan],
    arrivals: dict[int, Decimal] | None = None,
    opening: Decimal = ZERO,
) -> list[CoverageEntry]:
    """Покрытие одной строки — частный случай общего котла по сырью."""
    return cover_group({None: schedule}, arrivals, opening)[None]
