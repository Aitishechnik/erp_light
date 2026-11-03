"""Номенклатура: список, ручное заведение и правка. Читать может любой вошедший."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import User
from app.models.domain import PRODUCT_KINDS, Product
from app.schemas.domain import ProductIn, ProductOut, ProductUpdate
from app.services import audit_service
from app.services import directory_service as service
from app.services.directory_service import DIRECTORY_WRITE_ROLES, DirectoryError

router = APIRouter(tags=["products"])

Writer = Annotated[User, Depends(require_roles(*DIRECTORY_WRITE_ROLES))]


def _fail(exc: DirectoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _parse_kinds(raw: str) -> list[str]:
    """Виды из строки «raw,finished»; неизвестный вид — ошибка запроса."""
    kinds = [value.strip() for value in raw.split(",") if value.strip()]
    unknown = sorted(set(kinds) - set(PRODUCT_KINDS))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неизвестный вид номенклатуры: {', '.join(unknown)}",
        )
    return kinds


@router.get("/products", response_model=list[ProductOut])
def list_products(
    user: CurrentUser,
    db: DbSession,
    kind: str | None = Query(default=None, description="material | raw | finished"),
    kinds: str | None = Query(
        default=None,
        description="Виды через запятую: raw,finished. Приоритетнее kind",
    ),
    include_inactive: bool = Query(default=True, description="Показать и неактивные"),
) -> list[Product]:
    """Список номенклатуры целиком: фильтры и сортировка — на стороне таблицы."""
    selected = _parse_kinds(kinds) if kinds is not None else ([kind] if kind else None)
    rows = service.list_products(db, kinds=selected)
    if not include_inactive:
        rows = [row for row in rows if row.is_active]
    return rows


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Product:
    """Одна позиция: по ней таблица показывает объект из сообщения."""
    try:
        return service.get_product(db, product_id)
    except DirectoryError as exc:
        raise _fail(exc) from exc


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductIn, user: Writer, db: DbSession) -> Product:
    try:
        product = service.create_product(db, payload)
    except DirectoryError as exc:
        raise _fail(exc) from exc
    audit_service.record(
        db,
        actor=user,
        action="product.created",
        summary=f"Заведена номенклатура {product.code} · {product.name}",
        entity_id=product.id,
        entity_label=f"{product.code} · {product.name}",
        payload={"kind": product.kind},
    )
    db.commit()
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: uuid.UUID, payload: ProductUpdate, user: Writer, db: DbSession
) -> Product:
    try:
        product = service.update_product(db, product_id, payload)
    except DirectoryError as exc:
        raise _fail(exc) from exc
    audit_service.record(
        db,
        actor=user,
        action="product.updated",
        summary=f"Изменена номенклатура {product.code} · {product.name}",
        entity_id=product.id,
        entity_label=f"{product.code} · {product.name}",
        payload={"fields": sorted(payload.model_dump(exclude_none=True))},
    )
    db.commit()
    return product
