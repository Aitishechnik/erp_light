"""Общие зависимости API: сессия БД и текущий пользователь."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.auth import User
from app.services.auth import SESSION_COOKIE, resolve_session

DbSession = Annotated[Session, Depends(get_db)]


def current_user(request: Request, db: DbSession) -> User:
    """Пользователь по cookie сессии; без валидной сессии — 401."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход")
    user = resolve_session(db, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия истекла, войдите заново"
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_roles(*roles: str) -> Callable[[User], User]:
    """Проверка роли: пускает только перечисленные роли, иначе 403."""

    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этого действия",
            )
        return user

    return dependency
