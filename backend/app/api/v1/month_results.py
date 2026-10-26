"""Итоги месяца: план продаж против факта и ручное сопоставление номенклатуры."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_SALES_MANAGER,
    User,
)
from app.models.sales import DECISION_TITLES, REASON_TITLES, MonthResult
from app.schemas.sales_results import (
    DecisionIn,
    DecisionOut,
    MatchIn,
    MatchOut,
    MonthResultOut,
    MonthRowOut,
    MonthUnmatchedOut,
    ReasonIn,
    ReasonOptionOut,
    ReasonOut,
    ReopenIn,
)
from app.services import month_close_service
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


def _reason_out(row: service.MonthRow) -> ReasonOut | None:
    if row.reason is None:
        return None
    return ReasonOut(
        code=row.reason.reason,
        title=REASON_TITLES.get(row.reason.reason, row.reason.reason),
        comment=row.reason.comment,
        author_name=row.reason_author,
        updated_at=row.reason.updated_at,
    )


def _decision_out(result: MonthResult | None) -> DecisionOut | None:
    if result is None or result.decision is None or result.decision_at is None:
        return None
    return DecisionOut(
        code=result.decision,
        title=DECISION_TITLES.get(result.decision, result.decision),
        comment=result.decision_comment,
        target_year=result.target_year,
        target_month=result.target_month,
        author_name=result.decision_by.full_name if result.decision_by is not None else None,
        at=result.decision_at,
    )


def _summary(db: Session, user: User, year: int, month: int) -> MonthResultOut:
    summary = service.month_summary(db, user, year, month)
    state = month_close_service.get_result(db, year, month)
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
            reason=_reason_out(row),
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
        without_reason=summary.without_reason,
        status=state.status if state is not None else "open",
        closed_by_name=(
            state.closed_by.full_name if state is not None and state.closed_by is not None else None
        ),
        closed_at=state.closed_at if state is not None else None,
        reopen_reason=state.reopen_reason if state is not None else None,
        decision=_decision_out(state),
        reason_options=[
            ReasonOptionOut(code=code, title=title) for code, title in REASON_TITLES.items()
        ],
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


@router.put("/month-results/{year}/{month}/reasons", response_model=ReasonOut)
def put_reason(
    year: int,
    month: int,
    payload: ReasonIn,
    user: CurrentUser,
    db: DbSession,
) -> ReasonOut:
    """Поставить причину отклонения: менеджер по своим строкам, коммерческий — по всем."""
    try:
        row = service.set_reason(
            db,
            user,
            year,
            month,
            payload.client_id,
            payload.product_id,
            payload.reason,
            payload.comment,
        )
    except service.ReasonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return ReasonOut(
        code=row.reason,
        title=REASON_TITLES.get(row.reason, row.reason),
        comment=row.comment,
        author_name=row.author.full_name if row.author is not None else None,
        updated_at=row.updated_at,
    )


@router.delete(
    "/month-results/{year}/{month}/reasons",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_reason(
    year: int,
    month: int,
    client_id: uuid.UUID,
    product_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    """Снять причину со строки."""
    try:
        service.clear_reason(db, user, year, month, client_id, product_id)
    except service.ReasonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/month-results/{year}/{month}/close", response_model=MonthResultOut)
def close_month(year: int, month: int, user: CurrentUser, db: DbSession) -> MonthResultOut:
    """Закрыть месяц: снимок плана, факта, причин и решения."""
    try:
        month_close_service.close_month(db, user, year, month)
    except month_close_service.MonthCloseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _summary(db, user, year, month)


@router.post("/month-results/{year}/{month}/reopen", response_model=MonthResultOut)
def reopen_month(
    year: int, month: int, payload: ReopenIn, user: CurrentUser, db: DbSession
) -> MonthResultOut:
    """Открыть закрытый месяц заново: причина обязательна, снимок остаётся в истории."""
    try:
        month_close_service.reopen_month(db, user, year, month, payload.reason)
    except month_close_service.MonthCloseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _summary(db, user, year, month)


@router.put("/month-results/{year}/{month}/decision", response_model=MonthResultOut)
def put_decision(
    year: int, month: int, payload: DecisionIn, user: CurrentUser, db: DbSession
) -> MonthResultOut:
    """Решение месяца: перенос в план продаж, перенос в план закупок или «принять»."""
    try:
        month_close_service.set_decision(
            db,
            user,
            year,
            month,
            payload.decision,
            target_year=payload.target_year,
            target_month=payload.target_month,
            comment=payload.comment,
        )
    except month_close_service.MonthCloseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _summary(db, user, year, month)
