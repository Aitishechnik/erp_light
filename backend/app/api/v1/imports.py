"""Загрузка справочников из выгрузок 1С и журнал загрузок."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.models.domain import ImportSession
from app.schemas.imports import ImportKindOut, ImportSessionOut
from app.services import import_service as service
from app.services.import_service import KINDS, ImportDataError

router = APIRouter(tags=["imports"])


def session_out(row: ImportSession) -> ImportSessionOut:
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
    """Типы данных, которые можно загружать. Роли — чтобы экран показал доступное.

    Типы с ``listed=False`` (позиции партии) грузятся из карточки поступления:
    в списке они не нужны, но в журнале видны.
    """
    return [
        ImportKindOut(
            kind=kind.kind,
            title=kind.title,
            entity=kind.entity,
            columns=list(kind.columns),
            roles=list(kind.roles),
            note=kind.note,
        )
        for kind in KINDS.values()
        if kind.listed
    ]


@router.get("/imports", response_model=list[ImportSessionOut])
def list_imports(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[ImportSessionOut]:
    """Журнал загрузок: что и когда загружали, с итогами."""
    return [session_out(row) for row in service.list_sessions(db, limit=limit)]


@router.post("/imports/{kind}", response_model=ImportSessionOut)
def upload(
    kind: str,
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="Выгрузка из 1С в формате .xlsx")],
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
) -> ImportSessionOut:
    """Загрузить файл выгрузки. Повторная загрузка не создаёт дублей.

    Права зависят от типа: справочники грузят продажи/коммерция/закупки, импортные
    поступления — только закупки.
    """
    spec = KINDS.get(kind)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Неизвестный тип загрузки: {kind}")
    if user.role not in spec.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для этого действия")
    content = file.file.read()
    try:
        result = service.import_file(
            db, kind, file.filename or "без имени.xlsx", content, year=year, month=month
        )
    except ImportDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return session_out(result.session)
