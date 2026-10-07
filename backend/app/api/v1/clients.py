"""Справочник клиентов: список, заведение, правка."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import User
from app.schemas.clients import ClientIn, ClientOut, ClientUpdate
from app.services import directory_service as service
from app.services.directory_service import DIRECTORY_WRITE_ROLES, DirectoryError

router = APIRouter(tags=["clients"])

# Менять справочник может продажи, коммерция и закупки; читать — любой вошедший.
Writer = Annotated[User, Depends(require_roles(*DIRECTORY_WRITE_ROLES))]


def _fail(exc: DirectoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/clients", response_model=list[ClientOut])
def list_clients(
    user: CurrentUser,
    db: DbSession,
    include_inactive: bool = Query(default=False, description="Показать и неактивных"),
) -> list[ClientOut]:
    """Клиенты, по которым планируются продажи."""
    return [
        ClientOut.model_validate(row)
        for row in service.list_clients(db, include_inactive=include_inactive)
    ]


@router.post("/clients", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientIn, user: Writer, db: DbSession) -> ClientOut:
    try:
        return ClientOut.model_validate(service.create_client(db, payload))
    except DirectoryError as exc:
        raise _fail(exc) from exc


@router.patch("/clients/{client_id}", response_model=ClientOut)
def update_client(
    client_id: uuid.UUID, payload: ClientUpdate, user: Writer, db: DbSession
) -> ClientOut:
    try:
        return ClientOut.model_validate(service.update_client(db, client_id, payload))
    except DirectoryError as exc:
        raise _fail(exc) from exc
