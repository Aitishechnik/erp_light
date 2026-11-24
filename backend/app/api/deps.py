"""Общие зависимости API: сессия БД, текущий пользователь и проверка прав."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.auth import ROLE_ADMIN, User
from app.permissions import can
from app.services import access_service
from app.services.auth import SESSION_COOKIE, resolve_session

DbSession = Annotated[Session, Depends(get_db)]


def current_user(request: Request, db: DbSession) -> User:
    """Пользователь по cookie сессии; без валидной сессии — 401.

    Здесь же к пользователю прикрепляется профиль прав: сервисы читают его без
    похода в базу на каждую проверку.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход")
    user = resolve_session(db, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия истекла, войдите заново"
        )
    return access_service.attach(db, user)


CurrentUser = Annotated[User, Depends(current_user)]


def require_perm(block: str, action: str) -> Callable[[User], User]:
    """Пускает, если уровень доступа разрешает действие в блоке."""

    def dependency(user: CurrentUser) -> User:
        if not can(user, block, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этого действия",
            )
        return user

    return dependency


def require_admin(user: CurrentUser) -> User:
    """Только администратор: управление сотрудниками, ролями и его журнал."""
    if user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Действие доступно только администратору",
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]
