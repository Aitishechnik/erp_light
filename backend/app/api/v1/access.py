"""Конструктор прав: описание блоков, уровни и сохранение настроек.

Читать и менять может только администратор: это его инструмент.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import AdminUser, DbSession
from app.schemas.access import AccessOut, BlockOut, LevelOut, LevelUpdate
from app.services import access_service
from app.services.access_service import AccessError

router = APIRouter(tags=["access"])


@router.get("/access", response_model=AccessOut)
def get_access(user: AdminUser, db: DbSession) -> AccessOut:
    """Блоки, действия и текущие права всех шести уровней."""
    return AccessOut(
        levels=[LevelOut.model_validate(row) for row in access_service.levels_payload(db)],
        blocks=[BlockOut.model_validate(row) for row in access_service.blocks_payload()],
    )


@router.put("/access/{level}", response_model=LevelOut)
def save_access(level: str, payload: LevelUpdate, user: AdminUser, db: DbSession) -> LevelOut:
    """Сохранить права уровня: что включено и в каком охвате."""
    try:
        saved = access_service.save_level(
            db,
            user,
            level,
            {block: (rights.actions, rights.scope) for block, rights in payload.rights.items()},
        )
    except AccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return LevelOut.model_validate(saved)
