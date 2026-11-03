"""Годовой план отдела продаж: финальное утверждение генеральным директором.

Документ собирается из утверждённых планов всех активных менеджеров. Коммерческий
директор отправляет его на утверждение, генеральный директор утверждает или
возвращает. Любое изменение плана менеджера снимает утверждение (`revision`).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_SALES_MANAGER,
    User,
    is_admin,
)
from app.models.planning import (
    SALES_PLAN_APPROVAL_STATUS_TITLES,
    SALES_PLAN_STATUS_TITLES,
    SalesPlan,
    SalesPlanApproval,
    SalesPlanItem,
)
from app.schemas.planning import (
    AnnualSalesPlanItemOut,
    AnnualSalesPlanManagerOut,
    AnnualSalesPlanOut,
)
from app.services import audit_service

VIEWERS = (
    ROLE_SALES_MANAGER,
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
)


class AnnualPlanError(Exception):
    """Нарушение бизнес-правила годового плана; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _append_note(current: str | None, note: str) -> str:
    return f"{current}\n{note}" if current else note


def _active_managers(db: Session) -> list[User]:
    return list(
        db.execute(
            select(User)
            .where(User.role == ROLE_SALES_MANAGER, User.is_active.is_(True))
            .order_by(User.full_name)
        )
        .scalars()
        .all()
    )


def _plans(db: Session, year: int) -> dict[object, SalesPlan]:
    rows = (
        db.execute(
            select(SalesPlan)
            .where(SalesPlan.year == year)
            .options(selectinload(SalesPlan.items).selectinload(SalesPlanItem.product))
            .options(selectinload(SalesPlan.items).selectinload(SalesPlanItem.client))
            .order_by(SalesPlan.created_at)
        )
        .scalars()
        .all()
    )
    return {plan.manager_id: plan for plan in rows}


