"""Схемы плана продаж. Деньги и количество — Decimal, в JSON уходят строкой."""

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
    price: Decimal | None = Field(default=None, ge=0, description="Цена за единицу, одна на строку")
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
    price: Decimal | None
    amount: Decimal | None = Field(description="Количество × цена")
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
    total_amount: Decimal = Field(description="Сумма по всем строкам плана")
