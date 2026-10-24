"""План закупок сырья на основании финально согласованного годового плана продаж.

Позиции плана закупок — товары годового плана продаж (клиенты и менеджеры
суммируются). Закупщик вручную раскладывает позицию на сырьё: строка — сырьё,
страна, годовое количество, цена и поставщик. По месяцам количество
раскладывается расчётом (см. ``services/purchase_need.py``).

План хранит снимок источника. Если годовой план продаж пересмотрели и заново
согласовали, директор по закупкам видит diff и принимает изменения к сведению;
пока изменения не приняты, план нельзя отправить и утвердить.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.auth import (
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_IMPORT_MANAGER,
    ROLE_PURCHASE_DIRECTOR,
    User,
)
from app.models.counterparties import Counterparty
from app.models.countries import Country
from app.models.domain import Batch, BatchItem, Product
from app.models.planning import (
    PURCHASE_PLAN_STATUS_TITLES,
    SALES_PLAN_APPROVAL_STATUS_TITLES,
    PurchasePlan,
    PurchasePlanItem,
    PurchasePlanSourceEvent,
    SalesPlanApproval,
)
from app.schemas.planning import (
    PurchasePlanChangeOut,
    PurchasePlanCreate,
    PurchasePlanItemIn,
    PurchasePlanItemOut,
    PurchasePlanMonthOut,
    PurchasePlanOut,
    PurchasePlanPositionOut,
    PurchasePlanScheduleEntryOut,
    PurchasePlanSourceEventOut,
    PurchasePlanSourceOut,
)
from app.services import purchase_need as need
from app.services.plan_freeze import editable_months
from app.services.purchase_need import NeedChange, NeedPosition

EDITORS = (ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER)
VIEWERS = (ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER, ROLE_EXECUTIVE_DIRECTOR)


class PlanError(Exception):
    """Нарушение бизнес-правила плана закупок; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _load(db: Session, plan_id: uuid.UUID) -> PurchasePlan | None:
    return (
        db.execute(
            select(PurchasePlan)
            .where(PurchasePlan.id == plan_id)
            .options(selectinload(PurchasePlan.items))
            .options(
                selectinload(PurchasePlan.source_events).selectinload(
                    PurchasePlanSourceEvent.acknowledged_by
                )
            )
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one_or_none()
    )


def _require(db: Session, plan_id: uuid.UUID) -> PurchasePlan:
    plan = _load(db, plan_id)
    if plan is None:
        raise PlanError("План закупок сырья не найден", status_code=404)
    return plan


def _lock(db: Session, plan_id: uuid.UUID) -> None:
    """Заблокировать план до конца транзакции.

    Без этого две одновременные правки строк читают один и тот же набор и обе
    вставляют свои строки: в плане остаётся смесь двух версий. Блокировка
    сериализует правки, отправку и утверждение — вторая ждёт первую и видит
    актуальное состояние.
    """
    locked = db.execute(
        select(PurchasePlan.id).where(PurchasePlan.id == plan_id).with_for_update()
    ).scalar_one_or_none()
    if locked is None:
        raise PlanError("План закупок сырья не найден", status_code=404)


def _check_view(user: User) -> None:
    if user.role not in VIEWERS:
        raise PlanError("План закупок сырья вам не виден", status_code=403)


def _check_editor(user: User) -> None:
    if user.role not in EDITORS:
        raise PlanError("План закупок сырья ведут закупщики", status_code=403)


def _check_executive(user: User) -> None:
    if user.role != ROLE_EXECUTIVE_DIRECTOR:
        raise PlanError("Утверждает план закупок только исполнительный директор", status_code=403)


def _check_product(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise PlanError("Товар не найден", status_code=404)
    if not product.is_active:
        raise PlanError(f"«{product.name}» отключён — строку по нему не сохранить")
    if product.kind != "raw":
        raise PlanError(f"«{product.name}» — не сырьё: в этот план попадает только сырьё")
    return product


def _check_country(db: Session, country_id: uuid.UUID) -> Country:
    country = db.get(Country, country_id)
    if country is None:
        raise PlanError("Страна не найдена", status_code=404)
    if not country.is_active:
        raise PlanError(f"«{country.name}» отключена — выберите другую страну")
    return country


def _check_supplier(db: Session, supplier_id: uuid.UUID | None) -> Counterparty | None:
    if supplier_id is None:
        return None
    supplier = db.get(Counterparty, supplier_id)
    if supplier is None:
        raise PlanError("Поставщик не найден", status_code=404)
    if not supplier.is_active:
        raise PlanError(f"«{supplier.name}» отключён — поставщиком не выбрать")
    if not (supplier.is_local_supplier or supplier.is_import_supplier):
        raise PlanError(f"«{supplier.name}» не отмечен поставщиком — в план не подходит")
    return supplier


def _check_year_editable(plan: PurchasePlan) -> None:
    if not editable_months(plan.year):
        raise PlanError("Год прошёл — план закупок доступен только для чтения", status_code=409)


def _source_positions(db: Session, plan: PurchasePlan) -> dict[uuid.UUID, NeedPosition]:
    """Официальная потребность: текущая, если годовой план согласован, иначе снимок."""
    state, _ = need.annual_state(db, plan.year)
    if state == "ok":
        return need.need_positions(db, plan.year)
    return need.snapshot_positions(plan.source_snapshot)


def _source_changes(db: Session, plan: PurchasePlan) -> list[NeedChange]:
    state, _ = need.annual_state(db, plan.year)
    if state != "ok" or plan.source_snapshot is None:
        return []
    return need.diff_positions(
        need.snapshot_positions(plan.source_snapshot),
        need.need_positions(db, plan.year),
    )


def _change_dict(change: NeedChange) -> dict[str, Any]:
    return {
        "product_id": str(change.product_id),
        "code": change.code,
        "name": change.name,
        "unit": change.unit,
        "month": change.month,
        "was": str(change.was) if change.was is not None else None,
        "now": str(change.now) if change.now is not None else None,
        "kind": change.kind,
    }


def _change_out(change: Any) -> PurchasePlanChangeOut:
    if isinstance(change, NeedChange):
        return PurchasePlanChangeOut(
            product_id=change.product_id,
            code=change.code,
            name=change.name,
            unit=change.unit,
            month=change.month,
            was=change.was,
            now=change.now,
            kind=change.kind,
        )
    return PurchasePlanChangeOut.model_validate(change)


def _source_out(db: Session, plan: PurchasePlan) -> PurchasePlanSourceOut:
    state, approval = need.annual_state(db, plan.year)
    changes = _source_changes(db, plan)

    if state == "missing":
        public_state = "missing"
        title = (
            "Годовой план продаж ещё не согласован финально — потребность появится "
            "после утверждения генеральным директором"
        )
        annual_status_title = None
    elif state == "revision":
        public_state = "revision"
        title = (
            "Годовой план продаж пересматривается — потребность показана по последней "
            "согласованной версии"
        )
        annual_status_title = (
            SALES_PLAN_APPROVAL_STATUS_TITLES.get(approval.status) if approval else None
        )
    elif state == "stale":
        public_state = "revision"
        title = (
            "Годовой план продаж изменён — потребность показана по последней "
            "согласованной версии"
        )
        annual_status_title = SALES_PLAN_APPROVAL_STATUS_TITLES["revision"]
    elif plan.source_snapshot is None:
        public_state = "no_snapshot"
        title = "Снимок плана продаж не сохранён — примите текущую потребность к сведению"
        annual_status_title = (
            SALES_PLAN_APPROVAL_STATUS_TITLES.get(approval.status) if approval else None
        )
    elif changes:
        public_state = "changed"
        title = "План продаж пересмотрен после составления плана закупок"
        annual_status_title = (
            SALES_PLAN_APPROVAL_STATUS_TITLES.get(approval.status) if approval else None
        )
    else:
        public_state = "ok"
        title = "План продаж не менялся с момента составления плана закупок"
        annual_status_title = (
            SALES_PLAN_APPROVAL_STATUS_TITLES.get(approval.status) if approval else None
        )

    history = [
        PurchasePlanSourceEventOut(
            id=event.id,
            acknowledged_at=event.acknowledged_at,
            acknowledged_by_name=(
                event.acknowledged_by.full_name if event.acknowledged_by else None
            ),
            changes=[_change_out(row) for row in event.changes],
        )
        for event in sorted(plan.source_events, key=lambda row: row.acknowledged_at, reverse=True)
    ]

    return PurchasePlanSourceOut(
        state=public_state,
        title=title,
        annual_status_title=annual_status_title,
        annual_approved_at=approval.approved_at if approval else None,
        snapshot_at=plan.source_snapshot_at,
        acknowledged_at=plan.source_acknowledged_at,
        changes=[_change_out(change) for change in changes],
        history=history,
        revision_requested_at=plan.revision_requested_at,
        revision_requested_by_name=(
            plan.revision_requested_by.full_name if plan.revision_requested_by else None
        ),
    )


def _positions_out(
    db: Session, plan: PurchasePlan, source: dict[uuid.UUID, NeedPosition]
) -> list[PurchasePlanPositionOut]:
    state, _ = need.annual_state(db, plan.year)
    snapshot = need.snapshot_positions(plan.source_snapshot)
    current = need.need_positions(db, plan.year) if state == "ok" else {}
    changes = _source_changes(db, plan)
    changed_ids = {change.product_id for change in changes}

    positions: dict[uuid.UUID, NeedPosition] = dict(source)
    status: dict[uuid.UUID, str] = {product_id: "ok" for product_id in positions}
    if state == "ok" and plan.source_snapshot is not None:
        for product_id, position in snapshot.items():
            if product_id not in current:
                positions[product_id] = position
                status[product_id] = "removed"
        for product_id in current:
            if product_id not in snapshot:
                status[product_id] = "added"

    items_by_position: dict[uuid.UUID, list[PurchasePlanItem]] = {}
    for item in plan.items:
        items_by_position.setdefault(item.sales_product_id, []).append(item)

    for product_id, items in items_by_position.items():
        if product_id in positions:
            continue
        product = items[0].sales_product
        positions[product_id] = NeedPosition(
            product_id=product_id,
            code=product.code,
            name=product.name,
            unit=product.unit,
            months={},
        )
        status[product_id] = "orphan"

    result = [
        PurchasePlanPositionOut(
            product_id=position.product_id,
            code=position.code,
            name=position.name,
            unit=position.unit,
            total=position.total,
            months=[
                PurchasePlanMonthOut(month=month, quantity=quantity)
                for month, quantity in sorted(position.months.items())
                if quantity > 0
            ],
            decomposed=bool(items_by_position.get(position.product_id)),
            status=status.get(position.product_id, "ok"),
            changed=position.product_id in changed_ids,
        )
        for position in positions.values()
    ]
    result.sort(key=lambda row: row.name)
    return result


ONE_HUNDRED = Decimal("100")
SHARE = Decimal("0.1")
ZERO = Decimal("0")


def _linked_counts(db: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Сколько позиций поступлений ссылается на каждую строку плана."""
    if not item_ids:
        return {}
    rows = db.execute(
        select(BatchItem.purchase_plan_item_id, func.count(BatchItem.id))
        .where(BatchItem.purchase_plan_item_id.in_(item_ids))
        .group_by(BatchItem.purchase_plan_item_id)
    ).all()
    return {row[0]: int(row[1]) for row in rows if row[0] is not None}


def _fact_month(day: date, plan_year: int) -> int:
    """Месяц плана для даты прихода.

    Товар, пришедший в предыдущем году (например, в декабре под январскую
    потребность), относится к январю; пришедший после планового года — к декабрю,
    чтобы ничего не потерялось и не появилось «13-го месяца».
    """
    if day.year == plan_year:
        return day.month
    return 1 if day.year < plan_year else 12


def _facts(
    db: Session, item_ids: list[uuid.UUID], plan_year: int
) -> dict[uuid.UUID, tuple[Decimal, dict[int, Decimal]]]:
    """Факт по строкам плана: всего и по месяцам прихода партий."""
    if not item_ids:
        return {}
    rows = db.execute(
        select(BatchItem.purchase_plan_item_id, BatchItem.quantity, Batch.batch_date)
        .join(Batch, Batch.id == BatchItem.batch_id)
        .where(BatchItem.purchase_plan_item_id.in_(item_ids))
    ).all()
    result: dict[uuid.UUID, tuple[Decimal, dict[int, Decimal]]] = {}
    for item_id, quantity, day in rows:
        if item_id is None:
            continue
        total, months = result.get(item_id, (ZERO, {}))
        value = Decimal(quantity)
        month = _fact_month(day, plan_year)
        months[month] = months.get(month, ZERO) + value
        result[item_id] = (total + value, months)
    return result


def _fact_share(fact: Decimal, quantity: Decimal) -> Decimal:
    if quantity <= 0:
        return ZERO
    return (fact / quantity * ONE_HUNDRED).quantize(SHARE, rounding=ROUND_HALF_UP)


def _items_out(
    plan: PurchasePlan,
    source: dict[uuid.UUID, NeedPosition],
    facts: dict[uuid.UUID, tuple[Decimal, dict[int, Decimal]]] | None = None,
) -> list[PurchasePlanItemOut]:
    fact_by_item = facts or {}
    result: list[PurchasePlanItemOut] = []
    for item in sorted(
        plan.items,
        key=lambda row: (
            row.sales_product.name,
            row.country.name,
            row.product.name,
            row.supplier.name if row.supplier else "",
        ),
    ):
        position = source.get(item.sales_product_id)
        schedule = need.split_annual(
            item.quantity,
            position.months if position else {},
            item.delivery_days,
            plan.year,
        )
        fact, fact_months = fact_by_item.get(item.id, (ZERO, {}))
        result.append(
            PurchasePlanItemOut(
                id=item.id,
                sales_product_id=item.sales_product_id,
                sales_product_name=item.sales_product.name,
                product_id=item.product_id,
                product_code=item.product.code,
                product_name=item.product.name,
                product_kind=item.product.kind,
                unit=item.product.unit,
                country_id=item.country_id,
                country_name=item.country.name,
                delivery_days=item.delivery_days,
                quantity=item.quantity,
                price_rub=item.price_rub,
                supplier_id=item.supplier_id,
                supplier_name=item.supplier.name if item.supplier else None,
                notes=item.notes,
                fact_quantity=fact,
                fact_share=_fact_share(fact, item.quantity),
                fact_months=[
                    PurchasePlanMonthOut(month=month, quantity=quantity)
                    for month, quantity in sorted(fact_months.items())
                ],
                schedule=[
                    PurchasePlanScheduleEntryOut(
                        month=entry.month,
                        quantity=entry.quantity,
                        order_year=entry.order_year,
                        order_month=entry.order_month,
                        overdue=entry.overdue,
                    )
                    for entry in schedule
                ],
            )
        )
    return result


def _serialize(db: Session, plan: PurchasePlan) -> PurchasePlanOut:
    source = _source_positions(db, plan)
    facts = _facts(db, [item.id for item in plan.items], plan.year)
    return PurchasePlanOut(
        id=plan.id,
        year=plan.year,
        status=plan.status,
        status_title=PURCHASE_PLAN_STATUS_TITLES.get(plan.status, plan.status),
        created_by_name=plan.created_by.full_name,
        approved_by_name=plan.approved_by.full_name if plan.approved_by else None,
        approved_at=plan.approved_at,
        notes=plan.notes,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        editable_months=editable_months(plan.year),
        source=_source_out(db, plan),
        positions=_positions_out(db, plan, source),
        items=_items_out(plan, source, facts),
    )


def list_plans(db: Session, user: User, *, year: int | None = None) -> list[PurchasePlanOut]:
    _check_view(user)
    statement = (
        select(PurchasePlan)
        .options(selectinload(PurchasePlan.items))
        .options(
            selectinload(PurchasePlan.source_events).selectinload(
                PurchasePlanSourceEvent.acknowledged_by
            )
        )
        .order_by(PurchasePlan.year.desc())
    )
    if year is not None:
        statement = statement.where(PurchasePlan.year == year)
    return [_serialize(db, plan) for plan in db.execute(statement).scalars().all()]


def get_plan(db: Session, user: User, plan_id: uuid.UUID) -> PurchasePlanOut:
    _check_view(user)
    return _serialize(db, _require(db, plan_id))


def _require_annual(db: Session, year: int) -> SalesPlanApproval:
    state, approval = need.annual_state(db, year)
    if state == "missing":
        raise PlanError(
            f"На {year} год нет годового плана продаж — план закупок строится на его основе",
            status_code=409,
        )
    if state == "revision":
        raise PlanError(
            f"Годовой план продаж на {year} год ещё не согласован финально", status_code=409
        )
    if state == "stale":
        raise PlanError(
            f"Годовой план продаж на {year} год изменён — сначала повторно согласуйте его",
            status_code=409,
        )
    assert approval is not None
    return approval


def create_plan(db: Session, user: User, payload: PurchasePlanCreate) -> PurchasePlanOut:
    _check_editor(user)
    approval = _require_annual(db, payload.year)
    positions = need.need_positions(db, payload.year)
    snapshot = need.build_snapshot(positions, approval)
    now = _now()
    plan = PurchasePlan(
        year=payload.year,
        created_by_id=user.id,
        status="draft",
        notes=payload.notes,
        source_snapshot=snapshot,
        source_hash=str(snapshot["hash"]),
        source_snapshot_at=now,
        source_acknowledged_at=now,
    )
    db.add(plan)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PlanError(
            f"План закупок сырья на {payload.year} год уже есть", status_code=409
        ) from exc
    return _serialize(db, _require(db, plan.id))


def _allowed_positions(db: Session, plan: PurchasePlan) -> set[uuid.UUID]:
    """Позиции текущего плана продаж и снимка: строки исчезнувших позиций не теряем."""
    state, _ = need.annual_state(db, plan.year)
    if state == "ok":
        return set(need.need_positions(db, plan.year)) | set(
            need.snapshot_positions(plan.source_snapshot)
        )
    return set(need.snapshot_positions(plan.source_snapshot))


def update_items(
    db: Session,
    user: User,
    plan_id: uuid.UUID,
    items: list[PurchasePlanItemIn],
) -> PurchasePlanOut:
    """Сохранить строки: существующие обновляются на месте, новые добавляются.

    Строки плана — цели ссылок поступлений, поэтому у них постоянный ``id``.
    Убранную строку, с которой связаны поступления, убрать нельзя: сначала
    закупщик снимает привязку в карточках. У связанной строки нельзя менять
    сырьё, страну и позицию плана продаж — иначе факт приписался бы другому.
    """
    _lock(db, plan_id)
    plan = _require(db, plan_id)
    _check_editor(user)
    if plan.status != "draft":
        raise PlanError("План на проверке или утверждён — правки недоступны", status_code=409)
    _check_year_editable(plan)

    allowed = _allowed_positions(db, plan)
    existing = {row.id: row for row in plan.items}
    linked = set(_linked_counts(db, list(existing)))
    prepared: list[tuple[PurchasePlanItemIn, int, PurchasePlanItem | None]] = []
    seen: set[uuid.UUID] = set()
    for item in items:
        stored: PurchasePlanItem | None = None
        if item.id is not None:
            if item.id in seen:
                raise PlanError("Строка плана повторяется в запросе", status_code=400)
            seen.add(item.id)
            stored = existing.get(item.id)
            if stored is None:
                raise PlanError("Строка плана не найдена — обновите план", status_code=400)
        if item.sales_product_id not in allowed:
            raise PlanError(
                "Этой позиции нет в плане продаж — строку по ней не сохранить", status_code=400
            )
        if item.quantity <= 0:
            raise PlanError("Количество должно быть больше нуля")
        if item.price_rub is not None and item.price_rub < 0:
            raise PlanError("Цена не может быть отрицательной")
        _check_product(db, item.product_id)
        country = _check_country(db, item.country_id)
        _check_supplier(db, item.supplier_id)
        prepared.append((item, country.delivery_days, stored))

    for item, _, stored in prepared:
        if stored is None or stored.id not in linked:
            continue
        if (
            stored.sales_product_id != item.sales_product_id
            or stored.product_id != item.product_id
            or stored.country_id != item.country_id
        ):
            raise PlanError(
                f"Строка «{stored.product.name}» ({stored.country.name}) связана с "
                "поступлениями: сырьё, страну и позицию плана продаж менять нельзя. "
                "Сначала снимите привязку в карточках поступлений",
                status_code=409,
            )

    removed = [row for row_id, row in existing.items() if row_id not in seen]
    if removed:
        counts = _linked_counts(db, [row.id for row in removed])
        if counts:
            row = next(row for row in removed if row.id in counts)
            raise PlanError(
                f"Строку «{row.product.name}» ({row.country.name}) нельзя убрать: "
                f"с ней связано поступлений: {counts[row.id]}. Сначала снимите привязку "
                "в карточках поступлений",
                status_code=409,
            )
        for row in removed:
            db.delete(row)

    for item, delivery_days, stored in prepared:
        if stored is None:
            db.add(
                PurchasePlanItem(
                    plan_id=plan.id,
                    sales_product_id=item.sales_product_id,
                    product_id=item.product_id,
                    country_id=item.country_id,
                    quantity=item.quantity,
                    price_rub=item.price_rub,
                    supplier_id=item.supplier_id,
                    delivery_days=delivery_days,
                    notes=item.notes,
                )
            )
            continue
        stored.sales_product_id = item.sales_product_id
        stored.product_id = item.product_id
        stored.country_id = item.country_id
        stored.quantity = item.quantity
        stored.price_rub = item.price_rub
        stored.supplier_id = item.supplier_id
        stored.delivery_days = delivery_days
        stored.notes = item.notes

    db.commit()
    return _serialize(db, _require(db, plan_id))


def _ensure_source_acknowledged(db: Session, plan: PurchasePlan) -> None:
    if _source_changes(db, plan):
        raise PlanError(
            "План продаж изменился — примите изменения к сведению перед отправкой",
            status_code=409,
        )


def submit(db: Session, user: User, plan_id: uuid.UUID) -> PurchasePlanOut:
    _lock(db, plan_id)
    plan = _require(db, plan_id)
    _check_editor(user)
    if plan.status != "draft":
        raise PlanError("План уже на проверке или утверждён", status_code=409)
    if not plan.items:
        raise PlanError("Нельзя отправить пустой план: добавьте хотя бы одну строку")
    if any(item.price_rub is None for item in plan.items):
        raise PlanError("Укажите цену у всех строк: без цены план не отправить")
    _ensure_source_acknowledged(db, plan)
    plan.status = "on_review"
    plan.revision_requested_at = None
    plan.revision_requested_by_id = None
    db.commit()
    return _serialize(db, _require(db, plan_id))


def approve(db: Session, user: User, plan_id: uuid.UUID) -> PurchasePlanOut:
    _check_executive(user)
    _lock(db, plan_id)
    plan = _require(db, plan_id)
    if plan.status != "on_review":
        raise PlanError("Утвердить можно только план на проверке", status_code=409)
    _ensure_source_acknowledged(db, plan)
    plan.status = "approved"
    plan.approved_by_id = user.id
    plan.approved_at = _now()
    plan.revision_requested_at = None
    plan.revision_requested_by_id = None
    db.commit()
    return _serialize(db, _require(db, plan_id))


def _append_note(current: str | None, note: str) -> str:
    return f"{current}\n{note}" if current else note


def reject(db: Session, user: User, plan_id: uuid.UUID, reason: str) -> PurchasePlanOut:
    _check_executive(user)
    _lock(db, plan_id)
    plan = _require(db, plan_id)
    if plan.status != "on_review":
        raise PlanError("Вернуть на доработку можно только план на проверке", status_code=409)
    plan.status = "draft"
    plan.approved_by_id = None
    plan.approved_at = None
    plan.revision_requested_at = None
    plan.revision_requested_by_id = None
    if reason:
        plan.notes = _append_note(plan.notes, f"Возврат на доработку: {reason}")
    db.commit()
    return _serialize(db, _require(db, plan_id))


def reopen(db: Session, user: User, plan_id: uuid.UUID, reason: str) -> PurchasePlanOut:
    """Вернуть утверждённый план в работу: только исполнительный директор."""
    _check_executive(user)
    _lock(db, plan_id)
    plan = _require(db, plan_id)
    if plan.status != "approved":
        raise PlanError("Вернуть в работу можно только утверждённый план", status_code=409)
    plan.status = "draft"
    plan.approved_by_id = None
    plan.approved_at = None
    plan.revision_requested_at = None
    plan.revision_requested_by_id = None
    if reason:
        plan.notes = _append_note(plan.notes, f"Возврат в работу: {reason}")
    db.commit()
    return _serialize(db, _require(db, plan_id))


def acknowledge_source(db: Session, user: User, plan_id: uuid.UUID) -> PurchasePlanOut:
    """Принять изменения плана продаж к сведению: обновить снимок и записать историю."""
    _lock(db, plan_id)
    plan = _require(db, plan_id)
    _check_editor(user)
    state, approval = need.annual_state(db, plan.year)
    if state != "ok":
        raise PlanError(
            "Годовой план продаж не согласован финально — принять изменения нельзя",
            status_code=409,
        )

    current = need.need_positions(db, plan.year)
    changes = need.diff_positions(need.snapshot_positions(plan.source_snapshot), current)
    snapshot = need.build_snapshot(current, approval)
    now = _now()
    plan.source_snapshot = snapshot
    plan.source_hash = str(snapshot["hash"])
    plan.source_snapshot_at = now
    plan.source_acknowledged_at = now
    if changes:
        db.add(
            PurchasePlanSourceEvent(
                plan_id=plan.id,
                acknowledged_by_id=user.id,
                source_hash=str(snapshot["hash"]),
                changes=[_change_dict(change) for change in changes],
                acknowledged_at=now,
            )
        )
    db.commit()
    return _serialize(db, _require(db, plan_id))


def request_revision(db: Session, user: User, plan_id: uuid.UUID, reason: str) -> PurchasePlanOut:
    """Попросить исполнительного директора вернуть утверждённый план в работу."""
    _lock(db, plan_id)
    plan = _require(db, plan_id)
    _check_editor(user)
    if plan.status != "approved":
        raise PlanError("Запросить пересмотр можно только у утверждённого плана", status_code=409)
    plan.revision_requested_at = _now()
    plan.revision_requested_by_id = user.id
    if reason:
        plan.notes = _append_note(plan.notes, f"Запрошен пересмотр: {reason}")
    db.commit()
    return _serialize(db, _require(db, plan_id))


def delete_plan(db: Session, user: User, plan_id: uuid.UUID) -> None:
    if user.role != ROLE_PURCHASE_DIRECTOR:
        raise PlanError("Удалить план закупок может только директор по закупкам", status_code=403)
    _lock(db, plan_id)
    plan = _require(db, plan_id)
    if plan.status != "draft":
        raise PlanError("Удалить можно только черновик", status_code=409)
    if _linked_counts(db, [row.id for row in plan.items]):
        raise PlanError(
            "На строки плана ссылаются поступления — сначала снимите привязки "
            "в карточках поступлений",
            status_code=409,
        )
    db.delete(plan)
    db.commit()