def current_hash(db: Session, year: int) -> str:
    """Отпечаток утверждённых планов: менеджер, клиент, товар, месяц, количество."""
    rows = db.execute(
        select(SalesPlanItem, SalesPlan.manager_id)
        .join(SalesPlan, SalesPlan.id == SalesPlanItem.plan_id)
        .where(SalesPlan.year == year, SalesPlan.status == "approved")
    ).all()
    parts = sorted(
        f"{manager_id}|{item.client_id}|{item.product_id}|{item.month}|{item.quantity}"
        for item, manager_id in rows
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _manager_rows(
    managers: list[User], plans: dict[object, SalesPlan]
) -> list[AnnualSalesPlanManagerOut]:
    result: list[AnnualSalesPlanManagerOut] = []
    for manager in managers:
        plan = plans.get(manager.id)
        items = plan.items if plan is not None else []
        result.append(
            AnnualSalesPlanManagerOut(
                manager_id=manager.id,
                manager_name=manager.full_name,
                plan_id=plan.id if plan is not None else None,
                plan_status=plan.status if plan is not None else None,
                plan_status_title=(
                    SALES_PLAN_STATUS_TITLES.get(plan.status, plan.status)
                    if plan is not None
                    else "Плана нет"
                ),
                approved=plan is not None and plan.status == "approved",
                positions=len(items),
                clients=len({item.client_id for item in items}),
            )
        )
    return result


def _annual_items(plans: dict[object, SalesPlan]) -> list[AnnualSalesPlanItemOut]:
    rows: list[AnnualSalesPlanItemOut] = []
    for plan in plans.values():
        if plan.status != "approved":
            continue
        for item in plan.items:
            if item.quantity <= 0:
                continue
            rows.append(
                AnnualSalesPlanItemOut(
                    manager_id=plan.manager_id,
                    manager_name=plan.manager.full_name,
                    client_id=item.client_id,
                    client_name=item.client.name,
                    product_id=item.product_id,
                    product_code=item.product.code,
                    product_name=item.product.name,
                    unit=item.product.unit,
                    month=item.month,
                    quantity=item.quantity,
                )
            )
    rows.sort(
        key=lambda row: (
            row.manager_name,
            row.client_name,
            row.product_name,
            row.month,
        )
    )
    return rows


def get_annual(db: Session, user: User, year: int) -> AnnualSalesPlanOut:
    if user.role not in VIEWERS:
        raise AnnualPlanError("Годовой план отдела вам не виден", status_code=403)

    managers = _active_managers(db)
    plans = _plans(db, year)
    summaries = _manager_rows(managers, plans)
    all_approved = bool(summaries) and all(row.approved for row in summaries)
    missing = [row.manager_name for row in summaries if not row.approved]

    approval = (
        db.execute(select(SalesPlanApproval).where(SalesPlanApproval.year == year))
        .scalars()
        .one_or_none()
    )
    is_stale = (
        not all_approved
        and approval is not None
        and approval.status
        in (
            "on_review",
            "approved",
        )
    )
    if approval is None:
        status = "draft"
        status_title = SALES_PLAN_APPROVAL_STATUS_TITLES["draft"]
        submitted_by_name = None
        submitted_at = None
        approved_by_name = None
        approved_at = None
        notes = None
    else:
        status = approval.status
        status_title = SALES_PLAN_APPROVAL_STATUS_TITLES.get(status, status)
        submitted_by_name = approval.submitted_by.full_name if approval.submitted_by else None
        submitted_at = approval.submitted_at
        approved_by_name = approval.approved_by.full_name if approval.approved_by else None
        approved_at = approval.approved_at
        notes = approval.notes
        if approval.source_hash and approval.source_hash != current_hash(db, year):
            is_stale = True
        if is_stale and status in ("on_review", "approved"):
            status_title = SALES_PLAN_APPROVAL_STATUS_TITLES["revision"]

    return AnnualSalesPlanOut(
        year=year,
        status=status,
        status_title=status_title,
        submitted_by_name=submitted_by_name,
        submitted_at=submitted_at,
        approved_by_name=approved_by_name,
        approved_at=approved_at,
        notes=notes,
        is_stale=is_stale,
        all_approved=all_approved,
        missing_managers=missing,
        managers=summaries,
        items=_annual_items(plans),
    )


def _require(db: Session, year: int) -> SalesPlanApproval:
    approval = (
        db.execute(select(SalesPlanApproval).where(SalesPlanApproval.year == year))
        .scalars()
        .one_or_none()
    )
    if approval is None:
        raise AnnualPlanError("Годовой план ещё не отправлен", status_code=404)
    return approval


def submit(db: Session, user: User, year: int) -> AnnualSalesPlanOut:
    if user.role != ROLE_COMMERCIAL_DIRECTOR and not is_admin(user):
        raise AnnualPlanError(
            "Отправляет годовой план только коммерческий директор", status_code=403
        )

    managers = _active_managers(db)
    plans = _plans(db, year)
    summaries = _manager_rows(managers, plans)
    missing = [row.manager_name for row in summaries if not row.approved]
    if not summaries:
        raise AnnualPlanError("Нет активных менеджеров по продажам", status_code=409)
    if missing:
        raise AnnualPlanError(
            "Не у всех менеджеров есть утверждённый план: " + ", ".join(missing),
            status_code=409,
        )

    approval = (
        db.execute(select(SalesPlanApproval).where(SalesPlanApproval.year == year))
        .scalars()
        .one_or_none()
    )
    if approval is not None and approval.status in ("on_review", "approved"):
        raise AnnualPlanError("Годовой план уже отправлен или согласован", status_code=409)

    source_hash = current_hash(db, year)
    if approval is None:
        approval = SalesPlanApproval(year=year)
        db.add(approval)
    approval.status = "on_review"
    approval.submitted_by_id = user.id
    approval.submitted_by = user
    approval.submitted_at = datetime.now(UTC)
    approval.approved_by_id = None
    approval.approved_by = None
    approval.approved_at = None
    approval.source_hash = source_hash
    db.commit()
    return get_annual(db, user, year)


def approve(db: Session, user: User, year: int) -> AnnualSalesPlanOut:
    if user.role != ROLE_EXECUTIVE_DIRECTOR:
        raise AnnualPlanError(
            "Финально согласует годовой план только генеральный директор", status_code=403
        )
    approval = _require(db, year)
    if approval.status != "on_review":
        raise AnnualPlanError(
            "Согласовать можно только план на финальном согласовании", status_code=409
        )
    managers = _active_managers(db)
    plans = _plans(db, year)
    summaries = _manager_rows(managers, plans)
    missing = [row.manager_name for row in summaries if not row.approved]
    if missing:
        raise AnnualPlanError(
            "Не у всех менеджеров есть утверждённый план: " + ", ".join(missing),
            status_code=409,
        )
    source_hash = current_hash(db, year)
    if approval.source_hash != source_hash:
        raise AnnualPlanError(
            "Состав утверждённых планов изменился — отправьте годовой план заново",
            status_code=409,
        )
    approval.status = "approved"
    approval.approved_by_id = user.id
    approval.approved_by = user
    approval.approved_at = datetime.now(UTC)
    approval.source_hash = source_hash
    audit_service.record(
        db,
        actor=user,
        action="annual_plan.approved",
        summary=f"Годовой план отдела продаж на {year} год согласован",
        entity_id=approval.id,
        entity_label=f"Годовой план, {year}",
        year=year,
    )
    db.commit()
    return get_annual(db, user, year)


def reject(db: Session, user: User, year: int, reason: str) -> AnnualSalesPlanOut:
    if user.role != ROLE_EXECUTIVE_DIRECTOR:
        raise AnnualPlanError(
            "Возвращает годовой план только генеральный директор", status_code=403
        )
    approval = _require(db, year)
    if approval.status != "on_review":
        raise AnnualPlanError(
            "Вернуть можно только план на финальном согласовании", status_code=409
        )
    approval.status = "revision"
    approval.approved_by_id = None
    approval.approved_by = None
    approval.approved_at = None
    if reason:
        approval.notes = _append_note(approval.notes, f"Возврат на доработку: {reason}")
    db.commit()
    return get_annual(db, user, year)


def reopen(db: Session, user: User, year: int, reason: str) -> AnnualSalesPlanOut:
    """Вернуть утверждённый годовой план в работу."""
    if user.role != ROLE_EXECUTIVE_DIRECTOR:
        raise AnnualPlanError(
            "Возвращает годовой план только генеральный директор", status_code=403
        )
    approval = _require(db, year)
    if approval.status != "approved":
        raise AnnualPlanError(
            "Вернуть в работу можно только финально согласованный план", status_code=409
        )
    approval.status = "revision"
    approval.approved_by_id = None
    approval.approved_by = None
    approval.approved_at = None
    if reason:
        approval.notes = _append_note(approval.notes, f"Возврат в работу: {reason}")
    db.commit()
    return get_annual(db, user, year)


def invalidate(db: Session, year: int, reason: str) -> None:
    """Снять утверждение после изменения любого плана менеджера.

    Вызывается после фиксации изменений плана; если годовой план не отправлен или
    уже в `revision`, ничего не делает.
    """
    approval = (
        db.execute(select(SalesPlanApproval).where(SalesPlanApproval.year == year))
        .scalars()
        .one_or_none()
    )
    if approval is None or approval.status not in ("on_review", "approved"):
        return
    approval.status = "revision"
    approval.approved_by_id = None
    approval.approved_by = None
    approval.approved_at = None
    approval.notes = _append_note(
        approval.notes,
        f"Состав планов изменился: {reason}. Требуется повторное согласование.",
    )
    audit_service.record(
        db,
        actor=None,
        action="annual_plan.invalidated",
        summary=f"Согласование годового плана на {year} год снято: {reason}",
        entity_id=approval.id,
        entity_label=f"Годовой план, {year}",
        year=year,
    )
    db.commit()
