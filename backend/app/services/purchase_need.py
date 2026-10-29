"""Потребность закупок из годового плана продаж.

Модуль отвечает за три вещи:

1. собирает позиции финально согласованного годового плана продаж
   (товар × месяц, клиенты и менеджеры суммируются);
2. строит и сравнивает снимок источника — по нему видно, что план продаж
   пересмотрели после составления плана закупок;
3. раскладывает годовое количество сырья по месяцам пропорционально продажам
   позиции и считает, до какого месяца нужно оформить заказ с учётом срока
   доставки страны.

Когда заказ попадает в прошлый год (январь при сроке 90 дней — это октябрь
предыдущего года), возвращается настоящий год и месяц, а не «месяц 1».
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Product
from app.models.planning import SalesPlan, SalesPlanApproval, SalesPlanItem
from app.services.sales_plan_approval_service import current_hash

QTY = Decimal("0.001")
ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
SHARE = Decimal("0.1")


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


def cover_schedule(
    schedule: list[MonthPlan],
    arrivals: dict[int, Decimal] | None = None,
    opening: Decimal = ZERO,
) -> list[CoverageEntry]:
    """Разложить по месяцам то, что уже есть: остаток и приходы.

    Месяцы идут по порядку: остаток на начало плюс приход месяца закрывают
    потребность месяца, излишек переходит на следующий. Поэтому поставка
    контейнером сверх месяца не даёт 250 % — она даёт 100 % и запас на будущее.
    Приходы складываются с того месяца, в котором пришли: раньше времени они
    потребность не закрывают.
    """
    by_month = arrivals or {}
    available = quantize_qty(opening)
    result: list[CoverageEntry] = []
    for entry in schedule:
        available = quantize_qty(available + by_month.get(entry.month, ZERO))
        covered = quantize_qty(min(entry.quantity, max(available, ZERO)))
        available = quantize_qty(available - covered)
        result.append(
            CoverageEntry(
                month=entry.month,
                need=entry.quantity,
                covered=covered,
                remaining=quantize_qty(entry.quantity - covered),
                carry=available if available > 0 else ZERO,
                order_year=entry.order_year,
                order_month=entry.order_month,
                overdue=entry.overdue,
            )
        )
    return result
