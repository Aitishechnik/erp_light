"""Справочник пользователей: нужен, чтобы выбрать менеджера для плана."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_SALES_MANAGER,
    User,
)
from app.schemas.auth import UserOut, user_out

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    user: CurrentUser,
    db: DbSession,
    role: str | None = Query(default=None, description="Фильтр по роли"),
) -> list[UserOut]:
    """Список пользователей: доступен коммерческому и исполнительному директору."""
    if user.role not in (ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Справочник сотрудников вам недоступен"
        )
    statement = select(User).where(User.is_active.is_(True)).order_by(User.full_name)
    if role:
        statement = statement.where(User.role == role)
    return [user_out(row) for row in db.execute(statement).scalars().all()]


@router.get("/users/managers", response_model=list[UserOut])
def list_managers(user: CurrentUser, db: DbSession) -> list[UserOut]:
    """Активные менеджеры по продажам — для карточки клиента и планов.

    Доступно любому вошедшему: в списке нет ничего, кроме имени и роли.
    """
    statement = (
        select(User)
        .where(User.is_active.is_(True), User.role == ROLE_SALES_MANAGER)
        .order_by(User.full_name)
    )
    return [user_out(row) for row in db.execute(statement).scalars().all()]
