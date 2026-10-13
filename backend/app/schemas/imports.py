"""Схемы загрузки выгрузок 1С и журнала загрузок."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ImportKindOut(BaseModel):
    kind: str
    title: str
    entity: str
    columns: list[str]
    roles: list[str]
    note: str | None = None


class ImportSessionOut(BaseModel):
    id: uuid.UUID
    kind: str
    kind_title: str
    file_name: str
    status: str
    rows_total: int
    rows_created: int
    rows_updated: int
    rows_skipped: int
    rows_failed: int
    message: str | None
    created_at: datetime
