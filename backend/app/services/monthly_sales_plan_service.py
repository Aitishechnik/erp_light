"""Помесячный план продаж: окно пересмотра, правка строк, утверждение.

Окно — с 23-го числа предыдущего месяца по его последний день. В окне менеджер
правит количество по своим клиентам и товарам. Снижение ниже годового плана
требует причины, повышение — по желанию. После окна план фиксируется: если его
не утвердили вручную, он утверждается автоматически. Если месяц не трогали,
помесячного плана нет — в сравнении он равен годовому.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import User
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.monthly_plans import (
    MONTHLY_PLAN_EVENT_TITLES,
    MONTHLY_PLAN_STATUS_TITLES,
    MonthlySalesPlan,
    MonthlySalesPlanEvent,
    MonthlySalesPlanItem,
)
from app.models.planning import SalesPlan
from app.permissions import can, scope_for
from app.schemas.monthly_plans import (
    MonthlyPlanEventOut,
    MonthlyPlanItemIn,
    MonthlyPlanItemOut,
    MonthlyPlanOut,
)

ZERO = Decimal("0")
MAX_QUANTITY = Decimal("999999999999.999")


class MonthlyPlanError(Exception):
    """Нарушение правила помесячного плана; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def previous_month_end(year: int, month: int) -> date:
    """Последний день месяца перед планируемым."""
    return date(year, month, 1) - timedelta(days=1)


def window_bounds(year: int, month: int) -> tuple[date, date]:
    """Окно пересмотра: с 23-го по последний день предыдущего месяца."""
    end = previous_month_end(year, month)
    return end.replace(day=23), end


def window_state(year: int, month: int, *, today: date | None = None) -> str:
    """Состояние окна: not_started | open | closed."""
    current = today or date.today()
    start, end = window_bounds(year, month)
    if current < start:
        return "not_started"
    if current > end:
        return "closed"
    return "open"


def _now() -> datetime:
    return datetime.now(UTC)


def _resolve_manager(user: User, manager_id: uuid.UUID | None) -> uuid.UUID:
    if manager_id is not None:
        return manager_id
    if scope_for(user, "monthly_plan", "view") == "own":
        return user.id
    raise MonthlyPlanError("Укажите менеджера", status_code=400)


def _check_view(user: User, manager_id: uuid.UUID) -> None:
    if not can(user, "monthly_plan", "view"):
        raise MonthlyPlanError("Помесячный план вам не виден", status_code=403)
    if scope_for(user, "monthly_plan", "view") == "own" and manager_id != user.id:
        raise MonthlyPlanError("Этот план вам не виден", status_code=403)


def _check_editor(user: User, manager_id: uuid.UUID) -> None:
    if not can(user, "monthly_plan", "edit"):
        raise MonthlyPlanError("Правка плана вам недоступна", status_code=403)
    if scope_for(user, "monthly_plan", "edit") == "own" and manager_id != user.id:
        raise MonthlyPlanError("Правка плана вам недоступна", status_code=403)


def _check_commercial(user: User) -> None:
    if not can(user, "monthly_plan", "approve"):
        raise MonthlyPlanError("Утверждать помесячный план вам недоступно", status_code=403)


