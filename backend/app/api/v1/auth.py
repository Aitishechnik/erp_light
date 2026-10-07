"""Вход, выход и текущий пользователь."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.schemas.auth import LoginIn, UserOut, user_out
from app.services.auth import (
    SESSION_COOKIE,
    authenticate,
    create_session,
    delete_session,
)

router = APIRouter(tags=["auth"])


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
    return user_out(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(request: Request, response: Response, db: DbSession) -> Response:
    """Выход: удаляет сессию и cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    """Кто сейчас вошёл."""
    return user_out(user)
