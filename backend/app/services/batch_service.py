"""Сборка представлений партий и остатков + ручное создание партий."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.domain import Batch, BatchExpense, BatchItem, Product, StockSnapshot
from app.schemas.domain import (
    BatchCreate,
    BatchFinanceOut,
    BatchItemOut,
    BatchOut,
    StockRowOut,
)
from app.services.cost import (
    batch_invoice_total_currency,
    calculate_item_cost,
    finance_for_batch,
    q2,
)

ZERO = Decimal("0.00")


def latest_snapshots(db: Session, item_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, StockSnapshot]:
    """Самый свежий снимок остатка по каждой строке партии."""
    if not item_ids:
        return {}
    latest = (
        select(
            StockSnapshot.batch_item_id.label("item_id"),
            func.max(StockSnapshot.snapshot_date).label("max_date"),
        )
        .where(StockSnapshot.batch_item_id.in_(list(item_ids)))
        .group_by(StockSnapshot.batch_item_id)
        .subquery()
    )
    rows = (
        db.execute(
            select(StockSnapshot).join(
                latest,
                (StockSnapshot.batch_item_id == latest.c.item_id)
                & (StockSnapshot.snapshot_date == latest.c.max_date),
            )
        )
        .scalars()
        .all()
    )
    return {row.batch_item_id: row for row in rows}


def load_batches(db: Session) -> list[Batch]:
    return list(
        db.execute(
            select(Batch)
            .options(selectinload(Batch.items).selectinload(BatchItem.product))
            .options(selectinload(Batch.expenses))
            .order_by(Batch.batch_date.desc(), Batch.batch_number)
        )
        .scalars()
        .all()
    )


def load_batch(db: Session, batch_id: uuid.UUID) -> Batch | None:
    return (
        db.execute(
            select(Batch)
            .where(Batch.id == batch_id)
            .options(selectinload(Batch.items).selectinload(BatchItem.product))
            .options(selectinload(Batch.expenses))
        )
        .scalars()
        .one_or_none()
    )


def serialize_batch(
    batch: Batch, snapshots: dict[uuid.UUID, StockSnapshot] | None = None
) -> BatchOut:
    """Партия с посчитанной себестоимостью по каждой строке."""
    snaps = snapshots if snapshots is not None else {}
    finance = finance_for_batch(batch)

    items: list[BatchItemOut] = []
    for item in batch.items:
        item_total_rub, unit_cost = calculate_item_cost(
            finance,
            item_invoice_currency=item.total_invoice_currency,
            item_quantity=item.quantity,
        )
        snapshot = snaps.get(item.id)
        on_hand = snapshot.quantity if snapshot is not None else item.quantity
        items.append(
            BatchItemOut(
                id=item.id,
                product_code=item.product.code,
                product_name=item.product.name,
                product_kind=item.product.kind,
                unit=item.product.unit,
                quantity=item.quantity,
                total_invoice_currency=item.total_invoice_currency,
                item_total_rub=item_total_rub,
                unit_cost=unit_cost,
                quantity_on_hand=on_hand,
            )
        )

    return BatchOut(
        id=batch.id,
        batch_number=batch.batch_number,
        batch_type=batch.batch_type,
        batch_date=batch.batch_date,
        currency=batch.currency,
        supplier=batch.supplier,
        source=batch.source,
        comment=batch.comment,
        created_at=batch.created_at,
        finance=BatchFinanceOut(**{k: Decimal(v) for k, v in finance.as_dict().items()}),
        items=items,
    )


def _resolve_product(db: Session, code: str, name: str | None, kind: str, unit: str) -> Product:
    product = db.execute(select(Product).where(Product.code == code)).scalars().one_or_none()
    if product is not None:
        return product
    product = Product(code=code, name=name or code, kind=kind, unit=unit)
    db.add(product)
    db.flush()
    return product


def create_batch(db: Session, payload: BatchCreate) -> Batch:
    """Ручное создание партии (роль Закупщик)."""
    batch = Batch(
        batch_number=payload.batch_number,
        batch_type="purchase",
        batch_date=payload.batch_date,
        currency=payload.currency,
        supplier=payload.supplier,
        total_invoice_value=payload.total_invoice_value
        if payload.total_invoice_value is not None
        else sum((i.total_invoice_currency for i in payload.items), ZERO),
        current_exchange_rate=payload.current_exchange_rate,
        source="manual",
        comment=payload.comment,
    )
    db.add(batch)
    db.flush()

    for item in payload.items:
        product = _resolve_product(
            db, item.product_code, item.product_name, item.product_kind, item.unit
        )
        db.add(
            BatchItem(
                batch_id=batch.id,
                product_id=product.id,
                quantity=item.quantity,
                total_invoice_currency=item.total_invoice_currency,
            )
        )

    for expense in payload.expenses:
        db.add(
            BatchExpense(
                batch_id=batch.id,
                amount_rub=expense.amount_rub,
                description=expense.description,
                source="manual",
            )
        )

    db.commit()
    loaded = load_batch(db, batch.id)
    assert loaded is not None
    return loaded


def stock_rows(db: Session) -> list[StockRowOut]:
    """Текущие остатки по партиям с себестоимостью и стоимостью остатка."""
    batches = load_batches(db)
    item_ids = [item.id for batch in batches for item in batch.items]
    snaps = latest_snapshots(db, item_ids)

    rows: list[StockRowOut] = []
    for batch in batches:
        finance = finance_for_batch(batch)
        invoice_total = batch_invoice_total_currency(batch)
        if invoice_total == 0:
            continue
        for item in batch.items:
            snapshot = snaps.get(item.id)
            on_hand = snapshot.quantity if snapshot is not None else item.quantity
            _, unit_cost = calculate_item_cost(
                finance,
                item_invoice_currency=item.total_invoice_currency,
                item_quantity=item.quantity,
            )
            rows.append(
                StockRowOut(
                    batch_item_id=item.id,
                    batch_number=batch.batch_number,
                    batch_date=batch.batch_date,
                    product_code=item.product.code,
                    product_name=item.product.name,
                    product_kind=item.product.kind,
                    unit=item.product.unit,
                    quantity_on_hand=on_hand,
                    unit_cost=unit_cost,
                    value_rub=q2(on_hand * unit_cost),
                    snapshot_date=snapshot.snapshot_date if snapshot is not None else None,
                )
            )
    return rows
