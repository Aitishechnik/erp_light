"""Итоги месяца: план продаж против факта и ручное сопоставление номенклатуры."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_SALES_MANAGER,
    User,
)
from app.schemas.sales_results import (
    MatchIn,
    MatchOut,
    MonthResultOut,
    MonthRowOut,
    MonthUnmatchedOut,
)
from app.services import month_result_service as service
from app.services.import_service import ImportDataError
from app.services.sales_import_service import match_unmatched

router = APIRouter(tags=["month-results"])

VIEW_ROLES = (
    ROLE_SALES_MANAGER,
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
)

Viewer = Annotated[User, Depends(require_roles(*VIEW_ROLES))]

QUANTITY_STEP = Decimal("0.001")
MONEY_STEP = Decimal("0.01")


def _quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_STEP)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_STEP)


Matcher = Annotated[User, Depends(require_roles(ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR))]


def _summary(db: Session, user: User, year: int, month: int) -> MonthResultOut:
    summary = service.month_summary(db, user, year, month)
    rows = [
        MonthRowOut(
            client_id=row.client_id,
            client_name=row.client_name,
            manager_id=row.manager_id,
            manager_name=row.manager_name,
            product_id=row.product_id,
            product_name=row.product_name,
            unit=row.unit,
            plan_quantity=_quantity(row.plan_quantity),
            fact_quantity=_quantity(row.fact_quantity),
            fact_amount=_money(row.fact_amount),
            deviation=_quantity(row.fact_quantity - row.plan_quantity),
            group=row.group,
            manager_mismatch=row.manager_mismatch,
        )
        for row in summary.rows
    ]
    return MonthResultOut(
        year=summary.year,
        month=summary.month,
        plan_approved=summary.plan_approved,
        rows=rows,
        unmatched=[
            MonthUnmatchedOut(
                id=row.id,
                source_name=row.source_name,
                client_name=row.client.name if row.client is not None else None,
                quantity=_quantity(row.quantity),
                amount_rub=_money(row.amount_rub),
            )
            for row in summary.unmatched
        ],
        lines=len(rows),
        deviation_lines=summary.deviation_lines,
        extra_lines=summary.extra_lines,
        short_lines=summary.short_lines,
        fact_amount=_money(summary.fact_amount),
    )


@router.get("/month-results", response_model=MonthResultOut)
def month_result(
    user: CurrentUser,
    db: DbSession,
    year: int = Query(ge=2020, le=2100),
    month: int = Query(ge=1, le=12),
) -> MonthResultOut:
    """План продаж против факта за месяц. Менеджер видит только свои клиенты."""
    if user.role not in VIEW_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Итоги месяца вам недоступны"
        )
    return _summary(db, user, year, month)


@router.post("/month-results/{year}/{month}/match", response_model=MatchOut)
def match_row(
    year: int,
    month: int,
    payload: MatchIn,
    user: Matcher,
    db: DbSession,
) -> MatchOut:
    """Сопоставить неопознанную строку файла позиции справочника и запомнить алиас."""
    try:
        result = match_unmatched(db, payload.unmatched_id, payload.product_id)
    except ImportDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MatchOut(matched=result.matched, remaining=result.remaining)
