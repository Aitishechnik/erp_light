"""Схемы помесячного плана продаж.

Количество — Decimal (в JSON строкой), как и в годовом плане. Причина изменения
обязательна для любой строки, где месячное количество отличается от годового.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class MonthlyPlanItemIn(BaseModel):
    """Строка месячного плана: клиент × товар, количество и причина изменения."""

    client_id: uuid.UUID
    product_id: uuid.UUID
    quantity: Decimal = Field(ge=0, le=Decimal("999999999999.999"))
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Обязательна, если количество отличается от годового плана",
    )


class MonthlyPlanItemsIn(BaseModel):
    items: list[MonthlyPlanItemIn] = []


class MonthlyPlanItemOut(BaseModel):
    client_id: uuid.UUID
    client_name: str
    product_id: uuid.UUID
    product_code: str
    product_name: str
    unit: str
    annual_quantity: Decimal
    quantity: Decimal
    reason: str | None
    is_new: bool = Field(description="Позиции не было в годовом плане на этот месяц")
    is_removed: bool = Field(description="Позиция была в годовом плане, месячное количество 0")
    updated_at: datetime
    updated_by_name: str | None


class MonthlyPlanEventOut(BaseModel):
    """Событие истории пересмотра."""

    kind: str
    kind_title: str
    created_at: datetime
    actor_name: str | None
    client_id: uuid.UUID | None
    client_name: str | None
    product_id: uuid.UUID | None
    product_name: str | None
    old_quantity: Decimal | None
    new_quantity: Decimal | None
    reason: str | None


class MonthlyPlanOut(BaseModel):
    year: int
    month: int
    manager_id: uuid.UUID
    manager_name: str
    status: str
    status_title: str
    window_start: date
    window_end: date
    window_state: str = Field(description="not_started | open | closed")
    can_edit: bool
    can_approve: bool
    approved_at: datetime | None
    approved_by_name: str | None
    changed_lines: int = Field(description="Строк, где месяц отличается от года")
    items: list[MonthlyPlanItemOut]
