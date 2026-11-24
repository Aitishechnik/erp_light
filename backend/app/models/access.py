"""Права уровней доступа: переопределения поверх значений по умолчанию.

Сама матрица по умолчанию живёт в коде (``app.permissions``): так права
восстановимы, а в базе лежат только те блоки, которые админ действительно менял.
Пустая строка ``actions`` означает «ничего нельзя» и отличается от отсутствия
строки — отсутствие возвращает значение по умолчанию.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RolePermission(Base):
    """Настройка одного блока прав для одного уровня доступа."""

    __tablename__ = "role_permissions"

    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    block: Mapped[str] = mapped_column(String(32), primary_key=True)
    actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # own — только свои строки, all — все.
    scope: Mapped[str] = mapped_column(String(8), nullable=False, default="all")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
