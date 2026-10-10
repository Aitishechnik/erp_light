"""Курсы валют ЦБ: получить на дату и обновить пачкой."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import ROLE_IMPORT_MANAGER, ROLE_PURCHASE_DIRECTOR, User
from app.schemas.rates import RateOut
from app.services import currency_service
from app.services.currency_service import RateError

router = APIRouter(tags=["rates"])

Refresher = Annotated[User, Depends(require_roles(ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER))]


@router.get("/rates/{code}", response_model=RateOut)
def get_rate(
    code: str,
    user: CurrentUser,
    db: DbSession,
    day: Annotated[date | None, Query(alias="date", description="Дата курса")] = None,
) -> RateOut:
    """Курс валюты: на дату или последний доступный. Берётся из кэша или с сайта ЦБ."""
    target = day or date.today()
    currency = code.strip().upper()
    if currency == currency_service.BASE_CURRENCY:
        return RateOut(code=currency, rate_date=target, rate=Decimal("1"), nominal=1, source="base")
    try:
        # Без даты — последний доступный курс (по нему оценивается незакрытая часть).
        row = (
            currency_service.get_rate_row(db, currency, target)
            if day is not None
            else currency_service.latest_rate_row(db, currency)
        )
    except RateError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Курс {currency} не найден — введите вручную или обновите курсы ЦБ",
        )
    return RateOut(
        code=row.code,
        rate_date=row.rate_date,
        rate=row.rate,
        nominal=row.nominal,
        source=row.source,
    )


@router.post("/rates/refresh", response_model=list[RateOut])
def refresh(
    user: Refresher,
    db: DbSession,
    day: Annotated[date | None, Query(alias="date", description="Дата курсов")] = None,
) -> list[RateOut]:
    """Обновить все курсы ЦБ на дату (одна выгрузка на дату, потом кэш)."""
    target = day or date.today()
    try:
        rows = currency_service.refresh_rates(db, target)
    except RateError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return [
        RateOut(
            code=row.code,
            rate_date=row.rate_date,
            rate=row.rate,
            nominal=row.nominal,
            source=row.source,
        )
        for row in rows
    ]
