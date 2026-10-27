"""Журнал действий и служебные сообщения.

Одна строка — одно действие пользователя. Журнал хранит всё, что мы решили
фиксировать; служебное сообщение — это строка с ``is_message`` и адресатом
в ``audience`` (список ролей). Прочитанность живёт отдельно, чтобы журнал
не разрастался отметками каждого пользователя.

Деньги в журнал не кладём: только количества, статусы и ссылки на объект.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.auth import User

# Уровни: critical — то, что меняет обязательства или справочник; info — рабочие шаги.
AUDIT_LEVELS = ("info", "critical")


class AuditEvent(Base):
    """Событие журнала: кто, что, когда и с каким объектом."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_action", "action"),
        Index("ix_audit_events_entity", "entity_kind", "entity_id"),
        Index("ix_audit_events_message", "is_message", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Порядковый номер: события в одну секунду всё равно идут в порядке записи.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Автора может не быть: систему и неудачный вход пишем без пользователя.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    entity_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    entity_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Служебное сообщение: показываем в колокольчике (в журнале видно всегда).
    is_message: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Кому адресовано: список ролей; ["all"] — всем.
    audience: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    actor: Mapped[User | None] = relationship(lazy="joined")


class AuditEventRead(Base):
    """Отметка «прочитано» для служебного сообщения."""

    __tablename__ = "audit_event_reads"

    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_events.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["AUDIT_LEVELS", "AuditEvent", "AuditEventRead"]
