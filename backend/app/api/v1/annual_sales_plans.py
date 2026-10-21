"""API годового плана отдела продаж (финальное утверждение ГД)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.planning import AnnualSalesPlanOut, AnnualSalesPlanRejectIn
from app.services import sales_plan_approval_service as service
from app.services.sales_plan_approval_service import AnnualPlanError

router = APIRouter(tags=["annual-sales-plans"])


def _fail(exc: AnnualPlanError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/annual-sales-plans", response_model=AnnualSalesPlanOut)
def get_annual(
    user: CurrentUser,
    db: DbSession,
    year: int = Query(ge=2020, le=2100),
) -> AnnualSalesPlanOut:
    """Сводный годовой план отдела: планы менеджеров и статус утверждения ГД."""
    try:
        return service.get_annual(db, user, year)
    except AnnualPlanError as exc:
        raise _fail(exc) from exc


@router.post("/annual-sales-plans/{year}/submit", response_model=AnnualSalesPlanOut)
def submit(year: int, user: CurrentUser, db: DbSession) -> AnnualSalesPlanOut:
    """Коммерческий директор отправляет годовой план на утверждение ГД."""
    try:
        return service.submit(db, user, year)
    except AnnualPlanError as exc:
        raise _fail(exc) from exc


@router.post("/annual-sales-plans/{year}/approve", response_model=AnnualSalesPlanOut)
def approve(year: int, user: CurrentUser, db: DbSession) -> AnnualSalesPlanOut:
    """Генеральный директор утверждает финальную версию плана отдела."""
    try:
        return service.approve(db, user, year)
    except AnnualPlanError as exc:
        raise _fail(exc) from exc


@router.post("/annual-sales-plans/{year}/reject", response_model=AnnualSalesPlanOut)
def reject(
    year: int, payload: AnnualSalesPlanRejectIn, user: CurrentUser, db: DbSession
) -> AnnualSalesPlanOut:
    """Генеральный директор возвращает план на доработку с причиной."""
    try:
        return service.reject(db, user, year, payload.reason)
    except AnnualPlanError as exc:
        raise _fail(exc) from exc


@router.post("/annual-sales-plans/{year}/reopen", response_model=AnnualSalesPlanOut)
def reopen(
    year: int, payload: AnnualSalesPlanRejectIn, user: CurrentUser, db: DbSession
) -> AnnualSalesPlanOut:
    """Генеральный директор возвращает утверждённый план в работу."""
    try:
        return service.reopen(db, user, year, payload.reason)
    except AnnualPlanError as exc:
        raise _fail(exc) from exc
