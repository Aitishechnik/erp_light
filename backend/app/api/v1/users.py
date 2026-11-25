"""Справочник пользователей: нужен, чтобы выбрать менеджера для плана."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.auth import User
from app.permissions import can
from app.schemas.auth import UserOut, user_out

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    user: CurrentUser,
    db: DbSession,
    role: str | None = Query(default=None, description="Фильтр по роли"),
) -> list[UserOut]:
    """Список пользователей: кому разрешено право «Список сотрудников»."""
    if not can(user, "users", "view"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Справочник сотрудников вам недоступен"
        )
    statement = select(User).where(User.is_active.is_(True)).order_by(User.full_name)
    if role:
        statement = statement.where(User.role == role)
    return [user_out(row) for row in db.execute(statement).scalars().all()]


@router.get("/users/managers", response_model=list[UserOut])
def list_managers(user: CurrentUser, db: DbSession) -> list[UserOut]:
    """Активные сотрудники, которые ведут клиентов, — для карточки и планов.

    Должность не важна: коммерческий директор и ассистент попадают сюда, если
    админ отметил «Ведёт клиентов». Доступно любому вошедшему: в списке нет
    ничего, кроме имени, должности и признака менеджера.
    """
    statement = (
        select(User)
        .where(User.is_active.is_(True), User.is_manager.is_(True))
        .order_by(User.full_name)
    )
    return [user_out(row) for row in db.execute(statement).scalars().all()]
