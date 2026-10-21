"""План закупок сырья: ручной годовой план и его согласование.

План ведёт закупщик: строки — сырьё × месяц, цена в рублях, поставщик и срок
логистики. Автоматического расчёта потребности нет, связей со строками плана
продаж тоже: утверждённый план продаж остаётся бизнес-контекстом.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from math import ceil

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.auth import (
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_IMPORT_MANAGER,
    ROLE_PURCHASE_DIRECTOR,
    User,
)
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import (
    PURCHASE_PLAN_STATUS_TITLES,
    PurchasePlan,
    PurchasePlanItem,
)
from app.schemas.planning import (
    PurchasePlanCreate,
    PurchasePlanItemIn,
    PurchasePlanItemOut,
    PurchasePlanOut,
)
from app.services.plan_freeze import check_months_editable, editable_months

EDITORS = (ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER)
VIEWERS = (ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER, ROLE_EXECUTIVE_DIRECTOR)


class PlanError(Exception):
    """Нарушение бизнес-правила плана закупок; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def order_month(month: int, delivery_days: int) -> int:
    """Месяц заказа: месяц потребности минус целые месяцы логистики, минимум 1."""
    return max(1, month - ceil(delivery_days / 30))


def _load(db: Session, plan_id: uuid.UUID) -> PurchasePlan | None:
    return (
        db.execute(
            select(PurchasePlan)
            .where(PurchasePlan.id == plan_id)
            .options(selectinload(PurchasePlan.items).selectinload(PurchasePlanItem.product))
            .options(selectinload(PurchasePlan.items).selectinload(PurchasePlanItem.supplier))
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


def _serialize(plan: PurchasePlan) -> PurchasePlanOut:
    items = [
        PurchasePlanItemOut(
            id=item.id,
            product_id=item.product_id,
            product_code=item.product.code,
            product_name=item.product.name,
            product_kind=item.product.kind,
            unit=item.product.unit,
            month=item.month,
            quantity=item.quantity,
            price_rub=item.price_rub,
            supplier_id=item.supplier_id,
            supplier_name=item.supplier.name if item.supplier else None,
            delivery_days=item.delivery_days,
            order_month=item.order_month,
            notes=item.notes,
        )
        for item in sorted(
            plan.items,
            key=lambda row: (
                row.month,
                row.product.name,
                row.supplier.name if row.supplier else "",
            ),
        )
    ]
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
        items=items,
    )


def list_plans(db: Session, user: User, *, year: int | None = None) -> list[PurchasePlanOut]:
    _check_view(user)
    statement = (
        select(PurchasePlan)
        .options(selectinload(PurchasePlan.items).selectinload(PurchasePlanItem.product))
        .options(selectinload(PurchasePlan.items).selectinload(PurchasePlanItem.supplier))
        .order_by(PurchasePlan.year.desc())
    )
    if year is not None:
        statement = statement.where(PurchasePlan.year == year)
    return [_serialize(plan) for plan in db.execute(statement).scalars().all()]


def get_plan(db: Session, user: User, plan_id: uuid.UUID) -> PurchasePlanOut:
    _check_view(user)
    return _serialize(_require(db, plan_id))


def create_plan(db: Session, user: User, payload: PurchasePlanCreate) -> PurchasePlanOut:
    _check_editor(user)
    plan = PurchasePlan(
        year=payload.year,
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
            f"План закупок сырья на {payload.year} год уже есть", status_code=409
        ) from exc
    return _serialize(_require(db, plan.id))


def update_items(
    db: Session,
    user: User,
    plan_id: uuid.UUID,
    items: list[PurchasePlanItemIn],
) -> PurchasePlanOut:
    """Полная замена строк по редактируемым месяцам; замороженные не трогаем."""
    plan = _require(db, plan_id)
    _check_editor(user)
    if plan.status != "draft":
        raise PlanError("План на проверке или утверждён — правки недоступны", status_code=409)

    try:
        check_months_editable(plan.year, {item.month for item in items})
    except ValueError as exc:
        raise PlanError(str(exc), status_code=409) from exc

    for item in items:
        if item.quantity <= 0:
            raise PlanError("Количество должно быть больше нуля")
        if item.price_rub is not None and item.price_rub < 0:
            raise PlanError("Цена не может быть отрицательной")
        _check_product(db, item.product_id)
        _check_supplier(db, item.supplier_id)

    allowed = set(editable_months(plan.year))
    for existing in list(plan.items):
        if existing.month in allowed:
            db.delete(existing)
    db.flush()

    for item in items:
        db.add(
            PurchasePlanItem(
                plan_id=plan.id,
                product_id=item.product_id,
                month=item.month,
                quantity=item.quantity,
                price_rub=item.price_rub,
                supplier_id=item.supplier_id,
                delivery_days=item.delivery_days,
                order_month=order_month(item.month, item.delivery_days),
                notes=item.notes,
            )
        )

    db.commit()
    return _serialize(_require(db, plan_id))


def submit(db: Session, user: User, plan_id: uuid.UUID) -> PurchasePlanOut:
    plan = _require(db, plan_id)
    _check_editor(user)
    if plan.status != "draft":
        raise PlanError("План уже на проверке или утверждён", status_code=409)
    if not plan.items:
        raise PlanError("Нельзя отправить пустой план: добавьте хотя бы одну строку")
    if any(item.price_rub is None for item in plan.items):
        raise PlanError("Укажите цену у всех строк: без цены план не отправить")
    plan.status = "on_review"
    db.commit()
    return _serialize(_require(db, plan_id))


def approve(db: Session, user: User, plan_id: uuid.UUID) -> PurchasePlanOut:
    _check_executive(user)
    plan = _require(db, plan_id)
    if plan.status != "on_review":
        raise PlanError("Утвердить можно только план на проверке", status_code=409)
    plan.status = "approved"
    plan.approved_by_id = user.id
    plan.approved_at = datetime.now(UTC)
    db.commit()
    return _serialize(_require(db, plan_id))


def reject(db: Session, user: User, plan_id: uuid.UUID, reason: str) -> PurchasePlanOut:
    _check_executive(user)
    plan = _require(db, plan_id)
    if plan.status != "on_review":
        raise PlanError("Вернуть на доработку можно только план на проверке", status_code=409)
    plan.status = "draft"
    plan.approved_by_id = None
    plan.approved_at = None
    if reason:
        suffix = f"Возврат на доработку: {reason}"
        plan.notes = f"{plan.notes}\n{suffix}" if plan.notes else suffix
    db.commit()
    return _serialize(_require(db, plan_id))


def reopen(db: Session, user: User, plan_id: uuid.UUID, reason: str) -> PurchasePlanOut:
    """Вернуть утверждённый план в работу: только исполнительный директор."""
    _check_executive(user)
    plan = _require(db, plan_id)
    if plan.status != "approved":
        raise PlanError("Вернуть в работу можно только утверждённый план", status_code=409)
    plan.status = "draft"
    plan.approved_by_id = None
    plan.approved_at = None
    if reason:
        suffix = f"Возврат в работу: {reason}"
        plan.notes = f"{plan.notes}\n{suffix}" if plan.notes else suffix
    db.commit()
    return _serialize(_require(db, plan_id))


def delete_plan(db: Session, user: User, plan_id: uuid.UUID) -> None:
    if user.role != ROLE_PURCHASE_DIRECTOR:
        raise PlanError("Удалить план закупок может только директор по закупкам", status_code=403)
    plan = _require(db, plan_id)
    if plan.status != "draft":
        raise PlanError("Удалить можно только черновик", status_code=409)
    db.delete(plan)
    db.commit()
