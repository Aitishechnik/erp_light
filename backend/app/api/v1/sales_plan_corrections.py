"""API корректировок утверждённых планов менеджеров."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.planning import (
    SalesPlanCorrectionCreate,
    SalesPlanCorrectionItemsIn,
    SalesPlanCorrectionOut,
    SalesPlanCorrectionRejectIn,
)
from app.services import sales_plan_correction_service as service
from app.services.sales_plan_correction_service import CorrectionError

router = APIRouter(tags=["sales-plan-corrections"])


def _fail(exc: CorrectionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/sales-plan-corrections", response_model=list[SalesPlanCorrectionOut])
def list_corrections(
    user: CurrentUser,
    db: DbSession,
    plan_id: Annotated[
        uuid.UUID, Query(description="План, по которому нужна история корректировок")
    ],
) -> list[SalesPlanCorrectionOut]:
    try:
        return service.list_for_plan(db, user, plan_id)
    except CorrectionError as exc:
        raise _fail(exc) from exc


@router.post(
    "/sales-plan-corrections",
    response_model=SalesPlanCorrectionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_correction(
    payload: SalesPlanCorrectionCreate, user: CurrentUser, db: DbSession
) -> SalesPlanCorrectionOut:
    """Менеджер предлагает корректировку своего утверждённого плана."""
    try:
        return service.create(db, user, payload)
    except CorrectionError as exc:
        raise _fail(exc) from exc


@router.get("/sales-plan-corrections/{correction_id}", response_model=SalesPlanCorrectionOut)
def get_correction(
    correction_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> SalesPlanCorrectionOut:
    try:
        return service.get(db, user, correction_id)
    except CorrectionError as exc:
        raise _fail(exc) from exc


@router.put("/sales-plan-corrections/{correction_id}/items", response_model=SalesPlanCorrectionOut)
def update_items(
    correction_id: uuid.UUID,
    payload: SalesPlanCorrectionItemsIn,
    user: CurrentUser,
    db: DbSession,
) -> SalesPlanCorrectionOut:
    try:
        return service.update_items(db, user, correction_id, payload.items)
    except CorrectionError as exc:
        raise _fail(exc) from exc


@router.post(
    "/sales-plan-corrections/{correction_id}/submit", response_model=SalesPlanCorrectionOut
)
def submit(correction_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SalesPlanCorrectionOut:
    try:
        return service.submit(db, user, correction_id)
    except CorrectionError as exc:
        raise _fail(exc) from exc


@router.post(
    "/sales-plan-corrections/{correction_id}/approve", response_model=SalesPlanCorrectionOut
)
def approve(correction_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SalesPlanCorrectionOut:
    try:
        return service.approve(db, user, correction_id)
    except CorrectionError as exc:
        raise _fail(exc) from exc


@router.post(
    "/sales-plan-corrections/{correction_id}/reject", response_model=SalesPlanCorrectionOut
)
def reject(
    correction_id: uuid.UUID,
    payload: SalesPlanCorrectionRejectIn,
    user: CurrentUser,
    db: DbSession,
) -> SalesPlanCorrectionOut:
    try:
        return service.reject(db, user, correction_id, payload.reason)
    except CorrectionError as exc:
        raise _fail(exc) from exc


@router.delete(
    "/sales-plan-corrections/{correction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_correction(correction_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    try:
        service.delete_correction(db, user, correction_id)
    except CorrectionError as exc:
        raise _fail(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
