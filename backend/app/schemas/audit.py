"""Схемы журнала действий и служебных сообщений."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AuditEventOut(BaseModel):
    """Строка журнала или карточка служебного сообщения."""

    id: uuid.UUID
    created_at: datetime
    action: str
    action_title: str
    level: str
    entity_kind: str | None = None
    entity_id: uuid.UUID | None = None
    entity_label: str | None = None
    summary: str
    actor_name: str | None = None
    actor_role_title: str | None = None
    year: int | None = None
    month: int | None = None
    read: bool = Field(default=False, description="Прочитано текущим пользователем")


class MessagesOut(BaseModel):
    """Сообщения, сколько их всего и счётчик непрочитанных."""

    rows: list[AuditEventOut]
    unread: int
    total: int = Field(default=0, description="Сколько сообщений у пользователя всего")


class UnreadOut(BaseModel):
    """Только счётчик непрочитанных."""

    unread: int


class MarkReadIn(BaseModel):
    """Какие сообщения отметить прочитанными."""

    ids: list[uuid.UUID] = Field(default_factory=list)
