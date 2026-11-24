"""Вход, выход и текущий пользователь."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.models.auth import User
from app.permissions import Rights
from app.schemas.auth import BlockRightsOut, LoginIn, UserOut, user_out
from app.services import access_service
from app.services.auth import (
    SESSION_COOKIE,
    authenticate,
    create_session,
    delete_session,
)

router = APIRouter(tags=["auth"])


def _out(db: Session, user: User) -> UserOut:
    """Пользователь вместе с правами: по ним интерфейс строит меню и кнопки."""
    profile = access_service.profile(db, user)
    return user_out(
        user,
        permissions={
            block: BlockRightsOut(actions=sorted(rights.actions), scope=rights.scope)
            for block, rights in profile.items()
        },
    )


@router.post("/auth/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, db: DbSession) -> UserOut:
    """Вход по логину и паролю; ставит cookie сессии."""
    user = authenticate(db, payload.login, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль"
        )
    ttl_days = get_settings().session_ttl_days
    token = create_session(db, user, ttl_days=ttl_days)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=ttl_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return _out(db, user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(request: Request, response: Response, db: DbSession) -> Response:
    """Выход: удаляет сессию и cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser, db: DbSession) -> UserOut:
    """Кто сейчас вошёл, и что ему разрешено."""
    profile: dict[str, Rights] = getattr(user, "access_profile", {})
    return user_out(
        user,
        permissions={
            block: BlockRightsOut(actions=sorted(rights.actions), scope=rights.scope)
            for block, rights in profile.items()
        },
    )
