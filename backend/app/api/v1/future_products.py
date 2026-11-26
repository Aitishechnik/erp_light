"""API позиций будущих периодов: список, заведение, привязка к 1С."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession, require_perm
from app.models.auth import User
from app.models.domain import Product
from app.permissions import can, manages_all
from app.schemas.domain import (
    FutureProductBindIn,
    FutureProductBindOut,
    FutureProductIn,
    FutureProductOut,
    FutureProductUpdate,
    ProductOut,
)
from app.services import audit_service
from app.services import future_product_service as service
from app.services.directory_service import DirectoryError

router = APIRouter(tags=["future-products"])

Viewer = Annotated[User, Depends(require_perm("directories", "view"))]


def _future_editor(user: CurrentUser) -> User:
    """Заводить и править будущие позиции может и тот, кто ведёт планирование.

    Справочник номенклатуры может быть только на чтение (так настроен стенд),
    но коммерческому директору планирование нужно уже сегодня.
    """
    if not can(user, "directories", "edit") and not manages_all(user, "sales_plans", "edit"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Заводить будущие позиции может тот, кто ведёт планирование продаж",
        )
    return user


Editor = Annotated[User, Depends(_future_editor)]


def _fail(exc: DirectoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/future-products", response_model=list[FutureProductOut])
def list_future_products(user: Viewer, db: DbSession) -> list[FutureProductOut]:
    """Отдельный список: название, единица и где позиция уже используется."""
    return service.list_future_products(db)


@router.post("/future-products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_future_product(payload: FutureProductIn, user: Editor, db: DbSession) -> Product:
    try:
        product = service.create_future_product(db, payload)
    except DirectoryError as exc:
        raise _fail(exc) from exc
    audit_service.record(
        db,
        actor=user,
        action="future_product.created",
        summary=f"Заведена будущая позиция «{product.name}»",
        entity_id=product.id,
        entity_label=product.name,
        payload={"unit": product.unit},
    )
    db.commit()
    return product


@router.patch("/future-products/{product_id}", response_model=ProductOut)
def update_future_product(
    product_id: uuid.UUID, payload: FutureProductUpdate, user: Editor, db: DbSession
) -> Product:
    try:
        product = service.update_future_product(db, product_id, payload)
    except DirectoryError as exc:
        raise _fail(exc) from exc
    audit_service.record(
        db,
        actor=user,
        action="future_product.updated",
        summary=f"Изменена будущая позиция «{product.name}»",
        entity_id=product.id,
        entity_label=product.name,
        payload={"fields": sorted(payload.model_dump(exclude_none=True))},
    )
    db.commit()
    return product


@router.delete(
    "/future-products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_future_product(product_id: uuid.UUID, user: Editor, db: DbSession) -> Response:
    product = db.get(Product, product_id)
    name = product.name if product is not None else "позиция"
    try:
        service.delete_future_product(db, product_id)
    except DirectoryError as exc:
        raise _fail(exc) from exc
    audit_service.record(
        db,
        actor=user,
        action="future_product.deleted",
        summary=f"Удалена неиспользованная будущая позиция «{name}»",
        entity_id=product_id,
        entity_label=name,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/future-products/{product_id}/bind", response_model=FutureProductBindOut)
def bind_future_product(
    product_id: uuid.UUID, payload: FutureProductBindIn, user: Editor, db: DbSession
) -> FutureProductBindOut:
    """Привязка меняет чужие планы, поэтому доступна только охвату «все»."""
    if not manages_all(user, "sales_plans", "edit"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Привязку делает коммерческий директор, исполнительный директор или админ",
        )
    source = db.get(Product, product_id)
    source_name = source.name if source is not None else "позиция"
    try:
        result = service.bind_future_product(db, product_id, payload.product_id)
    except DirectoryError as exc:
        raise _fail(exc) from exc
    audit_service.record(
        db,
        actor=user,
        action="future_product.bound",
        summary=(
            f"Будущая позиция «{source_name}» привязана к "
            f"{result.product_code} · {result.product_name}"
        ),
        entity_id=result.product_id,
        entity_label=f"{result.product_code} · {result.product_name}",
        payload={
            "было": source_name,
            "стало": f"{result.product_code} · {result.product_name}, {result.product_unit}",
            "планов": result.plans,
            "строк_плана": result.plan_rows,
            "прочих_строк": result.other_rows,
            "годы": result.years,
        },
    )
    db.commit()
    return result
