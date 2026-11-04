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


class DecisionOut(BaseModel):
    """Решение месяца: что делаем с нереализованным объёмом."""

    code: str
    title: str
    comment: str | None
    target_year: int | None
    target_month: int | None
    author_name: str | None
    at: datetime


class MonthTotalsOut(BaseModel):
    """Итоги снимка: счётчики строк и сумма факта."""

    lines: int
    deviation_lines: int
    extra_lines: int
    short_lines: int
    without_reason: int
    fact_amount: Decimal


class HistoryDecisionOut(BaseModel):
    """Решение месяца из снимка: в старых версиях автора и даты может не быть."""

    code: str
    title: str
    target_year: int | None = None
    target_month: int | None = None
    author_name: str | None = None
    at: datetime | None = None


class MonthHistoryItemOut(BaseModel):
    """Одна версия снимка месяца: когда закрыли, кто и с какими итогами."""

    version: int
    closed_at: datetime
    closed_by_name: str | None
    totals: MonthTotalsOut
    decision: HistoryDecisionOut | None = None


class DecisionIn(BaseModel):
    """Поставить решение месяца."""

    decision: str = Field(max_length=32)
    target_year: int | None = Field(default=None, ge=2020, le=2100)
    target_month: int | None = Field(default=None, ge=1, le=12)
    comment: str | None = Field(default=None, max_length=500)


class ReopenIn(BaseModel):
    """Открыть закрытый месяц заново: причина обязательна."""

    reason: str = Field(min_length=1, max_length=500)


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
    status: str = Field(description="open | closed")
    closed_by_name: str | None = None
    closed_at: datetime | None = None
    reopen_reason: str | None = None
    decision: DecisionOut | None = None


class TransferDraftOut(BaseModel):
    """Черновик корректировки, созданный из решения месяца."""

    manager_name: str
    plan_id: uuid.UUID
    correction_id: uuid.UUID
    lines: int
    quantity: Decimal


class TransferSkippedOut(BaseModel):
    """Менеджер, чьи строки не перенеслись, и причина."""

    manager_name: str
    reason: str


class TransferDraftsOut(BaseModel):
    """Итог кнопки «создать корректировки»: что создано и что пропущено."""

    created: list[TransferDraftOut]
    skipped: list[TransferSkippedOut]


class MatchIn(BaseModel):
    """Сопоставить строку файла карточке номенклатуры."""

    unmatched_id: uuid.UUID
    product_id: uuid.UUID


class MatchOut(BaseModel):
    matched: int
    remaining: int
