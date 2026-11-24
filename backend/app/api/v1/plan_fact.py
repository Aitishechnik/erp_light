"""API страницы «План и факт»: сравнение годового, месячного плана и факта."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_perm
from app.models.auth import User
from app.schemas.plan_fact import PlanFactDetailOut, PlanFactSummaryOut
from app.services import plan_fact_service as service

router = APIRouter(tags=["plan-fact"])

Viewer = Annotated[User, Depends(require_perm("plan_fact", "view"))]


@router.get("/plan-fact", response_model=PlanFactSummaryOut)
def plan_fact_summary(
    user: Viewer,
    db: DbSession,
    year: int = Query(ge=2020, le=2100),
    manager_id: Annotated[uuid.UUID | None, Query(description="Менеджер")] = None,
) -> PlanFactSummaryOut:
    """Год по месяцам: годовой план, месячный план и факт."""
    return service.summary(db, user, year, manager_id)


@router.get("/plan-fact/{year}/{month}", response_model=PlanFactDetailOut)
def plan_fact_detail(
    year: int,
    month: int,
    user: Viewer,
    db: DbSession,
    manager_id: Annotated[uuid.UUID | None, Query(description="Менеджер")] = None,
) -> PlanFactDetailOut:
    """Детализация месяца: клиенты, позиции и две причины."""
    return service.detail(db, user, year, month, manager_id)
