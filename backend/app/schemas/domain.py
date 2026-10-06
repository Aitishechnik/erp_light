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
    is_active: bool


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


class BatchCreate(BaseModel):
    batch_number: str = Field(min_length=1, max_length=100)
    batch_date: date
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    supplier: str | None = None
    total_invoice_value: Decimal | None = Field(default=None, ge=0)
    current_exchange_rate: Decimal | None = Field(default=None, gt=0)
    comment: str | None = None
    items: list[BatchItemCreate] = Field(min_length=1)
    expenses: list[BatchExpenseCreate] = []


class BatchFinanceOut(BaseModel):
    invoice_total_currency: Decimal
    total_paid_currency: Decimal
    total_paid_rub: Decimal
    additional_expenses_rub: Decimal
    remaining_payment_currency: Decimal
    exchange_rate: Decimal
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
    supplier: str | None
    source: str
    comment: str | None
    created_at: datetime
    finance: BatchFinanceOut
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
