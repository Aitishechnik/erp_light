"""Сборка представлений партий и остатков + поступления (создание и правка)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.counterparties import Counterparty
from app.models.domain import (
    Batch,
    BatchExpense,
    BatchItem,
    BatchPayment,
    Product,
    StockSnapshot,
)
from app.models.rates import CurrencyRate
from app.schemas.domain import (
    BatchCreate,
    BatchFinanceOut,
    BatchItemOut,
    BatchOut,
    BatchPaymentOut,
    StockRowOut,
)
from app.services import currency_service
from app.services.cost import (
    BatchFinance,
    batch_invoice_total_currency,
    calculate_item_cost,
    finance_for_batch,
    payments_totals,
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


def load_batches(
    db: Session, *, date_from: date | None = None, date_to: date | None = None
) -> list[Batch]:
    """Партии (поступления); можно ограничить периодом — для календаря."""
    statement = (
        select(Batch)
        .options(selectinload(Batch.items).selectinload(BatchItem.product))
        .options(selectinload(Batch.expenses))
        .options(selectinload(Batch.payments))
        .order_by(Batch.batch_date, Batch.batch_number)
    )
    if date_from is not None:
        statement = statement.where(Batch.batch_date >= date_from)
    if date_to is not None:
        statement = statement.where(Batch.batch_date <= date_to)
    return list(db.execute(statement).scalars().all())


def load_batch(db: Session, batch_id: uuid.UUID) -> Batch | None:
    """Партия со строками, расходами и платежами.

    ``populate_existing`` обязателен: после правки коллекции могли остаться
    прежними в identity map, а ответ должен показывать актуальные данные.
    """
    return (
        db.execute(
            select(Batch)
            .where(Batch.id == batch_id)
            .options(selectinload(Batch.items).selectinload(BatchItem.product))
            .options(selectinload(Batch.expenses))
            .options(selectinload(Batch.payments))
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one_or_none()
    )


def batch_finance(db: Session, batch: Batch) -> tuple[BatchFinance, CurrencyRate | None]:
    """Себестоимость партии: платежи по своим курсам + незакрытая часть по текущему.

    Курс для незакрытой части — последний доступный (ЦБ); он обновляется раз в час,
    поэтому оценка остатка меняется, а зафиксированные курсы платежей — нет.
    """
    rate, rate_row = currency_service.batch_rate(db, batch.currency, batch.current_exchange_rate)
    paid_currency, paid_rub = payments_totals(batch.payments)
    finance = finance_for_batch(batch, rate=rate, paid_currency=paid_currency, paid_rub=paid_rub)
    return finance, rate_row if isinstance(rate_row, CurrencyRate) else None


def serialize_batch(
    batch: Batch,
    snapshots: dict[uuid.UUID, StockSnapshot] | None = None,
    *,
    finance: BatchFinance | None = None,
    rate_row: CurrencyRate | None = None,
) -> BatchOut:
    """Партия с посчитанной себестоимостью по каждой строке."""
    snaps = snapshots if snapshots is not None else {}
    if finance is None:
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

    payments = [
        BatchPaymentOut(
            id=payment.id,
            payment_date=payment.payment_date,
            amount_currency=payment.amount_currency,
            exchange_rate=payment.exchange_rate,
            amount_rub=q2(payment.amount_currency * payment.exchange_rate),
            comment=payment.comment,
        )
        for payment in sorted(batch.payments, key=lambda row: (row.payment_date, row.created_at))
    ]

    return BatchOut(
        id=batch.id,
        batch_number=batch.batch_number,
        batch_type=batch.batch_type,
        batch_date=batch.batch_date,
        currency=batch.currency,
        supplier_id=batch.supplier_id,
        supplier=batch.supplier,
        source=batch.source,
        comment=batch.comment,
        created_at=batch.created_at,
        finance=BatchFinanceOut(
            **{k: Decimal(v) for k, v in finance.as_dict().items()},
            rate_date=rate_row.rate_date if rate_row is not None else None,
            rate_updated_at=rate_row.fetched_at if rate_row is not None else None,
        ),
        payments=payments,
        items=items,
    )


def _resolve_product(db: Session, code: str, name: str | None, kind: str, unit: str) -> Product:
    product = db.execute(select(Product).where(Product.code == code)).scalars().one_or_none()
    if product is not None:
        return product
    product = Product(code=code, name=name or code, kind=kind, unit=unit, source="manual")
    db.add(product)
    db.flush()
    return product


def _resolve_supplier(db: Session, payload: BatchCreate) -> tuple[uuid.UUID | None, str | None]:
    """Поставщик: из справочника (если выбран) или свободным текстом."""
    if payload.supplier_id is None:
        return None, payload.supplier
    supplier = db.get(Counterparty, payload.supplier_id)
    if supplier is None:
        raise ValueError("Поставщик не найден в справочнике контрагентов")
    return supplier.id, supplier.name


def _items_expenses_payments(db: Session, batch: Batch, payload: BatchCreate) -> None:
    """Наполнить партию строками, рублёвыми и валютными платежами из запроса."""
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
    for payment in payload.payments:
        db.add(
            BatchPayment(
                batch_id=batch.id,
                payment_date=payment.payment_date,
                amount_currency=payment.amount_currency,
                exchange_rate=payment.exchange_rate,
                comment=payment.comment,
            )
        )


def create_batch(db: Session, payload: BatchCreate) -> Batch:
    """Новое поступление: курс берём из запроса, иначе из ЦБ на дату."""
    supplier_id, supplier_name = _resolve_supplier(db, payload)
    rate = currency_service.resolve_rate(
        db,
        currency=payload.currency,
        day=payload.batch_date,
        provided=payload.current_exchange_rate,
        allow_fetch=payload.auto_rate,
    )
    batch = Batch(
        batch_number=payload.batch_number,
        batch_type="purchase",
        batch_date=payload.batch_date,
        currency=payload.currency,
        supplier_id=supplier_id,
        supplier=supplier_name,
        total_invoice_value=payload.total_invoice_value
        if payload.total_invoice_value is not None
        else sum((i.total_invoice_currency for i in payload.items), ZERO),
        current_exchange_rate=rate,
        source="manual",
        comment=payload.comment,
    )
    db.add(batch)
    db.flush()
    _items_expenses_payments(db, batch, payload)
    db.commit()
    loaded = load_batch(db, batch.id)
    assert loaded is not None
    return loaded


def update_batch(db: Session, batch_id: uuid.UUID, payload: BatchCreate) -> Batch | None:
    """Правка поступления: строки и расходы заменяются целиком."""
    batch = load_batch(db, batch_id)
    if batch is None:
        return None
    supplier_id, supplier_name = _resolve_supplier(db, payload)
    rate = currency_service.resolve_rate(
        db,
        currency=payload.currency,
        day=payload.batch_date,
        provided=payload.current_exchange_rate,
        allow_fetch=payload.auto_rate,
    )
    batch.batch_number = payload.batch_number
    batch.batch_date = payload.batch_date
    batch.currency = payload.currency
    batch.supplier_id = supplier_id
    batch.supplier = supplier_name
    batch.total_invoice_value = (
        payload.total_invoice_value
        if payload.total_invoice_value is not None
        else sum((i.total_invoice_currency for i in payload.items), ZERO)
    )
    batch.current_exchange_rate = rate
    batch.comment = payload.comment

    for item in list(batch.items):
        db.delete(item)
    for expense in list(batch.expenses):
        db.delete(expense)
    for payment in list(batch.payments):
        db.delete(payment)
    db.flush()
    _items_expenses_payments(db, batch, payload)
    db.commit()
    return load_batch(db, batch_id)


def delete_batch(db: Session, batch_id: uuid.UUID) -> bool:
    """Удалить поступление вместе со строками и расходами."""
    batch = load_batch(db, batch_id)
    if batch is None:
        return False
    db.delete(batch)
    db.commit()
    return True


def stock_rows(db: Session) -> list[StockRowOut]:
    """Текущие остатки по партиям с себестоимостью и стоимостью остатка."""
    batches = load_batches(db)
    item_ids = [item.id for batch in batches for item in batch.items]
    snaps = latest_snapshots(db, item_ids)

    rows: list[StockRowOut] = []
    for batch in batches:
        finance, _ = batch_finance(db, batch)
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
