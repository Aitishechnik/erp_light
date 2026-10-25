"""Схемы итогов месяца: план продаж против факта."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class MonthRowOut(BaseModel):
    """Строка отчёта: клиент × товар, план и факт."""

    client_id: uuid.UUID
    client_name: str
    manager_id: uuid.UUID | None
    manager_name: str | None
    product_id: uuid.UUID
    product_name: str
    unit: str
    plan_quantity: Decimal
    fact_quantity: Decimal
    fact_amount: Decimal
    deviation: Decimal = Field(description="Факт минус план, в единице товара")
    group: str = Field(description="plan | extra | short")
    manager_mismatch: bool = Field(
        default=False, description="Клиент закреплён за другим менеджером, чем его план"
    )


class MonthUnmatchedOut(BaseModel):
    """Строка файла, которую не удалось сопоставить с номенклатурой."""

    id: uuid.UUID
    source_name: str
    client_name: str | None
    quantity: Decimal
    amount_rub: Decimal


class MonthResultOut(BaseModel):
    """Итоги месяца: строки, очередь сопоставления и счётчики."""

    year: int
    month: int
    plan_approved: bool
    rows: list[MonthRowOut]
    unmatched: list[MonthUnmatchedOut]
    lines: int
    deviation_lines: int
    extra_lines: int
    short_lines: int
    fact_amount: Decimal


class MatchIn(BaseModel):
    """Сопоставить строку файла карточке номенклатуры."""

    unmatched_id: uuid.UUID
    product_id: uuid.UUID


class MatchOut(BaseModel):
    matched: int
    remaining: int
