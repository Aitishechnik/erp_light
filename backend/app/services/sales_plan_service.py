"""Годовой план продаж: создание, заполнение, согласование.

Цепочка статусов: черновик → заполняется → на проверке → утверждён.
Права: менеджер по продажам ведёт свой план, коммерческий директор создаёт план
на любого менеджера и утверждает/отклоняет, исполнительный директор видит всё.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_SALES_MANAGER,
    User,
)
from app.models.clients import Client
from app.models.planning import (
    SALES_PLAN_STATUS_TITLES,
    SalesPlan,
    SalesPlanItem,
)
from app.schemas.planning import SalesPlanCreate, SalesPlanItemIn, SalesPlanItemOut, SalesPlanOut
from app.services.cost import q2
from app.services.plan_freeze import check_months_editable, editable_months

ZERO = Decimal("0.00")
EDITABLE_BY_OWNER = ("draft", "filling")


class PlanError(Exception):
    """Нарушение бизнес-правила плана; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _load(db: Session, plan_id: uuid.UUID) -> SalesPlan | None:
    return (
        db.execute(
            select(SalesPlan)
            .where(SalesPlan.id == plan_id)
            .options(selectinload(SalesPlan.items).selectinload(SalesPlanItem.product))
            .options(selectinload(SalesPlan.items).selectinload(SalesPlanItem.client))
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one_or_none()
    )


def _require(db: Session, plan_id: uuid.UUID) -> SalesPlan:
    plan = _load(db, plan_id)
    if plan is None:
        raise PlanError("План не найден", status_code=404)
    return plan


def _is_overseer(user: User) -> bool:
    return user.role in (ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR)


def _check_view(user: User, plan: SalesPlan) -> None:
    if _is_overseer(user):
        return
    if user.role == ROLE_SALES_MANAGER and plan.manager_id == user.id:
        return
    raise PlanError("Этот план вам не виден", status_code=403)


def _check_commercial_director(user: User) -> None:
    if user.role != ROLE_COMMERCIAL_DIRECTOR:
        raise PlanError("Действие доступно только коммерческому директору", status_code=403)


def _check_clients(db: Session, client_ids: set[uuid.UUID]) -> None:
    """Все клиенты строк должны существовать и быть активными."""
    for client_id in client_ids:
        client = db.get(Client, client_id)
        if client is None:
            raise PlanError("Клиент не найден", status_code=404)
        if not client.is_active:
            raise PlanError(f"Клиент «{client.name}» отключён — строку по нему не сохранить")


def _serialize(plan: SalesPlan) -> SalesPlanOut:
    items = [
        SalesPlanItemOut(
            id=item.id,
            client_id=item.client_id,
            client_name=item.client.name,
            product_id=item.product_id,
            product_code=item.product.code,
            product_name=item.product.name,
            product_kind=item.product.kind,
            unit=item.product.unit,
            month=item.month,
            quantity=item.quantity,
            price=item.price,
            amount=q2(item.quantity * item.price) if item.price is not None else None,
            notes=item.notes,
        )
        for item in sorted(
            plan.items, key=lambda row: (row.client.name, row.product.name, row.month)
        )
    ]
    total = sum((item.amount for item in items if item.amount is not None), ZERO)
    return SalesPlanOut(
        id=plan.id,
        year=plan.year,
        manager_id=plan.manager_id,
        manager_name=plan.manager.full_name,
        created_by_name=plan.created_by.full_name,
        status=plan.status,
        status_title=SALES_PLAN_STATUS_TITLES.get(plan.status, plan.status),
        notes=plan.notes,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        editable_months=editable_months(plan.year),
        items=items,
        total_amount=q2(total),
    )


def list_plans(db: Session, user: User, *, year: int | None = None) -> list[SalesPlanOut]:
    """Список планов: менеджер видит свои, коммерческий и исполнительный — все."""
    statement = (
        select(SalesPlan)
        .options(selectinload(SalesPlan.items).selectinload(SalesPlanItem.product))
        .options(selectinload(SalesPlan.items).selectinload(SalesPlanItem.client))
        .order_by(SalesPlan.year.desc(), SalesPlan.created_at)
    )
    if user.role == ROLE_SALES_MANAGER:
        statement = statement.where(SalesPlan.manager_id == user.id)
    elif not _is_overseer(user):
        raise PlanError("Планы продаж вам не видны", status_code=403)
    if year is not None:
        statement = statement.where(SalesPlan.year == year)
    return [_serialize(plan) for plan in db.execute(statement).scalars().all()]


def get_plan(db: Session, user: User, plan_id: uuid.UUID) -> SalesPlanOut:
    plan = _require(db, plan_id)
    _check_view(user, plan)
    return _serialize(plan)


def create_plan(db: Session, user: User, payload: SalesPlanCreate) -> SalesPlanOut:
    """Менеджер создаёт свой план; коммерческий директор — на любого менеджера."""
    if user.role == ROLE_SALES_MANAGER:
        manager_id = user.id
    elif user.role == ROLE_COMMERCIAL_DIRECTOR:
        if payload.manager_id is None:
            raise PlanError("Укажите менеджера, на которого создаётся план")
        manager_id = payload.manager_id
    else:
        raise PlanError(
            "Создавать план продаж может менеджер или коммерческий директор", status_code=403
        )

    manager = db.get(User, manager_id)
    if manager is None or not manager.is_active:
        raise PlanError("Менеджер не найден", status_code=404)
    if manager.role != ROLE_SALES_MANAGER:
        raise PlanError("План продаж заводится только на менеджера по продажам")

    plan = SalesPlan(
        year=payload.year,
        manager_id=manager.id,
        created_by_id=user.id,
        status="draft",
        notes=payload.notes,
    )
    db.add(plan)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PlanError(
            f"План на {payload.year} год для этого менеджера уже есть", status_code=409
        ) from exc
    created = _require(db, plan.id)
    return _serialize(created)


def update_items(
    db: Session, user: User, plan_id: uuid.UUID, items: list[SalesPlanItemIn]
) -> SalesPlanOut:
    """Полная замена строк по редактируемым месяцам.

    Замороженные месяцы менять нельзя — запрос с ними отклоняется целиком.
    """
    plan = _require(db, plan_id)
    _check_view(user, plan)

    is_owner = user.role == ROLE_SALES_MANAGER and plan.manager_id == user.id
    if is_owner:
        if plan.status not in EDITABLE_BY_OWNER:
            raise PlanError("План на проверке или утверждён — правки недоступны", status_code=409)
    elif user.role != ROLE_COMMERCIAL_DIRECTOR:
        raise PlanError("Правка плана вам недоступна", status_code=403)

    check_months_editable(plan.year, {item.month for item in items})

    seen: set[tuple[uuid.UUID, uuid.UUID, int]] = set()
    for item in items:
        key = (item.client_id, item.product_id, item.month)
        if key in seen:
            raise PlanError("В плане две строки на одного клиента, товар и месяц")
        seen.add(key)

    _check_clients(db, {item.client_id for item in items})

    allowed = set(editable_months(plan.year))
    for existing in list(plan.items):
        if existing.month in allowed:
            db.delete(existing)
    db.flush()

    for item in items:
        db.add(
            SalesPlanItem(
                plan_id=plan.id,
                client_id=item.client_id,
                product_id=item.product_id,
                month=item.month,
                quantity=item.quantity,
                price=item.price,
                notes=item.notes,
            )
        )

    if plan.status == "approved":
        plan.status = "on_review"
    db.commit()
    return _serialize(_require(db, plan_id))


def send_to_fill(db: Session, user: User, plan_id: uuid.UUID) -> SalesPlanOut:
    """Коммерческий директор отдаёт план менеджеру на заполнение."""
    _check_commercial_director(user)
    plan = _require(db, plan_id)
    if plan.status != "draft":
        raise PlanError("На заполнение отправляется только черновик", status_code=409)
    plan.status = "filling"
    db.commit()
    return _serialize(_require(db, plan_id))


def submit(db: Session, user: User, plan_id: uuid.UUID) -> SalesPlanOut:
    """Менеджер отправляет свой план на проверку."""
    plan = _require(db, plan_id)
    if not (user.role == ROLE_SALES_MANAGER and plan.manager_id == user.id):
        raise PlanError("Отправить план может только его менеджер", status_code=403)
    if plan.status not in EDITABLE_BY_OWNER:
        raise PlanError("План уже на проверке или утверждён", status_code=409)
    if not plan.items:
        raise PlanError("Нельзя отправить пустой план: заполните хотя бы одну строку")
    plan.status = "on_review"
    db.commit()
    return _serialize(_require(db, plan_id))


def approve(db: Session, user: User, plan_id: uuid.UUID) -> SalesPlanOut:
    """Коммерческий директор утверждает план."""
    _check_commercial_director(user)
    plan = _require(db, plan_id)
    if plan.status != "on_review":
        raise PlanError("Утвердить можно только план на проверке", status_code=409)
    plan.status = "approved"
    db.commit()
    return _serialize(_require(db, plan_id))


def reject(db: Session, user: User, plan_id: uuid.UUID, reason: str) -> SalesPlanOut:
    """Коммерческий директор возвращает план на доработку."""
    _check_commercial_director(user)
    plan = _require(db, plan_id)
    if plan.status != "on_review":
        raise PlanError("Отклонить можно только план на проверке", status_code=409)
    plan.status = "filling"
    if reason:
        suffix = f"Возврат на доработку: {reason}"
        plan.notes = f"{plan.notes}\n{suffix}" if plan.notes else suffix
    db.commit()
    return _serialize(_require(db, plan_id))


def delete_plan(db: Session, user: User, plan_id: uuid.UUID) -> None:
    """Удаление черновика: коммерческий директор или владелец плана."""
    plan = _require(db, plan_id)
    is_owner = user.role == ROLE_SALES_MANAGER and plan.manager_id == user.id
    if not (is_owner or user.role == ROLE_COMMERCIAL_DIRECTOR):
        raise PlanError("Удалить план вам недоступно", status_code=403)
    if plan.status not in EDITABLE_BY_OWNER:
        raise PlanError("Удалить можно только черновик или план на заполнении", status_code=409)
    db.delete(plan)
    db.commit()
