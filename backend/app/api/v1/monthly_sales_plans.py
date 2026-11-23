"""API помесячного плана продаж: пересмотр месяца и его утверждение."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.monthly_plans import MonthlyPlanEventOut, MonthlyPlanItemsIn, MonthlyPlanOut
from app.services import monthly_sales_plan_service as service

router = APIRouter(tags=["monthly-sales-plans"])


def _fail(exc: service.MonthlyPlanError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/monthly-sales-plans", response_model=MonthlyPlanOut)
def get_monthly_plan(
    user: CurrentUser,
    db: DbSession,
    year: int = Query(ge=2020, le=2100),
    month: int = Query(ge=1, le=12),
    manager_id: Annotated[uuid.UUID | None, Query(description="Менеджер")] = None,
) -> MonthlyPlanOut:
    """План месяца: менеджер видит свой, директора — любого."""
    try:
        return service.get_plan(db, user, year, month, manager_id)
    except service.MonthlyPlanError as exc:
        raise _fail(exc) from exc


@router.put("/monthly-sales-plans/{year}/{month}", response_model=MonthlyPlanOut)
def update_monthly_plan(
    year: int,
    month: int,
    payload: MonthlyPlanItemsIn,
    user: CurrentUser,
    db: DbSession,
    manager_id: Annotated[uuid.UUID | None, Query(description="Менеджер")] = None,
) -> MonthlyPlanOut:
    """Полная замена строк месяца; причина обязательна для изменённой строки."""
    try:
        return service.update_items(db, user, year, month, payload.items, manager_id)
    except service.MonthlyPlanError as exc:
        raise _fail(exc) from exc


@router.post("/monthly-sales-plans/{year}/{month}/approve", response_model=MonthlyPlanOut)
def approve_monthly_plan(
    year: int,
    month: int,
    user: CurrentUser,
    db: DbSession,
    manager_id: Annotated[uuid.UUID | None, Query(description="Менеджер")] = None,
) -> MonthlyPlanOut:
    """Коммерческий директор утверждает месячный план."""
    try:
        return service.approve(db, user, year, month, manager_id)
    except service.MonthlyPlanError as exc:
        raise _fail(exc) from exc


@router.get(
    "/monthly-sales-plans/{year}/{month}/history",
    response_model=list[MonthlyPlanEventOut],
)
def monthly_plan_history(
    year: int,
    month: int,
    user: CurrentUser,
    db: DbSession,
    manager_id: Annotated[uuid.UUID | None, Query(description="Менеджер")] = None,
) -> list[MonthlyPlanEventOut]:
    """История пересмотра: кто, когда и почему менял строки."""
    try:
        return service.history(db, user, year, month, manager_id)
    except service.MonthlyPlanError as exc:
        raise _fail(exc) from exc
