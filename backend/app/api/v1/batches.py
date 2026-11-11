"""Поступления партий: календарь, карточка, правка, удаление, позиции из 1С.

Создаются только выгрузкой 1С (``imports``), поэтому эндпоинта создания нет.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_roles
from app.api.v1.imports import session_out
from app.models.auth import ROLE_IMPORT_MANAGER, ROLE_PURCHASE_DIRECTOR, User
from app.models.domain import Batch, StockSnapshot
from app.models.rates import CurrencyRate
from app.schemas.domain import BatchCreate, BatchCustomsIn, BatchOut
from app.schemas.imports import BatchImportOut
from app.services import audit_service, batch_import_service
from app.services.batch_service import (
    ITEMS_LOCKED,
    batch_finance,
    delete_batch,
    expense_rates,
    latest_snapshots,
    load_batch,
    load_batches,
    lock_batch,
    rate_rows_for,
    serialize_batch,
    update_batch,
)
from app.services.currency_service import RateError
from app.services.customs_service import apply_customs, cancel_customs
from app.services.import_service import ImportDataError

router = APIRouter(tags=["batches"])

# Заполнять и править карточку поступления могут закупки; смотрят все вошедшие.
Writer = Annotated[User, Depends(require_roles(ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER))]
# Отмена растаможки — только директор по закупкам.
Director = Annotated[User, Depends(require_roles(ROLE_PURCHASE_DIRECTOR))]


def _out(
    db: DbSession,
    batch: Batch,
    *,
    snaps: dict[uuid.UUID, StockSnapshot] | None = None,
    rate_rows: dict[str, CurrencyRate] | None = None,
) -> BatchOut:
    """Поступление с себестоимостью: платежи по своим курсам + текущий курс остатка.

    Курсы и снимки остатков можно передать готовыми — календарь читает их одним
    запросом на все поступления. Сеть на пути чтения не нужна.
    """
    if snaps is None:
        snaps = latest_snapshots(db, [item.id for item in batch.items])
    rows = rate_rows if rate_rows is not None else rate_rows_for(db, [batch])
    finance, rate_row = batch_finance(db, batch, rows)
    return serialize_batch(
        batch, snaps, finance=finance, rate_row=rate_row, rates=expense_rates(batch, rows)
    )


def _require_items(payload: BatchCreate, batch: Batch | None = None) -> None:
    """Партия без позиций допустима только как черновик из выгрузки 1С."""
    if payload.items:
        return
    if batch is not None and batch.source == "1c" and not batch.items:
        return
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST, "Добавьте хотя бы одну строку: товар и количество"
    )


@router.get("/batches", response_model=list[BatchOut])
def list_batches(
    user: CurrentUser,
    db: DbSession,
    date_from: Annotated[date | None, Query(alias="from", description="Начало периода")] = None,
    date_to: Annotated[date | None, Query(alias="to", description="Конец периода")] = None,
) -> list[BatchOut]:
    """Поступления за период (для календаря) с себестоимостью по строкам.

    Курсы и снимки остатков читаются одним запросом на весь месяц: в ЦБ отсюда
    не ходим — иначе на недоступном ЦБ открытие календаря ждёт по разу на партию.
    """
    batches = load_batches(db, date_from=date_from, date_to=date_to)
    snaps = latest_snapshots(db, [item.id for batch in batches for item in batch.items])
    rate_rows = rate_rows_for(db, batches)
    return [_out(db, batch, snaps=snaps, rate_rows=rate_rows) for batch in batches]


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: uuid.UUID, user: CurrentUser, db: DbSession) -> BatchOut:
    batch = load_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    return _out(db, batch)


@router.put("/batches/{batch_id}", response_model=BatchOut)
def put_batch(batch_id: uuid.UUID, payload: BatchCreate, user: Writer, db: DbSession) -> BatchOut:
    """Правка поступления: строки и расходы заменяются целиком."""
    batch = load_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    _require_items(payload, batch)
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
    audit_service.record(
        db,
        actor=user,
        action="batch.items_changed",
        summary=f"Изменено поступление {batch.batch_number}: строк {len(payload.items)}",
        entity_id=batch.id,
        entity_label=batch.batch_number,
        payload={"items": len(payload.items)},
        year=batch.batch_date.year,
        month=batch.batch_date.month,
    )
    db.commit()
    return _out(db, batch)


@router.delete(
    "/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def remove_batch(batch_id: uuid.UUID, user: Writer, db: DbSession) -> Response:
    batch = load_batch(db, batch_id)
    if not delete_batch(db, batch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    if batch is not None:
        audit_service.record(
            db,
            actor=user,
            action="batch.deleted",
            summary=f"Удалено поступление {batch.batch_number}",
            entity_id=batch.id,
            entity_label=batch.batch_number,
        )
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/batches/{batch_id}/customs", response_model=BatchOut)
def post_customs(
    batch_id: uuid.UUID, payload: BatchCustomsIn, user: Writer, db: DbSession
) -> BatchOut:
    """Растаможка: пошлина и НДС строк превращаются в фикс по курсу на дату."""
    try:
        batch = apply_customs(db, batch_id, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    audit_service.record(
        db,
        actor=user,
        action="batch.customs_applied",
        summary=f"Растаможено поступление {batch.batch_number}",
        entity_id=batch.id,
        entity_label=batch.batch_number,
        payload={"customs_date": str(batch.customs_date)},
    )
    db.commit()
    return _out(db, batch)


@router.delete("/batches/{batch_id}/customs", response_model=BatchOut)
def delete_customs(batch_id: uuid.UUID, user: Director, db: DbSession) -> BatchOut:
    """Отмена растаможки: в строках снова действуют проценты пошлины и НДС."""
    try:
        batch = cancel_customs(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    return _out(db, batch)


@router.post("/batches/{batch_id}/import-items", response_model=BatchImportOut)
def import_batch_items(
    batch_id: uuid.UUID,
    user: Writer,
    db: DbSession,
    file: Annotated[UploadFile, File(description="Выгрузка «Партия» из 1С в формате .xlsx")],
) -> BatchImportOut:
    """Позиции партии файлом «Партия»: товар и количество, по строкам выгрузки.

    Поступление берётся из карточки — в файле нет ни номера, ни даты. Суммы и
    себестоимость здесь не считаются: строки создаются без инвойсной суммы.
    """
    batch = lock_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поступление не найдено")
    if batch.customs_date is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, ITEMS_LOCKED)
    if batch.payments:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "У поступления уже есть платежи: их суммы считались от прежних позиций. "
            "Удалите платежи, чтобы заменить позиции из файла.",
        )
    content = file.file.read()
    try:
        report = batch_import_service.import_items(
            db, batch, file.filename or "без имени.xlsx", content
        )
    except ImportDataError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    loaded = load_batch(db, batch_id)
    assert loaded is not None
    return BatchImportOut(batch=_out(db, loaded), report=session_out(report))
