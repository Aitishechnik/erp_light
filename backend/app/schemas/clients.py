"""Схемы справочника клиентов."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Наименование клиента")
    inn: str | None = Field(default=None, max_length=12, description="ИНН, необязательно")
    note: str | None = None


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=12)
    note: str | None = None
    is_active: bool | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    inn: str | None
    note: str | None
    is_active: bool
