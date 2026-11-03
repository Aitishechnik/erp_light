"""Справочник контрагентов: список, заведение, правка, отключение."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.auth import User
from app.models.counterparties import Counterparty
from app.schemas.counterparties import CounterpartyIn, CounterpartyOut, CounterpartyUpdate
from app.services import audit_service
from app.services import directory_service as service
from app.services.directory_service import DIRECTORY_WRITE_ROLES, DirectoryError

router = APIRouter(tags=["counterparties"])

Writer = Annotated[User, Depends(require_roles(*DIRECTORY_WRITE_ROLES))]

# Фильтр «роль контрагента» → колонка-признак.
# Что именно поменяли — по-русски, а не именами полей.
FIELD_TITLES = {
    "name": "название",
    "inn": "ИНН",
    "note": "заметка",
    "manager_id": "менеджер клиента",
    "is_customer": "признак покупателя",
    "is_local_supplier": "признак местного поставщика",
    "is_import_supplier": "признак импортного поставщика",
    "is_active": "активность",
}

ROLE_FIELDS = {
    "customer": "is_customer",
    "local_supplier": "is_local_supplier",
    "import_supplier": "is_import_supplier",
}


def _fail(exc: DirectoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _out(row: Counterparty) -> CounterpartyOut:
    """Ответ с именем закреплённого менеджера: фронту не нужен второй запрос."""
    result = CounterpartyOut.model_validate(row)
    if row.manager is not None:
        result.manager_name = row.manager.full_name
    return result


@router.get("/counterparties", response_model=list[CounterpartyOut])
def list_counterparties(
    user: CurrentUser,
    db: DbSession,
    role: str | None = Query(
        default=None, description="customer | local_supplier | import_supplier"
    ),
    include_inactive: bool = Query(default=False, description="Показать и отключённых"),
) -> list[CounterpartyOut]:
    """Контрагенты: покупатели, локальные и импортные поставщики.

    Список отдаётся целиком: фильтры и сортировка — на стороне таблицы.
    """
    if role is not None and role not in ROLE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Роль контрагента: customer, local_supplier или import_supplier",
        )
    rows = service.list_counterparties(
        db, role_field=ROLE_FIELDS.get(role) if role else None, include_inactive=include_inactive
    )
    return [_out(row) for row in rows]


@router.get("/counterparties/{counterparty_id}", response_model=CounterpartyOut)
def get_counterparty(
    counterparty_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> CounterpartyOut:
    """Один контрагент: по нему таблица показывает объект из сообщения."""
    try:
        return _out(service.get_counterparty(db, counterparty_id))
    except DirectoryError as exc:
        raise _fail(exc) from exc


@router.post("/counterparties", response_model=CounterpartyOut, status_code=status.HTTP_201_CREATED)
def create_counterparty(payload: CounterpartyIn, user: Writer, db: DbSession) -> CounterpartyOut:
    try:
        row = service.create_counterparty(db, payload)
    except DirectoryError as exc:
        raise _fail(exc) from exc
    audit_service.record(
        db,
        actor=user,
        action="counterparty.created",
        summary=f"Заведён контрагент {row.name}",
        entity_id=row.id,
        entity_label=row.name,
    )
    db.commit()
    return _out(row)


@router.patch("/counterparties/{counterparty_id}", response_model=CounterpartyOut)
def update_counterparty(
    counterparty_id: uuid.UUID, payload: CounterpartyUpdate, user: Writer, db: DbSession
) -> CounterpartyOut:
    try:
        row = service.update_counterparty(db, counterparty_id, payload)
    except DirectoryError as exc:
        raise _fail(exc) from exc
    changed = sorted(payload.model_dump(exclude_none=True))
    titles = ", ".join(FIELD_TITLES.get(field, field) for field in changed) or "поля"
    audit_service.record(
        db,
        actor=user,
        action="counterparty.updated",
        summary=f"Изменён контрагент {row.name}: {titles}",
        entity_id=row.id,
        entity_label=row.name,
        payload={"fields": changed},
    )
    db.commit()
    return _out(row)
