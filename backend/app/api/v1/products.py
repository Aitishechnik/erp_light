"""Номенклатура: список, ручное заведение и правка. Читать может любой вошедший."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import User
from app.models.domain import Product
from app.schemas.domain import ProductIn, ProductOut, ProductUpdate
from app.services import directory_service as service
from app.services.directory_service import DIRECTORY_WRITE_ROLES, DirectoryError

router = APIRouter(tags=["products"])

Writer = Annotated[User, Depends(require_roles(*DIRECTORY_WRITE_ROLES))]


def _fail(exc: DirectoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/products", response_model=list[ProductOut])
def list_products(
    user: CurrentUser,
    db: DbSession,
    kind: str | None = Query(default=None, description="goods | material"),
    include_inactive: bool = Query(default=True, description="Показать и неактивные"),
) -> list[Product]:
    rows = service.list_products(db, kind=kind)
    if not include_inactive:
        rows = [row for row in rows if row.is_active]
    return rows


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductIn, user: Writer, db: DbSession) -> Product:
    try:
        return service.create_product(db, payload)
    except DirectoryError as exc:
        raise _fail(exc) from exc


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: uuid.UUID, payload: ProductUpdate, user: Writer, db: DbSession
) -> Product:
    try:
        return service.update_product(db, product_id, payload)
    except DirectoryError as exc:
        raise _fail(exc) from exc
