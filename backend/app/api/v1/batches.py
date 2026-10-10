"""Поступления партий: календарь, карточка, создание, правка, удаление."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import ROLE_IMPORT_MANAGER, ROLE_PURCHASE_DIRECTOR, User
from app.models.domain import Batch
from app.schemas.domain import BatchCreate, BatchOut
from app.services.batch_service import (
    batch_finance,
    create_batch,
    delete_batch,
    latest_snapshots,
    load_batch,
    load_batches,
    serialize_batch,
    update_batch,
)
from app.services.currency_service import RateError

router = APIRouter(tags=["batches"])

# Заводить и править поступления могут закупки; смотрят все вошедшие.
Writer = Annotated[User, Depends(require_roles(ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER))]


def _out(db: DbSession, batch: Batch) -> BatchOut:
    """Поступление с себестоимостью: платежи по своим курсам + текущий курс остатка."""
    snaps = latest_snapshots(db, [item.id for item in batch.items])
    finance, rate_row = batch_finance(db, batch)
    return serialize_batch(batch, snaps, finance=finance, rate_row=rate_row)


@router.get("/batches", response_model=list[BatchOut])
def list_batches(
    user: CurrentUser,
    db: DbSession,
    date_from: Annotated[date | None, Query(alias="from", description="Начало периода")] = None,
    date_to: Annotated[date | None, Query(alias="to", description="Конец периода")] = None,
) -> list[BatchOut]:
    """Поступления за период (для календаря) с себестоимостью по строкам."""
    batches = load_batches(db, date_from=date_from, date_to=date_to)
    return [_out(db, batch) for batch in batches]


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: uuid.UUID, user: CurrentUser, db: DbSession) -> BatchOut:
    batch = load_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    return _out(db, batch)


@router.post("/batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
def post_batch(payload: BatchCreate, user: Writer, db: DbSession) -> BatchOut:
    """Новое поступление. Курс берём из запроса, иначе с сайта ЦБ."""
    exists = (
        db.execute(select(Batch).where(Batch.batch_number == payload.batch_number))
        .scalars()
        .one_or_none()
    )
    if exists is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Поступление «{payload.batch_number}» уже существует",
        )
    try:
        batch = create_batch(db, payload)
    except RateError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _out(db, batch)


@router.put("/batches/{batch_id}", response_model=BatchOut)
def put_batch(batch_id: uuid.UUID, payload: BatchCreate, user: Writer, db: DbSession) -> BatchOut:
    """Правка поступления: строки и расходы заменяются целиком."""
    twin = (
        db.execute(
            select(Batch).where(Batch.batch_number == payload.batch_number, Batch.id != batch_id)
        )
        .scalars()
        .one_or_none()
    )
    if twin is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Поступление «{payload.batch_number}» уже существует",
        )
    try:
        batch = update_batch(db, batch_id, payload)
    except RateError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    return _out(db, batch)


@router.delete(
    "/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def remove_batch(batch_id: uuid.UUID, user: Writer, db: DbSession) -> Response:
    if not delete_batch(db, batch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
