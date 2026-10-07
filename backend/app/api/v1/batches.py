"""Партии: список с себестоимостью, карточка, ручное создание. Доступ — любому вошедшему."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.domain import Batch
from app.schemas.domain import BatchCreate, BatchOut
from app.services.batch_service import (
    create_batch,
    latest_snapshots,
    load_batch,
    load_batches,
    serialize_batch,
)

router = APIRouter(tags=["batches"])


@router.get("/batches", response_model=list[BatchOut])
def list_batches(user: CurrentUser, db: DbSession) -> list[BatchOut]:
    batches = load_batches(db)
    item_ids = [item.id for batch in batches for item in batch.items]
    snaps = latest_snapshots(db, item_ids)
    return [serialize_batch(batch, snaps) for batch in batches]


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: uuid.UUID, user: CurrentUser, db: DbSession) -> BatchOut:
    batch = load_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Партия не найдена")
    snaps = latest_snapshots(db, [item.id for item in batch.items])
    return serialize_batch(batch, snaps)


@router.post("/batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
def post_batch(payload: BatchCreate, user: CurrentUser, db: DbSession) -> BatchOut:
    exists = (
        db.execute(select(Batch).where(Batch.batch_number == payload.batch_number))
        .scalars()
        .one_or_none()
    )
    if exists is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Партия «{payload.batch_number}» уже существует",
        )
    batch = create_batch(db, payload)
    return serialize_batch(batch)
