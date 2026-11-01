"""API плана закупок сырья."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.planning import (
    PurchasePlanCreate,
    PurchasePlanItemsIn,
    PurchasePlanOut,
    PurchasePlanRejectIn,
)
from app.services import purchase_plan_service as service
from app.services.purchase_plan_service import PlanError

router = APIRouter(tags=["purchase-plans"])


def _fail(exc: PlanError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/purchase-plans", response_model=list[PurchasePlanOut])
def list_plans(
    user: CurrentUser,
    db: DbSession,
    year: int | None = Query(default=None, ge=2020, le=2100),
) -> list[PurchasePlanOut]:
    """Список планов закупок сырья; при `year` — только этот год."""
    try:
        return service.list_plans(db, user, year=year)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/purchase-plans", response_model=PurchasePlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(payload: PurchasePlanCreate, user: CurrentUser, db: DbSession) -> PurchasePlanOut:
    """Создать годовой план закупок сырья (один на год)."""
    try:
        return service.create_plan(db, user, payload)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.get("/purchase-plans/{plan_id}", response_model=PurchasePlanOut)
def get_plan(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PurchasePlanOut:
    try:
        return service.get_plan(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.put("/purchase-plans/{plan_id}/items", response_model=PurchasePlanOut)
def update_items(
    plan_id: uuid.UUID, payload: PurchasePlanItemsIn, user: CurrentUser, db: DbSession
) -> PurchasePlanOut:
    """Полная замена строк плана: позиция продаж, сырьё, страна и годовое количество."""
    try:
        return service.update_items(db, user, plan_id, payload.items, version=payload.version)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/purchase-plans/{plan_id}/submit", response_model=PurchasePlanOut)
def submit(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PurchasePlanOut:
    """Отправить план на утверждение исполнительному директору."""
    try:
        return service.submit(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/purchase-plans/{plan_id}/approve", response_model=PurchasePlanOut)
def approve(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PurchasePlanOut:
    """Утвердить план; доступно только исполнительному директору."""
    try:
        return service.approve(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/purchase-plans/{plan_id}/reject", response_model=PurchasePlanOut)
def reject(
    plan_id: uuid.UUID, payload: PurchasePlanRejectIn, user: CurrentUser, db: DbSession
) -> PurchasePlanOut:
    """Вернуть план на проверке на доработку с причиной."""
    try:
        return service.reject(db, user, plan_id, payload.reason)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/purchase-plans/{plan_id}/reopen", response_model=PurchasePlanOut)
def reopen(
    plan_id: uuid.UUID, payload: PurchasePlanRejectIn, user: CurrentUser, db: DbSession
) -> PurchasePlanOut:
    """Вернуть утверждённый план в работу; только исполнительный директор."""
    try:
        return service.reopen(db, user, plan_id, payload.reason)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/purchase-plans/{plan_id}/acknowledge-source", response_model=PurchasePlanOut)
def acknowledge_source(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PurchasePlanOut:
    """Принять изменения плана продаж к сведению и обновить снимок источника."""
    try:
        return service.acknowledge_source(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.post("/purchase-plans/{plan_id}/request-revision", response_model=PurchasePlanOut)
def request_revision(
    plan_id: uuid.UUID, payload: PurchasePlanRejectIn, user: CurrentUser, db: DbSession
) -> PurchasePlanOut:
    """Попросить исполнительного директора вернуть утверждённый план в работу."""
    try:
        return service.request_revision(db, user, plan_id, payload.reason)
    except PlanError as exc:
        raise _fail(exc) from exc


@router.delete(
    "/purchase-plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_plan(plan_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    try:
        service.delete_plan(db, user, plan_id)
    except PlanError as exc:
        raise _fail(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
