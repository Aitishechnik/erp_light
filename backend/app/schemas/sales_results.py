"""Схемы итогов месяца: план продаж против факта."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReasonOut(BaseModel):
    """Причина отклонения по строке итогов."""

    code: str
    title: str
    comment: str | None
    author_name: str | None
    updated_at: datetime


class ReasonOptionOut(BaseModel):
    """Вариант причины для выпадающего списка."""

    code: str
    title: str


class ReasonIn(BaseModel):
    """Поставить или изменить причину."""

    client_id: uuid.UUID
    product_id: uuid.UUID
    reason: str = Field(max_length=32)
    comment: str | None = Field(default=None, max_length=500)


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
    reason: ReasonOut | None = Field(default=None, description="Причина отклонения")


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
    without_reason: int = Field(description="Строки с отклонением без причины")
    reason_options: list[ReasonOptionOut]
    fact_amount: Decimal


class MatchIn(BaseModel):
    """Сопоставить строку файла карточке номенклатуры."""

    unmatched_id: uuid.UUID
    product_id: uuid.UUID


class MatchOut(BaseModel):
    matched: int
    remaining: int
