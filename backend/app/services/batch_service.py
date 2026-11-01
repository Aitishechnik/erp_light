"""Сборка представлений партий и остатков + правка поступлений.

Поступления создаются только выгрузкой 1С (``receipt_import_service``); здесь —
правка карточки, ссылки на план закупок и сериализация.
"""

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
from app.models.planning import PurchasePlan, PurchasePlanItem
from app.models.rates import CurrencyRate
from app.schemas.domain import (
    BatchCreate,
    BatchExpenseOut,
    BatchFinanceOut,
    BatchItemOut,
    BatchOut,
    BatchPaymentOut,
    StockRowOut,
)
from app.services import currency_service
from app.services.cost import (
    CATEGORY_INVOICE,
    CATEGORY_RISK,
    BatchFinance,
    finance_for_batch,
    q2,
)

ZERO = Decimal("0.00")

#: Отказ при правке строк растаможенной партии (его же повторяет `customs_service`).
ITEMS_LOCKED = "Партия растаможена: строки изменить нельзя. Сначала отмените растаможку"
#: Валюта — база, от которой считались фикс-суммы таможни: после растаможки она тоже неизменна.
CURRENCY_LOCKED = "Партия растаможена: валюту изменить нельзя. Сначала отмените растаможку"


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
        .options(selectinload(Batch.items).selectinload(BatchItem.purchase_plan_item))
        .options(selectinload(Batch.expenses))
        .options(selectinload(Batch.payments))
        .order_by(Batch.batch_date, Batch.batch_number)
    )
    if date_from is not None:
        statement = statement.where(Batch.batch_date >= date_from)
    if date_to is not None:
        statement = statement.where(Batch.batch_date <= date_to)
    return list(db.execute(statement).scalars().all())


def lock_batch(db: Session, batch_id: uuid.UUID) -> Batch | None:
    """Заблокировать партию до конца транзакции и вернуть её со строками.

    Правка заменяет строки целиком; без блокировки две одновременные правки
    могут оставить смесь двух версий. Остальные операции с партией (импорт
    позиций, растаможка, удаление) берут ту же блокировку.
    """
    locked = db.execute(
        select(Batch.id).where(Batch.id == batch_id).with_for_update()
    ).scalar_one_or_none()
    if locked is None:
        return None
    return load_batch(db, batch_id)


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
            .options(selectinload(Batch.items).selectinload(BatchItem.purchase_plan_item))
            .options(selectinload(Batch.expenses))
            .options(selectinload(Batch.payments))
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one_or_none()
    )


def expense_rates(db: Session, batch: Batch) -> dict[str, Decimal]:
    """Курсы ЦБ на текущий день для валют общих расходов партии.

    Расход в валюте пересчитывается по последнему доступному курсу ЦБ; если курса
    нет, расход оценивается в ноль — выдуманное число в себестоимость не попадает.
    """
    rates: dict[str, Decimal] = {}
    codes = {(expense.currency or "RUB").strip().upper() for expense in batch.expenses}
    for code in codes:
        if code == "RUB":
            continue
        row = currency_service.latest_rate_row(db, code)
        if row is not None:
            rates[code] = row.rate
    return rates


def expense_amount_rub(expense: BatchExpense, rates: dict[str, Decimal]) -> Decimal:
    """Рублёвая величина общего расхода: рубли как есть, валюта — по курсу ЦБ."""
    code = (expense.currency or "RUB").strip().upper()
    if code == "RUB":
        return q2(expense.amount_currency)
    return q2(expense.amount_currency * rates.get(code, ZERO))


def batch_finance(db: Session, batch: Batch) -> tuple[BatchFinance, CurrencyRate | None]:
    """Себестоимость партии: платежи по своим курсам + незакрытая часть по текущему.

    Курс для незакрытой части — последний доступный (ЦБ); он обновляется раз в час,
    поэтому оценка остатка меняется, а зафиксированные курсы платежей — нет.
    """
    rate, rate_row = currency_service.batch_rate(db, batch.currency, batch.current_exchange_rate)
    finance = finance_for_batch(batch, rate=rate, expense_rates=expense_rates(db, batch))
    return finance, rate_row if isinstance(rate_row, CurrencyRate) else None


