"""Справочник контрагентов: покупатели, локальные и импортные поставщики.

Одна компания может быть и покупателем, и поставщиком — поэтому это один справочник
с признаками, а не три отдельных. Дубли ловятся по `name_key`: наименование,
приведённое к нижнему регистру с одиночными пробелами.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def name_key(name: str) -> str:
    """Ключ поиска дублей: регистр и лишние пробелы не важны."""
    return " ".join(name.split()).strip().casefold()


class Counterparty(Base):
    """Контрагент с признаками роли."""

    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    inn: Mapped[str | None] = mapped_column(String(12), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_customer: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    is_local_supplier: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    is_import_supplier: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
