"""Служебные сообщения исполнительному директору и журнал действий."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.audit import AuditEventOut, MarkReadIn, MessagesOut, UnreadOut
from app.services import audit_service

router = APIRouter(tags=["audit"])


@router.get("/messages", response_model=MessagesOut)
def list_messages(
    user: CurrentUser,
    db: DbSession,
    unread: bool = Query(default=False, description="Только непрочитанные"),
    limit: int = Query(default=20, ge=1, le=100),
    before: Annotated[datetime | None, Query(description="Курсор: старше этой даты")] = None,
) -> MessagesOut:
    """Служебные сообщения текущего пользователя, свежие сверху."""
    return audit_service.messages(db, user, unread_only=unread, limit=limit, before=before)


@router.get("/messages/count", response_model=UnreadOut)
def unread_messages(user: CurrentUser, db: DbSession) -> UnreadOut:
    """Сколько сообщений не прочитано — для счётчика на колокольчике."""
    return UnreadOut(unread=audit_service.unread_count(db, user))


@router.post("/messages/read", response_model=UnreadOut)
def read_messages(payload: MarkReadIn, user: CurrentUser, db: DbSession) -> UnreadOut:
    """Отметить выбранные сообщения прочитанными."""
    return UnreadOut(unread=audit_service.mark_read(db, user, payload.ids))


@router.post("/messages/read-all", response_model=UnreadOut)
def read_all_messages(user: CurrentUser, db: DbSession) -> UnreadOut:
    """Отметить все сообщения прочитанными."""
    return UnreadOut(unread=audit_service.mark_all_read(db, user))


@router.get("/audit", response_model=list[AuditEventOut])
def journal(
    user: CurrentUser,
    db: DbSession,
    action: Annotated[str | None, Query(description="Код события")] = None,
    entity_kind: Annotated[str | None, Query(description="Тип объекта")] = None,
    entity_id: Annotated[uuid.UUID | None, Query(description="Объект")] = None,
    limit: int = Query(default=50, ge=1, le=100),
    before: Annotated[datetime | None, Query(description="Курсор: старше этой даты")] = None,
) -> list[AuditEventOut]:
    """Журнал действий: директор видит всё, остальные — свои действия."""
    try:
        return audit_service.journal(
            db,
            user,
            action=action,
            entity_kind=entity_kind,
            entity_id=entity_id,
            limit=limit,
            before=before,
        )
    except audit_service.AuditError as exc:  # pragma: no cover - защита на будущее
        raise HTTPException(exc.status_code, exc.message) from exc