def plan_link_label(item: BatchItem) -> str | None:
    """Подпись строки плана для карточки: «2026 · Китай»."""
    link = item.purchase_plan_item
    if link is None:
        return None
    return f"{link.plan.year} · {link.country.name}"


def serialize_batch(
    batch: Batch,
    snapshots: dict[uuid.UUID, StockSnapshot] | None = None,
    *,
    finance: BatchFinance | None = None,
    rate_row: CurrencyRate | None = None,
    rates: dict[str, Decimal] | None = None,
) -> BatchOut:
    """Партия с посчитанной себестоимостью по каждой строке."""
    snaps = snapshots if snapshots is not None else {}
    expense_rate_map = rates or {}
    if finance is None:
        finance = finance_for_batch(batch, expense_rates=expense_rate_map)

    items: list[BatchItemOut] = []
    for item, cost in zip(batch.items, finance.items, strict=True):
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
                unit_price_currency=item.unit_price_currency,
                duty_percent=item.duty_percent,
                vat_percent=item.vat_percent,
                risk_unit_currency=item.risk_unit_currency,
                duty_fixed_rub=item.duty_fixed_rub,
                vat_fixed_rub=item.vat_fixed_rub,
                purchase_plan_item_id=item.purchase_plan_item_id,
                purchase_plan_label=plan_link_label(item),
                invoice_currency=cost.invoice_currency,
                risk_currency=cost.risk_currency,
                duty_rub=cost.duty_rub,
                vat_rub=cost.vat_rub,
                risk_rub=cost.risk_rub,
                expenses_rub=cost.expenses_rub,
                item_total_rub=cost.item_total_rub,
                unit_cost=cost.unit_cost,
                quantity_on_hand=on_hand,
            )
        )

    expenses = [
        BatchExpenseOut(
            id=expense.id,
            description=expense.description,
            currency=(expense.currency or "RUB").strip().upper(),
            amount_currency=expense.amount_currency,
            amount_rub=expense_amount_rub(expense, expense_rate_map),
        )
        for expense in sorted(batch.expenses, key=lambda row: row.created_at)
    ]

    payments = [
        BatchPaymentOut(
            id=payment.id,
            payment_date=payment.payment_date,
            amount_currency=payment.amount_currency,
            exchange_rate=payment.exchange_rate,
            amount_rub=q2(payment.amount_currency * payment.exchange_rate),
            category=payment.category,
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
        customs_date=batch.customs_date,
        customs_rate=batch.customs_rate,
        finance=BatchFinanceOut(
            invoice_total_currency=finance.invoice_total_currency,
            risk_total_currency=finance.risk_total_currency,
            exchange_rate=finance.cbr_rate,
            rate_date=rate_row.rate_date if rate_row is not None else None,
            rate_updated_at=rate_row.fetched_at if rate_row is not None else None,
            invoice_paid_currency=finance.invoice.paid_currency,
            invoice_paid_rub=finance.invoice.paid_rub,
            invoice_remaining_currency=finance.invoice.remaining_currency,
            invoice_rate=finance.invoice.rate,
            risk_paid_currency=finance.risk.paid_currency,
            risk_paid_rub=finance.risk.paid_rub,
            risk_remaining_currency=finance.risk.remaining_currency,
            risk_rate=finance.risk.rate,
            planned_invoice_currency=finance.invoice.planned_currency,
            planned_invoice_rub=finance.invoice.planned_rub,
            planned_risk_currency=finance.risk.planned_currency,
            planned_risk_rub=finance.risk.planned_rub,
            expenses_rub=finance.expenses_rub,
            duty_rub=finance.duty_rub,
            vat_rub=finance.vat_rub,
            average_rate=finance.average_rate,
            final_cost_rub=finance.final_cost_rub,
        ),
        payments=payments,
        expenses=expenses,
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


def check_payments_limit(payload: BatchCreate) -> None:
    """Платежи категории не могут превышать сумму этой категории.

    Инвойс и Risk закрываются отдельно: платежи ``invoice`` ограничены инвойсной
    стоимостью товаров, платежи ``risk`` — суммой Risk по строкам.
    """
    totals = {CATEGORY_INVOICE: ZERO, CATEGORY_RISK: ZERO}
    for item in payload.items:
        totals[CATEGORY_INVOICE] += q2(item.unit_price_currency * item.quantity)
        totals[CATEGORY_RISK] += q2(item.risk_unit_currency * item.quantity)
    paid = {CATEGORY_INVOICE: ZERO, CATEGORY_RISK: ZERO}
    for payment in payload.payments:
        paid[payment.category] += payment.amount_currency
    for category, title in ((CATEGORY_INVOICE, "инвойсу"), (CATEGORY_RISK, "Risk")):
        if paid[category] > totals[category]:
            raise ValueError(
                f"Сумма валютных платежей по {title} ({paid[category]}) больше суммы партии "
                f"({totals[category]}). Уменьшите платёж или добавьте товары."
            )


def _lock_plan_item(db: Session, plan_item_id: uuid.UUID) -> PurchasePlanItem | None:
    """Заблокировать план и вернуть его строку (или None, если её уже нет).

    Правка плана сначала блокирует строку плана, потом считает привязки и удаляет
    строки. Ссылка из поступления берёт ту же блокировку: если строка удаляется,
    вторая операция ждёт и видит актуальное состояние — либо 409 «нельзя убрать»,
    либо 400 «строка не найдена», но не молчаливую потерю ссылки.
    """
    plan_id = db.execute(
        select(PurchasePlanItem.plan_id).where(PurchasePlanItem.id == plan_item_id)
    ).scalar_one_or_none()
    if plan_id is None:
        return None
    db.execute(select(PurchasePlan.id).where(PurchasePlan.id == plan_id).with_for_update())
    return db.get(PurchasePlanItem, plan_item_id, populate_existing=True)


def _plan_year_fits(plan_year: int, day: date) -> bool:
    """Год плана и дата поступления: тот же год или пограничный месяц.

    Декабрь может закрывать январскую потребность следующего года, январь —
    декабрьскую предыдущего. Остальные месяцы — только свой год, иначе приход
    молча завысил бы декабрь чужого плана.
    """
    if day.year == plan_year:
        return True
    if day.month == 12 and plan_year == day.year + 1:
        return True
    return day.month == 1 and plan_year == day.year - 1


def _resolve_plan_item(
    db: Session,
    product_id: uuid.UUID,
    plan_item_id: uuid.UUID | None,
    day: date,
) -> uuid.UUID | None:
    """Проверить ссылку на строку плана: то же сырьё и подходящий год."""
    if plan_item_id is None:
        return None
    link = _lock_plan_item(db, plan_item_id)
    if link is None:
        raise ValueError("Строка плана закупок не найдена — обновите карточку")
    if link.product_id != product_id:
        raise ValueError("Строка плана закупок — про другое сырьё")
    if not _plan_year_fits(link.plan.year, day):
        raise ValueError("Строка плана закупок — другого года: выберите план этого года")
    return link.id


def _items_expenses_payments(
    db: Session, batch: Batch, payload: BatchCreate, *, with_items: bool = True
) -> None:
    """Наполнить партию строками, общими расходами и валютными платежами."""
    for item in payload.items if with_items else []:
        product = _resolve_product(
            db, item.product_code, item.product_name, item.product_kind, item.unit
        )
        plan_item_id = _resolve_plan_item(
            db, product.id, item.purchase_plan_item_id, batch.batch_date
        )
        db.add(
            BatchItem(
                batch_id=batch.id,
                product_id=product.id,
                quantity=item.quantity,
                unit_price_currency=item.unit_price_currency,
                duty_percent=item.duty_percent,
                vat_percent=item.vat_percent,
                risk_unit_currency=item.risk_unit_currency,
                purchase_plan_item_id=plan_item_id,
            )
        )
    for expense in payload.expenses:
        db.add(
            BatchExpense(
                batch_id=batch.id,
                amount_currency=expense.amount_currency,
                currency=expense.currency,
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
                category=payment.category,
                comment=payment.comment,
            )
        )


def _update_plan_links(db: Session, batch: Batch, payload: BatchCreate) -> None:
    """Сменить только ссылки на план у растаможенной партии — строки не трогаем.

    Ссылка не входит в себестоимость, поэтому её можно менять и после растаможки.
    Строку поступления находим по ``id``: сопоставление по товару здесь ненадёжно.
    """
    stored = {row.id: row for row in batch.items}
    for row in payload.items:
        if row.id is None:
            continue
        item = stored.get(row.id)
        if item is None:
            raise ValueError("Строка поступления не найдена — откройте карточку заново")
        if row.purchase_plan_item_id is None:
            item.purchase_plan_item_id = None
            continue
        link = _lock_plan_item(db, row.purchase_plan_item_id)
        if link is None:
            raise ValueError("Строка плана закупок не найдена — обновите карточку")
        if link.product_id != item.product_id:
            raise ValueError("Строка плана закупок — про другое сырьё")
        if not _plan_year_fits(link.plan.year, batch.batch_date):
            raise ValueError("Строка плана закупок — другого года: выберите план этого года")
        item.purchase_plan_item_id = link.id


def _resolve_batch_rate(db: Session, payload: BatchCreate) -> Decimal | None:
    """Курс для незакрытого остатка. У черновика без позиций и платежей его не считаем.

    Дата поступления на курс не влияет: остаток оценивается по актуальному курсу ЦБ.
    Курс на прошлую дату задаётся только растаможкой.
    """
    if not payload.items and not payload.payments:
        return payload.current_exchange_rate
    return currency_service.resolve_rate(
        db,
        currency=payload.currency,
        provided=payload.current_exchange_rate,
        allow_fetch=payload.auto_rate,
    )


def _same_items(batch: Batch, payload: BatchCreate) -> bool:
    """Совпадают ли строки запроса с сохранёнными (для растаможенной партии)."""
    if len(batch.items) != len(payload.items):
        return False
    stored = {item.product.code: item for item in batch.items}
    for row in payload.items:
        item = stored.get(row.product_code)
        if item is None:
            return False
        saved = (
            item.quantity,
            item.unit_price_currency,
            item.duty_percent,
            item.vat_percent,
            item.risk_unit_currency,
        )
        new = (
            row.quantity,
            row.unit_price_currency,
            row.duty_percent,
            row.vat_percent,
            row.risk_unit_currency,
        )
        if saved != new:
            return False
    return True


def update_batch(db: Session, batch_id: uuid.UUID, payload: BatchCreate) -> Batch | None:
    """Правка поступления: строки и расходы заменяются целиком.

    У растаможенной партии строки неизменны: снятая фиксация пошлины и НДС
    перестала бы соответствовать товару, поэтому правка — только через
    отмену растаможки.
    """
    batch = lock_batch(db, batch_id)
    if batch is None:
        return None
    cleared = batch.customs_date is not None
    if cleared and not _same_items(batch, payload):
        raise ValueError(ITEMS_LOCKED)
    if cleared and payload.currency.strip().upper() != batch.currency.strip().upper():
        # Фикс таможни посчитан в валюте партии: смена валюты обесценила бы эти суммы.
        raise ValueError(CURRENCY_LOCKED)
    check_payments_limit(payload)
    supplier_id, supplier_name = _resolve_supplier(db, payload)
    rate = _resolve_batch_rate(db, payload)
    batch.batch_number = payload.batch_number
    batch.batch_date = payload.batch_date
    batch.currency = payload.currency
    batch.supplier_id = supplier_id
    batch.supplier = supplier_name
    batch.current_exchange_rate = rate
    batch.comment = payload.comment

    if not cleared:
        for item in list(batch.items):
            db.delete(item)
    for expense in list(batch.expenses):
        db.delete(expense)
    for payment in list(batch.payments):
        db.delete(payment)
    db.flush()
    _items_expenses_payments(db, batch, payload, with_items=not cleared)
    if cleared:
        # Строки растаможенной партии не пересоздаются: ссылки на план меняем по id.
        _update_plan_links(db, batch, payload)
    db.commit()
    return load_batch(db, batch_id)


def delete_batch(db: Session, batch_id: uuid.UUID) -> bool:
    """Удалить поступление вместе со строками и расходами."""
    batch = lock_batch(db, batch_id)
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
        if finance.invoice_total_currency == 0 and finance.risk_total_currency == 0:
            continue
        for item, cost in zip(batch.items, finance.items, strict=True):
            snapshot = snaps.get(item.id)
            on_hand = snapshot.quantity if snapshot is not None else item.quantity
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
                    unit_cost=cost.unit_cost,
                    value_rub=q2(on_hand * cost.unit_cost),
                    snapshot_date=snapshot.snapshot_date if snapshot is not None else None,
                )
            )
    return rows
