"""Загрузка справочников из выгрузок 1С и журнал загрузок."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import User
from app.models.domain import ImportSession
from app.schemas.imports import ImportKindOut, ImportSessionOut
from app.services import directory_service
from app.services import import_service as service
from app.services.import_service import KINDS, ImportDataError

router = APIRouter(tags=["imports"])

Loader = Annotated[User, Depends(require_roles(*directory_service.DIRECTORY_WRITE_ROLES))]


def _session_out(row: ImportSession) -> ImportSessionOut:
    return ImportSessionOut(
        id=row.id,
        kind=row.kind,
        kind_title=KINDS[row.kind].title if row.kind in KINDS else row.kind,
        file_name=row.file_name,
        status=row.status,
        rows_total=row.rows_total,
        rows_created=row.rows_created,
        rows_updated=row.rows_updated,
        rows_skipped=row.rows_skipped,
        rows_failed=row.rows_failed,
        message=row.message,
        created_at=row.created_at,
    )


@router.get("/imports/kinds", response_model=list[ImportKindOut])
def list_kinds(user: CurrentUser) -> list[ImportKindOut]:
    """Шесть типов данных, которые можно загружать."""
    return [
        ImportKindOut(
            kind=kind.kind, title=kind.title, entity=kind.entity, columns=list(kind.columns)
        )
        for kind in KINDS.values()
    ]


@router.get("/imports", response_model=list[ImportSessionOut])
def list_imports(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[ImportSessionOut]:
    """Журнал загрузок: что и когда загружали, с итогами."""
    return [_session_out(row) for row in service.list_sessions(db, limit=limit)]


@router.post("/imports/{kind}", response_model=ImportSessionOut)
def upload(
    kind: str,
    user: Loader,
    db: DbSession,
    file: Annotated[UploadFile, File(description="Выгрузка из 1С в формате .xlsx")],
) -> ImportSessionOut:
    """Загрузить файл выгрузки. Повторная загрузка не создаёт дублей."""
    content = file.file.read()
    try:
        result = service.import_file(db, kind, file.filename or "без имени.xlsx", content)
    except ImportDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _session_out(result.session)
