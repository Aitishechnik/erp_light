"""Схемы плана продаж. Количество — Decimal, в JSON уходит строкой.

Цен в плане продаж нет: планируем объём, деньги считаются в других разделах.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SalesPlanItemIn(BaseModel):
    client_id: uuid.UUID = Field(description="Клиент, по которому планируется продажа")
    product_id: uuid.UUID
    month: int = Field(ge=1, le=12)
    quantity: Decimal = Field(ge=0, description="Количество на месяц")
    notes: str | None = Field(default=None, max_length=255)


class SalesPlanCreate(BaseModel):
    year: int = Field(ge=2020, le=2100)
    manager_id: uuid.UUID | None = Field(
        default=None, description="Обязателен, когда план создаёт коммерческий директор"
    )
    notes: str | None = None


class SalesPlanItemsIn(BaseModel):
    items: list[SalesPlanItemIn] = []


class SalesPlanRejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class SalesPlanItemOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str
    product_id: uuid.UUID
    product_code: str
    product_name: str
    product_kind: str
    unit: str
    month: int
    quantity: Decimal
    notes: str | None


class SalesPlanOut(BaseModel):
    id: uuid.UUID
    year: int
    manager_id: uuid.UUID
    manager_name: str
    created_by_name: str
    status: str
    status_title: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
    editable_months: list[int] = Field(description="Месяцы, которые сейчас можно менять")
    items: list[SalesPlanItemOut]


# --- План закупок сырья ---------------------------------------------------


class PurchasePlanItemIn(BaseModel):
    product_id: uuid.UUID
    month: int = Field(ge=1, le=12)
    quantity: Decimal = Field(gt=0, description="Количество на месяц")
    price_rub: Decimal | None = Field(default=None, ge=0, description="Цена за единицу, ₽")
    supplier_id: uuid.UUID | None = Field(default=None, description="Поставщик из справочника")
    delivery_days: int = Field(default=30, ge=0, le=365, description="Срок логистики, дней")
    notes: str | None = Field(default=None, max_length=255)


class PurchasePlanCreate(BaseModel):
    year: int = Field(ge=2020, le=2100)
    notes: str | None = None


class PurchasePlanItemsIn(BaseModel):
    items: list[PurchasePlanItemIn] = []


class PurchasePlanRejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class PurchasePlanItemOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_code: str
    product_name: str
    product_kind: str
    unit: str
    month: int
    quantity: Decimal
    price_rub: Decimal | None
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    delivery_days: int
    order_month: int | None
    notes: str | None


class PurchasePlanOut(BaseModel):
    id: uuid.UUID
    year: int
    status: str
    status_title: str
    created_by_name: str
    approved_by_name: str | None
    approved_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    editable_months: list[int] = Field(description="Месяцы, которые сейчас можно менять")
    items: list[PurchasePlanItemOut]
