"""API годового плана продаж."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.planning import (
    SalesPlanCreate,
    SalesPlanItemsIn,
    SalesPlanOut,
    SalesPlanRejectIn,
)
from app.services import sales_plan_service as service
from app.services.sales_plan_service import PlanError

router = APIRouter(tags=["sales-plans"])


def _fail(exc: PlanError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/sales-plans", response_model=list[SalesPlanOut])
def list_plans(
    user: CurrentUser,
    db: DbSession,
    year: int | None = Query(default=None, ge=2020, le=2100),
) -> list[SalesPlanOut]:
    """Список планов: менеджер видит свои, директора — все."""
    try:
        return service.list_plans(db, user, year=year)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/sales-plans", response_model=SalesPlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(payload: SalesPlanCreate, user: CurrentUser, db: DbSession) -> SalesPlanOut:
    """Создать годовой план продаж."""
    try:
        return service.create_plan(db, user, payload)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.get("/sales-plans/{plan_id}", response_model=SalesPlanOut)
def get_plan(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SalesPlanOut:
    try:
        return service.get_plan(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.put("/sales-plans/{plan_id}/items", response_model=SalesPlanOut)
def update_items(
    plan_id: uuid.UUID, payload: SalesPlanItemsIn, user: CurrentUser, db: DbSession
) -> SalesPlanOut:
    """Полная замена строк плана по редактируемым месяцам."""
    try:
        return service.update_items(db, user, plan_id, payload.items)
    except PlanError as exc:
        raise _fail(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/sales-plans/{plan_id}/send-to-fill", response_model=SalesPlanOut)
def send_to_fill(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SalesPlanOut:
    """Коммерческий директор отдаёт план менеджеру на заполнение."""
    try:
        return service.send_to_fill(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/sales-plans/{plan_id}/submit", response_model=SalesPlanOut)
def submit(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SalesPlanOut:
    """Менеджер отправляет план на проверку."""
    try:
        return service.submit(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/sales-plans/{plan_id}/approve", response_model=SalesPlanOut)
def approve(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SalesPlanOut:
    """Коммерческий директор утверждает план."""
    try:
        return service.approve(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/sales-plans/{plan_id}/reject", response_model=SalesPlanOut)
def reject(
    plan_id: uuid.UUID, payload: SalesPlanRejectIn, user: CurrentUser, db: DbSession
) -> SalesPlanOut:
    """Коммерческий директор возвращает план на доработку."""
    try:
        return service.reject(db, user, plan_id, payload.reason)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.delete(
    "/sales-plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_plan(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    try:
        service.delete_plan(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
