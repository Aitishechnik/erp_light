"""Корректировка утверждённого плана менеджера.

Утверждённый план напрямую не правится. Корректировка — полная редактируемая копия
строк плана на редактируемые месяцы: можно менять объёмы, добавлять и удалять
клиентов, товары и позиции. Черновик правит владелец плана, коммерческий директор
или исполнительный директор; отправляет его на утверждение один из них, а
утверждает коммерческий директор. Применение заменяет строки плана на редактируемых
месяцах и снимает утверждение годового плана отдела — его повторно утверждает
генеральный директор.
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
    SalesPlanApproval,
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
from app.services import audit_service
from app.services.plan_freeze import check_months_editable, editable_months
from app.services.sales_plan_approval_service import current_hash, invalidate

PlanKey = tuple[uuid.UUID, uuid.UUID, int]


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


def _check_can_propose(user: User, plan: SalesPlan) -> None:
    """Корректировку предлагает владелец, коммерческий или исполнительный директор."""
    if user.role in (ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR):
        return
    if user.role == ROLE_SALES_MANAGER and plan.manager_id == user.id:
        return
    raise CorrectionError(
        "Создать корректировку может владелец плана, коммерческий или " "исполнительный директор",
        status_code=403,
    )


def _check_commercial(user: User) -> None:
    """Утверждает и отклоняет корректировку коммерческий или исполнительный директор."""
    if user.role not in (ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR):
        raise CorrectionError(
            "Утверждает корректировку коммерческий или исполнительный директор",
            status_code=403,
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


def _plan_quantities(plan: SalesPlan) -> dict[PlanKey, SalesPlanItem]:
    return {(item.client_id, item.product_id, item.month): item for item in plan.items}


def _editable_plan_items(plan: SalesPlan) -> dict[PlanKey, SalesPlanItem]:
    allowed = set(editable_months(plan.year))
    return {key: item for key, item in _plan_quantities(plan).items() if item.month in allowed}


def _correction_keys(correction: SalesPlanCorrection) -> set[PlanKey]:
    return {(item.client_id, item.product_id, item.month) for item in correction.items}


def _is_full_copy(plan_items: dict[PlanKey, SalesPlanItem], keys: set[PlanKey]) -> bool:
    """Полная копия покрывает все строки плана на редактируемых месяцах.

    Старые корректировки (до перехода на полную копию) хранили только изменения:
    для них набор ключей — подмножество, и применяем их как точечный патч.
    """
    return set(plan_items).issubset(keys)


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


def _annual_needs_reapproval(db: Session, year: int) -> bool:
    """Нужно ли ещё раз финально согласовать годовой план после корректировки.

    Показываем подсказку только пока план отдела действительно ждёт повторного
    согласования: после повторного утверждения ГД она не должна висеть.
    """
    approval = (
        db.execute(select(SalesPlanApproval).where(SalesPlanApproval.year == year))
        .scalars()
        .one_or_none()
    )
    if approval is None or approval.status == "draft":
        return False
    if approval.status == "revision":
        return True
    if approval.status in ("on_review", "approved"):
        return approval.source_hash != current_hash(db, year)
    return False


def _serialize(db: Session, correction: SalesPlanCorrection) -> SalesPlanCorrectionOut:
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
        annual_needs_reapproval=_annual_needs_reapproval(db, plan.year),
        items=items,
    )


def create(db: Session, user: User, payload: SalesPlanCorrectionCreate) -> SalesPlanCorrectionOut:
    plan = _require_plan(db, payload.plan_id)
    _check_can_propose(user, plan)
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
    db.flush()
    # Полная копия: в черновик сразу попадают все строки редактируемых месяцев.
    for item in _editable_plan_items(plan).values():
        db.add(
            SalesPlanCorrectionItem(
                correction_id=correction.id,
                client_id=item.client_id,
                product_id=item.product_id,
                month=item.month,
                quantity=item.quantity,
                current_quantity=item.quantity,
                notes=item.notes,
            )
        )
    db.commit()
    return _serialize(db, _require_correction(db, correction.id))


def update_items(
    db: Session,
    user: User,
    correction_id: uuid.UUID,
    items: list[SalesPlanCorrectionItemIn],
) -> SalesPlanCorrectionOut:
    correction = _require_correction(db, correction_id)
    plan = correction.plan
    _check_can_propose(user, plan)
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

    plan_items = _editable_plan_items(plan)
    seen: set[PlanKey] = set()
    proposed: dict[PlanKey, SalesPlanCorrectionItemIn] = {}
    for item in items:
        key = (item.client_id, item.product_id, item.month)
        if key in seen:
            raise CorrectionError("В корректировке две строки на одного клиента, товар и месяц")
        seen.add(key)
        _check_client(db, item.client_id)
        _check_product(db, item.product_id)
        if item.quantity > 0:
            proposed[key] = item

    # Полная копия приходит, когда клиент присылает строку на каждый месяц плана,
    # включая нули для удалённых позиций. Иначе — старый точечный патч.
    full_copy = set(plan_items).issubset(seen)
    stored: list[SalesPlanCorrectionItem] = []
    if full_copy:
        for key, plan_item in plan_items.items():
            proposed_item = proposed.get(key)
            if proposed_item is None:
                stored.append(
                    SalesPlanCorrectionItem(
                        correction_id=correction.id,
                        client_id=key[0],
                        product_id=key[1],
                        month=key[2],
                        quantity=0,
                        current_quantity=plan_item.quantity,
                        notes=None,
                    )
                )
            else:
                stored.append(
                    SalesPlanCorrectionItem(
                        correction_id=correction.id,
                        client_id=key[0],
                        product_id=key[1],
                        month=key[2],
                        quantity=proposed_item.quantity,
                        current_quantity=plan_item.quantity,
                        notes=(
                            proposed_item.notes
                            if proposed_item.notes is not None
                            else plan_item.notes
                        ),
                    )
                )
        for key, item in proposed.items():
            if key in plan_items:
                continue
            stored.append(
                SalesPlanCorrectionItem(
                    correction_id=correction.id,
                    client_id=key[0],
                    product_id=key[1],
                    month=key[2],
                    quantity=item.quantity,
                    current_quantity=0,
                    notes=item.notes,
                )
            )
    else:
        for item in items:
            key = (item.client_id, item.product_id, item.month)
            if item.quantity == 0 and key not in plan_items:
                raise CorrectionError("Удалять нечего: такой строки в плане нет")
            maybe_plan_item = plan_items.get(key)
            stored.append(
                SalesPlanCorrectionItem(
                    correction_id=correction.id,
                    client_id=key[0],
                    product_id=key[1],
                    month=key[2],
                    quantity=item.quantity,
                    current_quantity=(
                        maybe_plan_item.quantity if maybe_plan_item is not None else 0
                    ),
                    notes=item.notes,
                )
            )

    for existing in list(correction.items):
        db.delete(existing)
    db.flush()
    for row in stored:
        db.add(row)
    db.commit()
    return _serialize(db, _require_correction(db, correction_id))


def submit(db: Session, user: User, correction_id: uuid.UUID) -> SalesPlanCorrectionOut:
    correction = _require_correction(db, correction_id)
    plan = correction.plan
    _check_can_propose(user, plan)
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
    plan_items = _editable_plan_items(plan)
    changed = False
    for item in correction.items:
        key = (item.client_id, item.product_id, item.month)
        if key in plan_items:
            if plan_items[key].quantity != item.quantity:
                changed = True
                break
        elif item.quantity != 0:
            changed = True
            break
    if not changed:
        raise CorrectionError("В корректировке нет изменений относительно плана")
    correction.status = "on_review"
    db.commit()
    return _serialize(db, _require_correction(db, correction_id))


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

    plan_items = _editable_plan_items(plan)
    keys = _correction_keys(correction)
    full_copy = _is_full_copy(plan_items, keys)
    if full_copy:
        # Полная копия: редактируемые месяцы заменяются целиком.
        allowed = set(editable_months(plan.year))
        for existing in list(plan.items):
            if existing.month in allowed:
                db.delete(existing)
        db.flush()
        for item in correction.items:
            if item.quantity <= 0:
                continue
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
    else:
        # Старый точечный патч: трогаем только перечисленные строки.
        for item in correction.items:
            key = (item.client_id, item.product_id, item.month)
            patch_item = plan_items.get(key)
            if item.quantity == 0:
                if patch_item is not None:
                    db.delete(patch_item)
                continue
            if patch_item is not None:
                patch_item.quantity = item.quantity
                if item.notes is not None:
                    patch_item.notes = item.notes
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
    audit_service.record(
        db,
        actor=user,
        action="correction.approved",
        summary=(
            f"Корректировка плана {plan.manager.full_name} на {plan.year} год утверждена, "
            f"строк: {len(correction.items)}"
        ),
        entity_id=plan.id,
        entity_label=f"{plan.manager.full_name}, {plan.year}",
        year=plan.year,
    )
    db.commit()

    invalidate(
        db,
        plan.year,
        f"корректировка плана менеджера {plan.manager.full_name}",
    )
    return _serialize(db, _require_correction(db, correction_id))


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
    return _serialize(db, _require_correction(db, correction_id))


def delete_correction(db: Session, user: User, correction_id: uuid.UUID) -> None:
    correction = _require_correction(db, correction_id)
    _check_can_propose(user, correction.plan)
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
    return [_serialize(db, row) for row in rows]


def get(db: Session, user: User, correction_id: uuid.UUID) -> SalesPlanCorrectionOut:
    correction = _require_correction(db, correction_id)
    _check_view(user, correction.plan)
    return _serialize(db, correction)
