"""Схемы справочника стран."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class CountryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, description="Название страны")
    delivery_days: int = Field(ge=1, le=365, description="Срок доставки, дней")
    is_active: bool = True


class CountryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    delivery_days: int | None = Field(default=None, ge=1, le=365)
    is_active: bool | None = None


class CountryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    delivery_days: int
    is_active: bool
    source: str
