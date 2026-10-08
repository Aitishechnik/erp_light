"""Схемы курсов валют."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class RateOut(BaseModel):
    code: str
    rate_date: date
    rate: Decimal
    nominal: int
    source: str
