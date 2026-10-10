"""Pydantic-схемы API. Деньги — Decimal (в JSON уходят строкой, без потери точности)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    kind: str
    unit: str
    source: str
    is_active: bool


class ProductIn(BaseModel):
    """Ручное заведение номенклатуры."""

    code: str = Field(min_length=1, max_length=64, description="Код (артикул)")
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="goods", description="goods — товар, material — материал")
    unit: str = Field(default="шт", min_length=1, max_length=16)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    is_active: bool | None = None


class BatchExpenseCreate(BaseModel):
    amount_rub: Decimal = Field(description="Сумма расхода в рублях, входит в себестоимость")
    description: str = ""


class BatchItemCreate(BaseModel):
    product_code: str = Field(min_length=1, max_length=64)
    product_name: str | None = None
    product_kind: str = "goods"
    unit: str = "шт"
    quantity: Decimal = Field(gt=0)
    total_invoice_currency: Decimal = Field(ge=0)


class BatchPaymentCreate(BaseModel):
    """Валютный платёж: закрывает инвойсную стоимость, курс фиксируется вручную."""

    payment_date: date
    amount_currency: Decimal = Field(gt=0)
    exchange_rate: Decimal = Field(gt=0, description="Курс платежа, фиксируется навсегда")
    comment: str | None = Field(default=None, max_length=255)


class BatchCreate(BaseModel):
    """Поступление партии: шапка, строки и доп. расходы."""

    batch_number: str = Field(min_length=1, max_length=100)
    batch_date: date
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    supplier_id: uuid.UUID | None = Field(default=None, description="Поставщик из справочника")
    supplier: str | None = Field(
        default=None, description="Наименование, если поставщик не из справочника"
    )
    total_invoice_value: Decimal | None = Field(default=None, ge=0)
    current_exchange_rate: Decimal | None = Field(
        default=None, gt=0, description="Если не указан, берётся курс ЦБ на дату"
    )
    auto_rate: bool = Field(default=True, description="Разрешить запрос курса с сайта ЦБ")
    comment: str | None = None
    items: list[BatchItemCreate] = Field(min_length=1)
    payments: list[BatchPaymentCreate] = Field(
        default=[], description="Валютные платежи по инвойсу"
    )
    expenses: list[BatchExpenseCreate] = Field(
        default=[], description="Рублёвые платежи (доп. расходы)"
    )


class BatchPaymentOut(BaseModel):
    id: uuid.UUID
    payment_date: date
    amount_currency: Decimal
    exchange_rate: Decimal
    amount_rub: Decimal
    comment: str | None


class BatchFinanceOut(BaseModel):
    invoice_total_currency: Decimal
    total_paid_currency: Decimal
    total_paid_rub: Decimal
    additional_expenses_rub: Decimal
    remaining_payment_currency: Decimal
    exchange_rate: Decimal = Field(description="Курс, по которому оценена незакрытая часть")
    rate_date: date | None = Field(default=None, description="Дата курса ЦБ")
    rate_updated_at: datetime | None = Field(default=None, description="Когда курс обновлялся")
    final_cost_rub: Decimal


class BatchItemOut(BaseModel):
    id: uuid.UUID
    product_code: str
    product_name: str
    product_kind: str
    unit: str
    quantity: Decimal
    total_invoice_currency: Decimal
    item_total_rub: Decimal
    unit_cost: Decimal
    quantity_on_hand: Decimal


class BatchOut(BaseModel):
    id: uuid.UUID
    batch_number: str
    batch_type: str
    batch_date: date
    currency: str
    supplier_id: uuid.UUID | None
    supplier: str | None
    source: str
    comment: str | None
    created_at: datetime
    finance: BatchFinanceOut
    payments: list[BatchPaymentOut]
    items: list[BatchItemOut]


class StockRowOut(BaseModel):
    batch_item_id: uuid.UUID
    batch_number: str
    batch_date: date
    product_code: str
    product_name: str
    product_kind: str
    unit: str
    quantity_on_hand: Decimal
    unit_cost: Decimal
    value_rub: Decimal
    snapshot_date: date | None
