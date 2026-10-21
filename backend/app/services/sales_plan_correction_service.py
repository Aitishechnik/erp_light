"""Корректировка утверждённого плана менеджера.

Менеджер не правит утверждённый план напрямую: он предлагает набор изменений
(«клиент × товар × месяц → новое количество»). Коммерческий директор принимает
изменения (они применяются к плану) или отклоняет с причиной. Применение снимает
утверждение годового плана отдела — его повторно утверждает генеральный директор.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_SALES_MANAGER,
    User,
)
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import (
    SALES_PLAN_CORRECTION_STATUS_TITLES,
    SalesPlan,
    SalesPlanCorrection,
    SalesPlanCorrectionItem,
    SalesPlanItem,
)
from app.schemas.planning import (
    SalesPlanCorrectionCreate,
    SalesPlanCorrectionItemIn,
    SalesPlanCorrectionItemOut,
    SalesPlanCorrectionOut,
)
from app.services.plan_freeze import check_months_editable
from app.services.sales_plan_approval_service import invalidate


class CorrectionError(Exception):
    """Нарушение бизнес-правила корректировки; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _load_plan(db: Session, plan_id: uuid.UUID) -> SalesPlan | None:
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


def _load_correction(db: Session, correction_id: uuid.UUID) -> SalesPlanCorrection | None:
    return (
        db.execute(
            select(SalesPlanCorrection)
            .where(SalesPlanCorrection.id == correction_id)
            .options(
                selectinload(SalesPlanCorrection.items).selectinload(
                    SalesPlanCorrectionItem.product
                )
            )
            .options(
                selectinload(SalesPlanCorrection.items).selectinload(SalesPlanCorrectionItem.client)
            )
            .options(selectinload(SalesPlanCorrection.plan))
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one_or_none()
    )


def _require_plan(db: Session, plan_id: uuid.UUID) -> SalesPlan:
    plan = _load_plan(db, plan_id)
    if plan is None:
        raise CorrectionError("План не найден", status_code=404)
    return plan


def _require_correction(db: Session, correction_id: uuid.UUID) -> SalesPlanCorrection:
    correction = _load_correction(db, correction_id)
    if correction is None:
        raise CorrectionError("Корректировка не найдена", status_code=404)
    return correction


def _check_owner(user: User, plan: SalesPlan) -> None:
    if not (user.role == ROLE_SALES_MANAGER and plan.manager_id == user.id):
        raise CorrectionError(
            "Предложить корректировку может только владелец плана", status_code=403
        )


def _check_commercial(user: User) -> None:
    if user.role != ROLE_COMMERCIAL_DIRECTOR:
        raise CorrectionError(
            "Утверждает корректировку только коммерческий директор", status_code=403
        )


def _check_view(user: User, plan: SalesPlan) -> None:
    if user.role in (ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR):
        return
    if user.role == ROLE_SALES_MANAGER and plan.manager_id == user.id:
        return
    raise CorrectionError("Корректировка вам не видна", status_code=403)


def _plan_hash(plan: SalesPlan) -> str:
    parts = sorted(
        f"{item.client_id}|{item.product_id}|{item.month}|{item.quantity}" for item in plan.items
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _plan_quantities(plan: SalesPlan) -> dict[tuple[uuid.UUID, uuid.UUID, int], SalesPlanItem]:
    return {(item.client_id, item.product_id, item.month): item for item in plan.items}


def _check_client(db: Session, client_id: uuid.UUID) -> None:
    client = db.get(Counterparty, client_id)
    if client is None:
        raise CorrectionError("Клиент не найден", status_code=404)
    if not client.is_active:
        raise CorrectionError(f"Клиент «{client.name}» отключён — строку по нему не сохранить")
    if not client.is_customer:
        raise CorrectionError(f"«{client.name}» не отмечен покупателем — в плане не используется")


def _check_product(db: Session, product_id: uuid.UUID) -> None:
    product = db.get(Product, product_id)
    if product is None:
        raise CorrectionError("Товар не найден", status_code=404)
    if not product.is_active:
        raise CorrectionError(f"«{product.name}» отключён — строку по нему не сохранить")


def _serialize(correction: SalesPlanCorrection) -> SalesPlanCorrectionOut:
    plan = correction.plan
    plan_items = _plan_quantities(plan)
    items = [
        SalesPlanCorrectionItemOut(
            id=item.id,
            client_id=item.client_id,
            client_name=item.client.name,
            product_id=item.product_id,
            product_code=item.product.code,
            product_name=item.product.name,
            unit=item.product.unit,
            month=item.month,
            quantity=item.quantity,
            current_quantity=(
                item.current_quantity
                if item.current_quantity is not None
                else (
                    plan_items[(item.client_id, item.product_id, item.month)].quantity
                    if (item.client_id, item.product_id, item.month) in plan_items
                    else 0
                )
            ),
            notes=item.notes,
        )
        for item in sorted(
            correction.items,
            key=lambda row: (row.client.name, row.product.name, row.month),
        )
    ]
    return SalesPlanCorrectionOut(
        id=correction.id,
        plan_id=correction.plan_id,
        status=correction.status,
        status_title=SALES_PLAN_CORRECTION_STATUS_TITLES.get(correction.status, correction.status),
        created_by_name=correction.created_by.full_name,
        reviewed_by_name=correction.reviewed_by.full_name if correction.reviewed_by else None,
        reviewed_at=correction.reviewed_at,
        reason=correction.reason,
        review_reason=correction.review_reason,
        created_at=correction.created_at,
        updated_at=correction.updated_at,
        items=items,
    )


def create(db: Session, user: User, payload: SalesPlanCorrectionCreate) -> SalesPlanCorrectionOut:
    plan = _require_plan(db, payload.plan_id)
    _check_owner(user, plan)
    if plan.status != "approved":
        raise CorrectionError(
            "Корректировку можно предложить только к утверждённому плану", status_code=409
        )
    open_correction = (
        db.execute(
            select(SalesPlanCorrection).where(
                SalesPlanCorrection.plan_id == plan.id,
                SalesPlanCorrection.status.in_(("draft", "on_review")),
            )
        )
        .scalars()
        .first()
    )
    if open_correction is not None:
        raise CorrectionError("По плану уже есть открытая корректировка", status_code=409)
    correction = SalesPlanCorrection(
        plan_id=plan.id,
        created_by_id=user.id,
        status="draft",
        reason=payload.reason,
        base_hash=_plan_hash(plan),
    )
    db.add(correction)
    db.commit()
    return _serialize(_require_correction(db, correction.id))


def update_items(
    db: Session,
    user: User,
    correction_id: uuid.UUID,
    items: list[SalesPlanCorrectionItemIn],
) -> SalesPlanCorrectionOut:
    correction = _require_correction(db, correction_id)
    plan = correction.plan
    _check_owner(user, plan)
    if correction.status != "draft":
        raise CorrectionError("Править можно только черновик корректировки", status_code=409)
    if plan.status != "approved":
        raise CorrectionError("План уже не утверждён — корректировка неактуальна", status_code=409)
    if correction.base_hash != _plan_hash(plan):
        raise CorrectionError(
            "План изменился с момента создания корректировки — создайте её заново",
            status_code=409,
        )

    try:
        check_months_editable(plan.year, {item.month for item in items})
    except ValueError as exc:
        raise CorrectionError(str(exc), status_code=409) from exc

    plan_items = _plan_quantities(plan)
    seen: set[tuple[uuid.UUID, uuid.UUID, int]] = set()
    for item in items:
        key = (item.client_id, item.product_id, item.month)
        if key in seen:
            raise CorrectionError("В корректировке две строки на одного клиента, товар и месяц")
        seen.add(key)
        _check_client(db, item.client_id)
        _check_product(db, item.product_id)
        if item.quantity == 0 and key not in plan_items:
            raise CorrectionError("Удалять нечего: такой строки в плане нет")

    for existing in list(correction.items):
        db.delete(existing)
    db.flush()
    for item in items:
        db.add(
            SalesPlanCorrectionItem(
                correction_id=correction.id,
                client_id=item.client_id,
                product_id=item.product_id,
                month=item.month,
                quantity=item.quantity,
                current_quantity=(
                    plan_items[(item.client_id, item.product_id, item.month)].quantity
                    if (item.client_id, item.product_id, item.month) in plan_items
                    else 0
                ),
                notes=item.notes,
            )
        )
    db.commit()
    return _serialize(_require_correction(db, correction_id))


def submit(db: Session, user: User, correction_id: uuid.UUID) -> SalesPlanCorrectionOut:
    correction = _require_correction(db, correction_id)
    plan = correction.plan
    _check_owner(user, plan)
    if correction.status != "draft":
        raise CorrectionError("Отправить можно только черновик корректировки", status_code=409)
    if plan.status != "approved":
        raise CorrectionError("План уже не утверждён — корректировка неактуальна", status_code=409)
    if correction.base_hash != _plan_hash(plan):
        raise CorrectionError(
            "План изменился с момента создания корректировки — создайте её заново",
            status_code=409,
        )
    if not correction.items:
        raise CorrectionError("Корректировка пустая: добавьте хотя бы одно изменение")
    plan_items = _plan_quantities(plan)
    changed = any(
        plan_items.get((item.client_id, item.product_id, item.month)) is None
        or plan_items[(item.client_id, item.product_id, item.month)].quantity != item.quantity
        for item in correction.items
    )
    if not changed:
        raise CorrectionError("В корректировке нет изменений относительно плана")
    correction.status = "on_review"
    db.commit()
    return _serialize(_require_correction(db, correction_id))


def approve(db: Session, user: User, correction_id: uuid.UUID) -> SalesPlanCorrectionOut:
    _check_commercial(user)
    correction = _require_correction(db, correction_id)
    plan = correction.plan
    if correction.status != "on_review":
        raise CorrectionError("Утвердить можно только корректировку на проверке", status_code=409)
    if plan.status != "approved":
        raise CorrectionError(
            "План уже не утверждён — корректировку применить нельзя", status_code=409
        )
    if correction.base_hash != _plan_hash(plan):
        raise CorrectionError(
            "План изменился с момента создания корректировки — "
            "попросите менеджера создать её заново",
            status_code=409,
        )
    try:
        check_months_editable(plan.year, {item.month for item in correction.items})
    except ValueError as exc:
        raise CorrectionError(str(exc), status_code=409) from exc

    plan_items = _plan_quantities(plan)
    for item in correction.items:
        key = (item.client_id, item.product_id, item.month)
        existing = plan_items.get(key)
        if item.quantity == 0:
            if existing is not None:
                db.delete(existing)
            continue
        if existing is not None:
            existing.quantity = item.quantity
            if item.notes is not None:
                existing.notes = item.notes
        else:
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
    plan.updated_at = datetime.now(UTC)
    correction.status = "approved"
    correction.reviewed_by_id = user.id
    correction.reviewed_at = datetime.now(UTC)
    db.commit()

    invalidate(
        db,
        plan.year,
        f"корректировка плана менеджера {plan.manager.full_name}",
    )
    return _serialize(_require_correction(db, correction_id))


def reject(
    db: Session, user: User, correction_id: uuid.UUID, reason: str
) -> SalesPlanCorrectionOut:
    _check_commercial(user)
    correction = _require_correction(db, correction_id)
    if correction.status != "on_review":
        raise CorrectionError("Отклонить можно только корректировку на проверке", status_code=409)
    correction.status = "rejected"
    correction.reviewed_by_id = user.id
    correction.reviewed_at = datetime.now(UTC)
    correction.review_reason = reason or None
    db.commit()
    return _serialize(_require_correction(db, correction_id))


def delete_correction(db: Session, user: User, correction_id: uuid.UUID) -> None:
    correction = _require_correction(db, correction_id)
    _check_owner(user, correction.plan)
    if correction.status != "draft":
        raise CorrectionError("Удалить можно только черновик корректировки", status_code=409)
    db.delete(correction)
    db.commit()


def list_for_plan(db: Session, user: User, plan_id: uuid.UUID) -> list[SalesPlanCorrectionOut]:
    plan = _require_plan(db, plan_id)
    _check_view(user, plan)
    rows = (
        db.execute(
            select(SalesPlanCorrection)
            .where(SalesPlanCorrection.plan_id == plan_id)
            .options(
                selectinload(SalesPlanCorrection.items).selectinload(
                    SalesPlanCorrectionItem.product
                )
            )
            .options(
                selectinload(SalesPlanCorrection.items).selectinload(SalesPlanCorrectionItem.client)
            )
            .options(selectinload(SalesPlanCorrection.plan))
            .order_by(SalesPlanCorrection.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_serialize(row) for row in rows]


def get(db: Session, user: User, correction_id: uuid.UUID) -> SalesPlanCorrectionOut:
    correction = _require_correction(db, correction_id)
    _check_view(user, correction.plan)
    return _serialize(correction)
