"""Курсы валют: кэш официальных курсов ЦБ РФ по датам.

Курс хранится в рублях за одну единицу валюты (номинал уже учтён), поэтому
для USD «90,5» — это 90,5 ₽ за доллар, как бы ЦБ ни публиковал номинал.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CurrencyRate(Base):
    """Курс валюты на дату (рублей за единицу)."""

    __tablename__ = "currency_rates"
    __table_args__ = (UniqueConstraint("rate_date", "code", name="currency_rate_date_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    nominal: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rate: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, comment="Рублей за одну единицу валюты"
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="cbr")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
