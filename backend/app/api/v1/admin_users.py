"""Управление сотрудниками: только администратор."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import AdminUser, DbSession
from app.schemas.auth import UserOut, user_out
from app.schemas.users import AdminUserIn, AdminUserUpdate, PasswordIn
from app.services import user_service
from app.services.user_service import UserAdminError

router = APIRouter(tags=["admin-users"])


def _fail(exc: UserAdminError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/admin/users", response_model=list[UserOut])
def list_all_users(user: AdminUser, db: DbSession) -> list[UserOut]:
    """Все сотрудники, включая заблокированных."""
    return [user_out(row) for row in user_service.list_users(db)]


@router.post("/admin/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: AdminUserIn, user: AdminUser, db: DbSession) -> UserOut:
    """Завести сотрудника с логином, паролем и уровнем доступа."""
    try:
        created = user_service.create_user(
            db,
            user,
            login=payload.login,
            full_name=payload.full_name,
            password=payload.password,
            role=payload.role,
        )
    except UserAdminError as exc:
        raise _fail(exc) from exc
    return user_out(created)


@router.patch("/admin/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, payload: AdminUserUpdate, user: AdminUser, db: DbSession
) -> UserOut:
    """Изменить имя, уровень доступа или заблокировать сотрудника."""
    try:
        updated = user_service.update_user(
            db,
            user,
            user_id,
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
        )
    except UserAdminError as exc:
        raise _fail(exc) from exc
    return user_out(updated)


@router.post("/admin/users/{user_id}/password", response_model=UserOut)
def reset_password(
    user_id: uuid.UUID, payload: PasswordIn, user: AdminUser, db: DbSession
) -> UserOut:
    """Сбросить пароль сотруднику; себе админ тоже может сменить пароль."""
    try:
        updated = user_service.reset_password(db, user, user_id, payload.password)
    except UserAdminError as exc:
        raise _fail(exc) from exc
    return user_out(updated)


@router.delete(
    "/admin/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_user(user_id: uuid.UUID, user: AdminUser, db: DbSession) -> Response:
    """Удалить сотрудника без истории; с историей — 409 и совет заблокировать."""
    try:
        user_service.delete_user(db, user, user_id)
    except UserAdminError as exc:
        raise _fail(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
