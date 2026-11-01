"""Пользователи и сессии входа.

Минимальный вход нужен цепочкам согласования: без автора перехода «утверждено»
ничего не значит. Пароли хранятся только в виде pbkdf2-хеша с солью.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Пять ролей erp_lite.
ROLE_SALES_MANAGER = "sales_manager"
ROLE_SALES_ASSISTANT = "sales_assistant"
ROLE_COMMERCIAL_DIRECTOR = "commercial_director"
ROLE_PURCHASE_DIRECTOR = "purchase_director"
ROLE_IMPORT_MANAGER = "import_manager"
ROLE_EXECUTIVE_DIRECTOR = "executive_director"

ROLES = (
    ROLE_SALES_MANAGER,
    ROLE_SALES_ASSISTANT,
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_IMPORT_MANAGER,
    ROLE_EXECUTIVE_DIRECTOR,
)

ROLE_TITLES = {
    ROLE_SALES_MANAGER: "Менеджер по продажам",
    ROLE_SALES_ASSISTANT: "Ассистент отдела продаж",
    ROLE_COMMERCIAL_DIRECTOR: "Коммерческий директор",
    ROLE_PURCHASE_DIRECTOR: "Директор по закупкам",
    ROLE_IMPORT_MANAGER: "Менеджер по закупкам (импорт)",
    ROLE_EXECUTIVE_DIRECTOR: "Исполнительный директор",
}


class User(Base):
    """Сотрудник с одной ролью."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    """Сессия входа: в cookie уходит токен, в базе лежит только его хеш."""

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="sessions", lazy="joined")
