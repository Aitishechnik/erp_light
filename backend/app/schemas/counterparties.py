"""Схемы справочника контрагентов."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class CounterpartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Наименование контрагента")
    inn: str | None = Field(default=None, max_length=12, description="ИНН, необязательно")
    note: str | None = None
    is_customer: bool = False
    is_local_supplier: bool = False
    is_import_supplier: bool = False


class CounterpartyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=12)
    note: str | None = None
    is_customer: bool | None = None
    is_local_supplier: bool | None = None
    is_import_supplier: bool | None = None
    is_active: bool | None = None


class CounterpartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    inn: str | None
    note: str | None
    is_customer: bool
    is_local_supplier: bool
    is_import_supplier: bool
    source: str
    is_active: bool
