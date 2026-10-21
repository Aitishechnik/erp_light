"""Справочник стран: список, заведение и правка.

Читать может любой вошедший; менять — директор по закупкам (страны нужны
для плана закупок сырья).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import ROLE_PURCHASE_DIRECTOR, User
from app.schemas.countries import CountryIn, CountryOut, CountryUpdate
from app.services import country_service as service
from app.services.directory_service import DirectoryError

router = APIRouter(tags=["countries"])

Writer = Annotated[User, Depends(require_roles(ROLE_PURCHASE_DIRECTOR))]


def _fail(exc: DirectoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/countries", response_model=list[CountryOut])
def list_countries(
    user: CurrentUser,
    db: DbSession,
    include_inactive: bool = Query(default=False, description="Показать и отключённые"),
) -> list[CountryOut]:
    """Страны и сроки доставки."""
    rows = service.list_countries(db, include_inactive=include_inactive)
    return [CountryOut.model_validate(row) for row in rows]


@router.post("/countries", response_model=CountryOut, status_code=status.HTTP_201_CREATED)
def create_country(payload: CountryIn, user: Writer, db: DbSession) -> CountryOut:
    try:
        return CountryOut.model_validate(service.create_country(db, payload))
    except DirectoryError as exc:
        raise _fail(exc) from exc


@router.patch("/countries/{country_id}", response_model=CountryOut)
def update_country(
    country_id: uuid.UUID, payload: CountryUpdate, user: Writer, db: DbSession
) -> CountryOut:
    try:
        return CountryOut.model_validate(service.update_country(db, country_id, payload))
    except DirectoryError as exc:
        raise _fail(exc) from exc
