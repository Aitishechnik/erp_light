"""Схемы страницы «План и факт»: год, месяц, клиент и позиция.

Три источника: годовой план (утверждённые планы менеджеров), месячный план
(утверждённый пересмотр) и факт из выгрузки 1С. Месячный план может отсутствовать —
тогда месяц равен годовому.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class PlanFactMonthOut(BaseModel):
    """Итоги одного месяца: годовой план, месячный план и факт."""

    year: int
    month: int
    annual_quantity: Decimal
    monthly_quantity: Decimal
    fact_quantity: Decimal
    fact_loaded: bool = False
    revised: bool = False
    monthly_state: str = "none"
    month_closed: bool = False
    window_start: date
    window_end: date
    window_state: str


class PlanFactSummaryOut(BaseModel):
    year: int
    annual_total: Decimal
    monthly_total: Decimal
    fact_total: Decimal
    months: list[PlanFactMonthOut]


class PlanFactRowOut(BaseModel):
    """Строка детализации: клиент × товар за месяц."""

    client_id: uuid.UUID
    client_name: str
    manager_id: uuid.UUID | None
    manager_name: str | None
    product_id: uuid.UUID
    product_name: str
    unit: str
    annual_quantity: Decimal
    monthly_quantity: Decimal
    fact_quantity: Decimal
    plan_reason: str | None = None
    fact_reason: str | None = None
    is_new: bool = False
    removed: bool = False


class PlanFactDetailOut(BaseModel):
    year: int
    month: int
    annual_quantity: Decimal
    monthly_quantity: Decimal
    fact_quantity: Decimal
    rows: list[PlanFactRowOut]
