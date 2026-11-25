"""План продаж: создание, заполнение, согласование.

Цепочка статусов: черновик → заполняется → на проверке → утверждён.
Что можно — решает матрица прав: блок «Планирование продаж» и охват
«только свои» / «все». Кто именно считается менеджером плана — правило домена.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.auth import User
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import (
    SALES_PLAN_STATUS_TITLES,
    SalesPlan,
    SalesPlanItem,
)
from app.permissions import can, manages_all, scope_for
from app.schemas.planning import (
    SalesPlanCreate,
    SalesPlanDraftClientOut,
    SalesPlanDraftRowIn,
    SalesPlanDraftRowOut,
    SalesPlanItemIn,
    SalesPlanItemOut,
    SalesPlanOut,
)
from app.services import audit_service
from app.services.plan_freeze import check_months_editable, editable_months
from app.services.sales_plan_approval_service import invalidate as invalidate_annual

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


def _check_view(user: User, plan: SalesPlan) -> None:
    if not can(user, "sales_plans", "view"):
        raise PlanError("Планы продаж вам не видны", status_code=403)
    if scope_for(user, "sales_plans", "view") == "own" and plan.manager_id != user.id:
        raise PlanError("Этот план вам не виден", status_code=403)


def _check_approve(user: User) -> None:
    if not can(user, "sales_plans", "approve"):
        raise PlanError("Утверждать план продаж вам недоступно", status_code=403)


def _check_clients(db: Session, client_ids: set[uuid.UUID]) -> None:
    """Клиент строки — активный контрагент с признаком «покупатель»."""
    for client_id in client_ids:
        client = db.get(Counterparty, client_id)
        if client is None:
            raise PlanError("Клиент не найден", status_code=404)
        if not client.is_active:
            raise PlanError(f"Клиент «{client.name}» отключён — строку по нему не сохранить")
        if not client.is_customer:
            raise PlanError(
                f"«{client.name}» не отмечен покупателем — в плане продаж не используется"
            )


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _draft_pairs(plan: SalesPlan) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """Позиции черновика: сохранённый состав плюс все строки плана."""
    pairs = {(item.client_id, item.product_id) for item in plan.items}
    for row in plan.draft_rows or []:
        client_id = _uuid(row.get("client_id"))
        product_id = _uuid(row.get("product_id"))
        if client_id is not None and product_id is not None:
            pairs.add((client_id, product_id))
    return pairs


def _draft_client_ids(plan: SalesPlan) -> set[uuid.UUID]:
    """Клиенты черновика, в том числе добавленные без единой позиции."""
    ids = {client_id for client_id, _product_id in _draft_pairs(plan)}
    for row in plan.draft_clients or []:
        client_id = _uuid(row.get("client_id"))
        if client_id is not None:
            ids.add(client_id)
    return ids


def _check_products(db: Session, product_ids: set[uuid.UUID]) -> None:
    if not product_ids:
        return
    found = set(db.execute(select(Product.id).where(Product.id.in_(product_ids))).scalars().all())
    if product_ids - found:
        raise PlanError("Позиция номенклатуры не найдена", status_code=404)


def _serialize(db: Session, plan: SalesPlan) -> SalesPlanOut:
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
            notes=item.notes,
        )
        for item in sorted(
            plan.items, key=lambda row: (row.client.name, row.product.name, row.month)
        )
    ]

    client_ids = _draft_client_ids(plan)
    pairs = _draft_pairs(plan)
    product_ids = {product_id for _client_id, product_id in pairs}
    clients = (
        {
            row.id: row
            for row in db.execute(select(Counterparty).where(Counterparty.id.in_(client_ids)))
            .scalars()
            .all()
        }
        if client_ids
        else {}
    )
    products = (
        {
            row.id: row
            for row in db.execute(select(Product).where(Product.id.in_(product_ids)))
            .scalars()
            .all()
        }
        if product_ids
        else {}
    )
    draft_clients = sorted(
        (
            SalesPlanDraftClientOut(client_id=client_id, client_name=client.name)
            for client_id, client in clients.items()
        ),
        key=lambda row: row.client_name,
    )
    draft_rows = sorted(
        (
            SalesPlanDraftRowOut(
                client_id=client_id,
                client_name=clients[client_id].name,
                product_id=product_id,
                product_code=products[product_id].code,
                product_name=products[product_id].name,
                unit=products[product_id].unit,
            )
            for client_id, product_id in pairs
            if client_id in clients and product_id in products
        ),
        key=lambda row: (row.client_name, row.product_name),
    )

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
        draft_clients=draft_clients,
        draft_rows=draft_rows,
    )


def list_plans(db: Session, user: User, *, year: int | None = None) -> list[SalesPlanOut]:
    """Список планов: менеджер видит свои, коммерческий, исполнительный и закупки — все."""
    statement = (
        select(SalesPlan)
        .options(selectinload(SalesPlan.items).selectinload(SalesPlanItem.product))
        .options(selectinload(SalesPlan.items).selectinload(SalesPlanItem.client))
        .order_by(SalesPlan.year.desc(), SalesPlan.created_at)
    )
    if not can(user, "sales_plans", "view"):
        raise PlanError("Планы продаж вам не видны", status_code=403)
    if scope_for(user, "sales_plans", "view") == "own":
        statement = statement.where(SalesPlan.manager_id == user.id)
    if year is not None:
        statement = statement.where(SalesPlan.year == year)
    return [_serialize(db, plan) for plan in db.execute(statement).scalars().all()]


def get_plan(db: Session, user: User, plan_id: uuid.UUID) -> SalesPlanOut:
    plan = _require(db, plan_id)
    _check_view(user, plan)
    return _serialize(db, plan)


def create_plan(db: Session, user: User, payload: SalesPlanCreate) -> SalesPlanOut:
    """«Свои» заводят план на себя, право на всех — на выбранного менеджера."""
    if not can(user, "sales_plans", "edit"):
        raise PlanError("Создавать план продаж вам недоступно", status_code=403)
    if not manages_all(user, "sales_plans", "edit"):
        manager_id = user.id
    else:
        if payload.manager_id is None:
            raise PlanError("Укажите менеджера, на которого создаётся план")
        manager_id = payload.manager_id

    manager = db.get(User, manager_id)
    if manager is None or not manager.is_active:
        raise PlanError("Сотрудник не найден или заблокирован", status_code=404)
    if not manager.is_manager:
        raise PlanError("План продаж заводится только на сотрудника, который ведёт клиентов")

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
    return _serialize(db, created)


def update_items(
    db: Session,
    user: User,
    plan_id: uuid.UUID,
    items: list[SalesPlanItemIn],
    *,
    clients: list[uuid.UUID] | None = None,
    rows: list[SalesPlanDraftRowIn] | None = None,
) -> SalesPlanOut:
    """Полная замена строк по редактируемым месяцам и состава черновика.

    Замороженные месяцы менять нельзя — запрос с ними отклоняется целиком.
    ``clients``/``rows`` присылают новые формы: клиенты и позиции сохраняются
    даже без количеств. Если их нет (старый клиент), состав не перезаписываем,
    а пустой запрос не может стереть уже заполненный черновик.
    """
    plan = _require(db, plan_id)
    _check_view(user, plan)

    if not can(user, "sales_plans", "edit"):
        raise PlanError("Правка плана вам недоступна", status_code=403)
    if scope_for(user, "sales_plans", "edit") == "own":
        if plan.manager_id != user.id:
            raise PlanError("Правка плана вам недоступна", status_code=403)
        if plan.status not in EDITABLE_BY_OWNER:
            raise PlanError("План на проверке или утверждён — правки недоступны", status_code=409)

    check_months_editable(plan.year, {item.month for item in items})

    seen: set[tuple[uuid.UUID, uuid.UUID, int]] = set()
    for item in items:
        key = (item.client_id, item.product_id, item.month)
        if key in seen:
            raise PlanError("В плане две строки на одного клиента, товар и месяц")
        seen.add(key)

    allowed = set(editable_months(plan.year))
    editable_existing = [row for row in plan.items if row.month in allowed]
    explicit_draft = clients is not None or rows is not None
    if not explicit_draft and not items and editable_existing:
        # Старый клиент без состава черновика: раньше такой запрос удалял все
        # строки. Лучше отказать, чем молча обнулить план.
        raise PlanError(
            "Пустой запрос не может обнулить заполненный план — обновите страницу и повторите",
            status_code=409,
        )

    draft_rows = [(row.client_id, row.product_id) for row in rows or []]
    if len(set(draft_rows)) != len(draft_rows):
        raise PlanError("В черновике две одинаковые позиции")
    draft_pairs = set(draft_rows)
    draft_clients = set(clients or []) | {client_id for client_id, _ in draft_pairs}
    draft_clients |= {item.client_id for item in items}
    draft_pairs |= {(item.client_id, item.product_id) for item in items}
    # Замороженные строки не редактируются, но их клиенты и позиции остаются
    # в составе черновика — иначе после сохранения они бы «пропали» из формы.
    for existing in plan.items:
        if existing.month not in allowed:
            draft_clients.add(existing.client_id)
            draft_pairs.add((existing.client_id, existing.product_id))

    _check_clients(db, draft_clients)
    _check_products(
        db, {product_id for _client_id, product_id in draft_pairs} | {i.product_id for i in items}
    )

    if explicit_draft:
        plan.draft_clients = [
            {"client_id": str(client_id)} for client_id in sorted(draft_clients, key=str)
        ]
        plan.draft_rows = [
            {"client_id": str(client_id), "product_id": str(product_id)}
            for client_id, product_id in sorted(
                draft_pairs, key=lambda pair: (str(pair[0]), str(pair[1]))
            )
        ]
    else:
        # Старый клиент: состав сохраняем, но при первом сохранении заводим его
        # из уже существующих строк, чтобы черновик был восстановим.
        if plan.draft_clients is None:
            plan.draft_clients = [
                {"client_id": str(client_id)}
                for client_id in sorted(_draft_client_ids(plan) | draft_clients, key=str)
            ]
        if plan.draft_rows is None:
            all_pairs = _draft_pairs(plan) | draft_pairs
            plan.draft_rows = [
                {"client_id": str(client_id), "product_id": str(product_id)}
                for client_id, product_id in sorted(
                    all_pairs, key=lambda pair: (str(pair[0]), str(pair[1]))
                )
            ]

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
                notes=item.notes,
            )
        )

    was_approved = plan.status == "approved"
    if was_approved:
        plan.status = "on_review"
    audit_service.record(
        db,
        actor=user,
        action="sales_plan.items_changed",
        summary=(f"План на {plan.year} год, {plan.manager.full_name}: строк {len(items)}"),
        entity_id=plan.id,
        entity_label=f"{plan.manager.full_name}, {plan.year}",
        payload={"stroki": len(items), "bylo_utverzhden": was_approved},
        year=plan.year,
    )
    db.commit()
    if was_approved:
        invalidate_annual(db, plan.year, f"изменён план менеджера {plan.manager.full_name}")
    return _serialize(db, _require(db, plan_id))


def send_to_fill(db: Session, user: User, plan_id: uuid.UUID) -> SalesPlanOut:
    """Отдать черновик менеджеру на заполнение."""
    if not can(user, "sales_plans", "dispatch"):
        raise PlanError("Отдавать план на заполнение вам недоступно", status_code=403)
    plan = _require(db, plan_id)
    if plan.status != "draft":
        raise PlanError("На заполнение отправляется только черновик", status_code=409)
    plan.status = "filling"
    db.commit()
    return _serialize(db, _require(db, plan_id))


def submit(db: Session, user: User, plan_id: uuid.UUID) -> SalesPlanOut:
    """Менеджер отправляет свой план на проверку; администратор — любой."""
    plan = _require(db, plan_id)
    if not can(user, "sales_plans", "submit"):
        raise PlanError("Отправлять план на проверку вам недоступно", status_code=403)
    if scope_for(user, "sales_plans", "submit") == "own" and plan.manager_id != user.id:
        raise PlanError("Отправить план может только его менеджер", status_code=403)
    if plan.status not in EDITABLE_BY_OWNER:
        raise PlanError("План уже на проверке или утверждён", status_code=409)
    if not plan.items:
        raise PlanError("Нельзя отправить пустой план: заполните хотя бы одну строку")
    plan.status = "on_review"
    db.commit()
    return _serialize(db, _require(db, plan_id))


def approve(db: Session, user: User, plan_id: uuid.UUID) -> SalesPlanOut:
    """Утвердить план на проверке."""
    _check_approve(user)
    plan = _require(db, plan_id)
    if plan.status != "on_review":
        raise PlanError("Утвердить можно только план на проверке", status_code=409)
    plan.status = "approved"
    audit_service.record(
        db,
        actor=user,
        action="sales_plan.approved",
        summary=f"План продаж на {plan.year} год утверждён: {plan.manager.full_name}",
        entity_id=plan.id,
        entity_label=f"{plan.manager.full_name}, {plan.year}",
        year=plan.year,
    )
    db.commit()
    invalidate_annual(db, plan.year, f"утверждён план менеджера {plan.manager.full_name}")
    return _serialize(db, _require(db, plan_id))


def reject(db: Session, user: User, plan_id: uuid.UUID, reason: str) -> SalesPlanOut:
    """Вернуть план на доработку."""
    _check_approve(user)
    plan = _require(db, plan_id)
    if plan.status != "on_review":
        raise PlanError("Отклонить можно только план на проверке", status_code=409)
    plan.status = "filling"
    if reason:
        suffix = f"Возврат на доработку: {reason}"
        plan.notes = f"{plan.notes}\n{suffix}" if plan.notes else suffix
    db.commit()
    return _serialize(db, _require(db, plan_id))


def delete_plan(db: Session, user: User, plan_id: uuid.UUID) -> None:
    """Удаление черновика: коммерческий директор, администратор или владелец."""
    plan = _require(db, plan_id)
    if not can(user, "sales_plans", "delete"):
        raise PlanError("Удалить план вам недоступно", status_code=403)
    if scope_for(user, "sales_plans", "delete") == "own" and plan.manager_id != user.id:
        raise PlanError("Удалить план вам недоступно", status_code=403)
    if plan.status not in EDITABLE_BY_OWNER:
        raise PlanError("Удалить можно только черновик или план на заполнении", status_code=409)
    audit_service.record(
        db,
        actor=user,
        action="sales_plan.deleted",
        summary=f"Удалён план продаж на {plan.year} год: {plan.manager.full_name}",
        entity_id=plan.id,
        entity_label=f"{plan.manager.full_name}, {plan.year}",
        year=plan.year,
    )
    db.delete(plan)
    db.commit()
