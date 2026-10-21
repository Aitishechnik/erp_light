"""Справочник стран: название и срок доставки сырья.

Срок доставки — параметр закупки: по нему план закупок сдвигает месяц заказа
назад от месяца потребности. Название уникально без учёта регистра и лишних
пробелов (тот же ключ, что у контрагентов).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.counterparties import name_key


class Country(Base):
    """Страна происхождения сырья и срок доставки из неё."""

    __tablename__ = "countries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    delivery_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, comment="Срок доставки, дней"
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["Country", "name_key"]