def _load(db: Session, year: int, month: int, manager_id: uuid.UUID) -> MonthlySalesPlan | None:
    return (
        db.execute(
            select(MonthlySalesPlan)
            .where(
                MonthlySalesPlan.year == year,
                MonthlySalesPlan.month == month,
                MonthlySalesPlan.manager_id == manager_id,
            )
            .options(selectinload(MonthlySalesPlan.items).selectinload(MonthlySalesPlanItem.client))
            .options(
                selectinload(MonthlySalesPlan.items).selectinload(MonthlySalesPlanItem.product)
            )
            .options(
                selectinload(MonthlySalesPlan.items).selectinload(MonthlySalesPlanItem.updated_by)
            )
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one_or_none()
    )


def _require(db: Session, year: int, month: int, manager_id: uuid.UUID) -> MonthlySalesPlan:
    plan = _load(db, year, month, manager_id)
    if plan is None:
        raise MonthlyPlanError("Месячный план не найден", status_code=404)
    return plan


def _annual_plan(db: Session, year: int, manager_id: uuid.UUID) -> SalesPlan:
    plan = (
        db.execute(
            select(SalesPlan)
            .where(
                SalesPlan.year == year,
                SalesPlan.manager_id == manager_id,
                SalesPlan.status == "approved",
            )
            .options(selectinload(SalesPlan.items))
        )
        .scalars()
        .one_or_none()
    )
    if plan is None:
        raise MonthlyPlanError(
            "Годовой план менеджера на этот год не утверждён — пересматривать нечего",
            status_code=409,
        )
    return plan


def _annual_map(
    db: Session, year: int, month: int, manager_id: uuid.UUID
) -> dict[tuple[uuid.UUID, uuid.UUID], Decimal]:
    plan = _annual_plan(db, year, manager_id)
    return {
        (item.client_id, item.product_id): item.quantity
        for item in plan.items
        if item.month == month
    }


def _event(
    db: Session,
    plan: MonthlySalesPlan,
    user: User,
    *,
    kind: str,
    client_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    old_quantity: Decimal | None = None,
    new_quantity: Decimal | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        MonthlySalesPlanEvent(
            plan_id=plan.id,
            kind=kind,
            client_id=client_id,
            product_id=product_id,
            old_quantity=old_quantity,
            new_quantity=new_quantity,
            reason=reason,
            actor_id=user.id,
        )
    )


def _auto_approve(db: Session, plan: MonthlySalesPlan) -> None:
    """План не утвердили до конца окна — фиксируем как есть."""
    approved_at = _now()
    plan.status = "approved"
    plan.approved_at = approved_at
    plan.approved_by_id = None
    db.add(
        MonthlySalesPlanEvent(
            plan_id=plan.id,
            kind="auto_approve",
            actor_id=None,
            created_at=approved_at,
        )
    )
    db.commit()


def _create_from_annual(
    db: Session, user: User, year: int, month: int, manager_id: uuid.UUID
) -> MonthlySalesPlan:
    annual = _annual_map(db, year, month, manager_id)
    plan = MonthlySalesPlan(year=year, month=month, manager_id=manager_id, status="draft")
    db.add(plan)
    db.flush()
    for (client_id, product_id), quantity in annual.items():
        db.add(
            MonthlySalesPlanItem(
                plan_id=plan.id,
                client_id=client_id,
                product_id=product_id,
                annual_quantity=quantity,
                quantity=quantity,
                updated_by_id=user.id,
            )
        )
    if window_state(year, month) == "closed":
        approved_at = _now()
        plan.status = "approved"
        plan.approved_at = approved_at
        db.add(
            MonthlySalesPlanEvent(
                plan_id=plan.id,
                kind="auto_approve",
                actor_id=None,
                created_at=approved_at,
            )
        )
    db.commit()
    return _require(db, year, month, manager_id)


def _item_out(
    item: MonthlySalesPlanItem, annual_keys: set[tuple[uuid.UUID, uuid.UUID]]
) -> MonthlyPlanItemOut:
    key = (item.client_id, item.product_id)
    return MonthlyPlanItemOut(
        client_id=item.client_id,
        client_name=item.client.name,
        product_id=item.product_id,
        product_code=item.product.code,
        product_name=item.product.name,
        unit=item.product.unit,
        annual_quantity=item.annual_quantity,
        quantity=item.quantity,
        reason=item.reason,
        is_new=key not in annual_keys,
        is_removed=key in annual_keys and item.quantity == ZERO and item.annual_quantity > ZERO,
        updated_at=item.updated_at,
        updated_by_name=item.updated_by.full_name if item.updated_by is not None else None,
    )


def _serialize(db: Session, plan: MonthlySalesPlan, user: User) -> MonthlyPlanOut:
    annual = _annual_map(db, plan.year, plan.month, plan.manager_id)
    annual_keys = set(annual)
    items = sorted(plan.items, key=lambda row: (row.client.name, row.product.name))
    changed = sum(1 for item in items if item.quantity != item.annual_quantity)
    state = window_state(plan.year, plan.month)
    may_edit = can(user, "monthly_plan", "edit") and (
        scope_for(user, "monthly_plan", "edit") == "all" or plan.manager_id == user.id
    )
    can_edit = plan.status == "draft" and state == "open" and may_edit
    can_approve = plan.status == "draft" and can(user, "monthly_plan", "approve")
    start, end = window_bounds(plan.year, plan.month)
    return MonthlyPlanOut(
        year=plan.year,
        month=plan.month,
        manager_id=plan.manager_id,
        manager_name=plan.manager.full_name,
        status=plan.status,
        status_title=MONTHLY_PLAN_STATUS_TITLES.get(plan.status, plan.status),
        window_start=start,
        window_end=end,
        window_state=state,
        can_edit=can_edit,
        can_approve=can_approve,
        approved_at=plan.approved_at,
        approved_by_name=(plan.approved_by.full_name if plan.approved_by is not None else None),
        changed_lines=changed,
        items=[_item_out(item, annual_keys) for item in items],
    )


def get_plan(
    db: Session,
    user: User,
    year: int,
    month: int,
    manager_id: uuid.UUID | None = None,
) -> MonthlyPlanOut:
    """Помесячный план; до открытия окна его ещё нет, после закрытия он фиксируется."""
    target = _resolve_manager(user, manager_id)
    _check_view(user, target)
    plan = _load(db, year, month, target)
    if plan is None:
        if window_state(year, month) == "not_started":
            raise MonthlyPlanError(
                "Окно пересмотра ещё не открылось: оно начинается 23-го числа предыдущего месяца",
                status_code=409,
            )
        plan = _create_from_annual(db, user, year, month, target)
    elif plan.status == "draft" and window_state(year, month) == "closed":
        _auto_approve(db, plan)
        plan = _require(db, year, month, target)
    return _serialize(db, plan, user)


def _check_clients(db: Session, client_ids: set[uuid.UUID]) -> None:
    for client_id in client_ids:
        client = db.get(Counterparty, client_id)
        if client is None:
            raise MonthlyPlanError("Клиент не найден", status_code=404)
        if not client.is_active:
            raise MonthlyPlanError(f"Клиент «{client.name}» отключён — строку не сохранить")
        if not client.is_customer:
            raise MonthlyPlanError(
                f"«{client.name}» не отмечен покупателем — в плане продаж не используется"
            )


def update_items(
    db: Session,
    user: User,
    year: int,
    month: int,
    items: list[MonthlyPlanItemIn],
    manager_id: uuid.UUID | None = None,
) -> MonthlyPlanOut:
    """Полная замена строк месяца; причина обязательна для каждой изменённой строки."""
    target = _resolve_manager(user, manager_id)
    _check_editor(user, target)
    if window_state(year, month) != "open":
        raise MonthlyPlanError(
            "Окно пересмотра закрыто: правки — только с 23-го числа предыдущего месяца "
            "по его последний день",
            status_code=409,
        )
    plan = _load(db, year, month, target)
    if plan is None:
        plan = _create_from_annual(db, user, year, month, target)
    if plan.status != "draft":
        raise MonthlyPlanError("План уже утверждён — правки недоступны", status_code=409)

    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for item in items:
        key = (item.client_id, item.product_id)
        if key in seen:
            raise MonthlyPlanError("В плане две строки на одного клиента и товар")
        seen.add(key)
        if item.quantity < ZERO or item.quantity > MAX_QUANTITY:
            raise MonthlyPlanError("Количество вне допустимого диапазона")

    annual = _annual_map(db, year, month, target)
    # Отключённый клиент мог остаться в годовом плане: не блокируем из-за него
    # сохранение, проверяем только новые строки.
    _check_clients(
        db,
        {item.client_id for item in items if (item.client_id, item.product_id) not in annual},
    )
    missing = set(annual) - seen
    if missing:
        client_id, product_id = next(iter(missing))
        client = db.get(Counterparty, client_id)
        name = client.name if client is not None else "клиент"
        raise MonthlyPlanError(
            f"В плане пропала строка «{name}»: чтобы убрать позицию, поставьте 0 и укажите причину"
        )

    existing = {(item.client_id, item.product_id): item for item in plan.items}
    prepared: list[tuple[MonthlyPlanItemIn, Decimal, str | None]] = []
    for item in items:
        key = (item.client_id, item.product_id)
        previous = existing.get(key)
        annual_quantity = (
            previous.annual_quantity if previous is not None else annual.get(key, ZERO)
        )
        reason: str | None = (item.reason or "").strip() or None
        if item.quantity < annual_quantity and not reason:
            client = db.get(Counterparty, item.client_id)
            product = db.get(Product, item.product_id)
            client_name = client.name if client is not None else "клиент"
            product_name = product.name if product is not None else "позиция"
            raise MonthlyPlanError(
                f"Укажите причину: «{client_name}», {product_name} — " "цифра ниже годового плана"
            )
        if item.quantity == annual_quantity:
            reason = None
        prepared.append((item, annual_quantity, reason))

    changed = 0
    for item, _annual_quantity, reason in prepared:
        key = (item.client_id, item.product_id)
        previous = existing.get(key)
        old_quantity = previous.quantity if previous is not None else None
        old_reason = (previous.reason or None) if previous is not None else None
        if previous is not None and old_quantity == item.quantity and old_reason == reason:
            continue
        changed += 1
        _event(
            db,
            plan,
            user,
            kind="edit",
            client_id=item.client_id,
            product_id=item.product_id,
            old_quantity=old_quantity,
            new_quantity=item.quantity,
            reason=reason,
        )
    for key, previous in existing.items():
        if key not in seen and previous.quantity != ZERO:
            changed += 1
            _event(
                db,
                plan,
                user,
                kind="edit",
                client_id=key[0],
                product_id=key[1],
                old_quantity=previous.quantity,
                new_quantity=ZERO,
                reason=previous.reason,
            )

    for previous in list(plan.items):
        db.delete(previous)
    db.flush()
    for item, annual_quantity, reason in prepared:
        db.add(
            MonthlySalesPlanItem(
                plan_id=plan.id,
                client_id=item.client_id,
                product_id=item.product_id,
                annual_quantity=annual_quantity,
                quantity=item.quantity,
                reason=reason,
                updated_by_id=user.id,
            )
        )
    if changed:
        plan.updated_at = _now()
    db.commit()
    return _serialize(db, _require(db, year, month, target), user)


def approve(
    db: Session,
    user: User,
    year: int,
    month: int,
    manager_id: uuid.UUID | None = None,
) -> MonthlyPlanOut:
    """Коммерческий директор утверждает месячный план."""
    target = _resolve_manager(user, manager_id)
    _check_commercial(user)
    plan = _require(db, year, month, target)
    if plan.status != "draft":
        raise MonthlyPlanError("План уже утверждён", status_code=409)
    for item in plan.items:
        if item.quantity < item.annual_quantity and not (item.reason or "").strip():
            raise MonthlyPlanError(
                "В плане есть снижение ниже годового плана без причины — утвердить нельзя"
            )
    plan.status = "approved"
    plan.approved_at = _now()
    plan.approved_by_id = user.id
    _event(db, plan, user, kind="approve")
    db.commit()
    return _serialize(db, _require(db, year, month, target), user)


def history(
    db: Session,
    user: User,
    year: int,
    month: int,
    manager_id: uuid.UUID | None = None,
) -> list[MonthlyPlanEventOut]:
    target = _resolve_manager(user, manager_id)
    _check_view(user, target)
    plan = _load(db, year, month, target)
    if plan is None:
        return []
    rows = (
        db.execute(
            select(MonthlySalesPlanEvent)
            .where(MonthlySalesPlanEvent.plan_id == plan.id)
            .options(selectinload(MonthlySalesPlanEvent.actor))
            .options(selectinload(MonthlySalesPlanEvent.client))
            .options(selectinload(MonthlySalesPlanEvent.product))
            .order_by(MonthlySalesPlanEvent.created_at)
        )
        .scalars()
        .all()
    )
    return [
        MonthlyPlanEventOut(
            kind=row.kind,
            kind_title=MONTHLY_PLAN_EVENT_TITLES.get(row.kind, row.kind),
            created_at=row.created_at,
            actor_name=row.actor.full_name if row.actor is not None else None,
            client_id=row.client_id,
            client_name=row.client.name if row.client is not None else None,
            product_id=row.product_id,
            product_name=row.product.name if row.product is not None else None,
            old_quantity=row.old_quantity,
            new_quantity=row.new_quantity,
            reason=row.reason,
        )
        for row in rows
    ]
