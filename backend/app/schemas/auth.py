"""Схемы входа, пользователя и прав доступа."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.auth import ROLE_ADMIN, ROLE_TITLES, User


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class BlockRightsOut(BaseModel):
    """Права на один блок: что можно и в каком охвате."""

    actions: list[str]
    scope: str = "all"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    login: str
    full_name: str
    role: str
    role_title: str
    is_active: bool = True
    created_at: datetime | None = None
    is_admin: bool = False
    # Заполняется только для текущего пользователя (/auth/me и вход).
    permissions: dict[str, BlockRightsOut] | None = None


def user_out(user: User, *, permissions: dict[str, BlockRightsOut] | None = None) -> UserOut:
    """Пользователь с русским названием роли и, если нужно, его правами."""
    return UserOut(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        role=user.role,
        role_title=ROLE_TITLES.get(user.role, user.role),
        is_active=user.is_active,
        created_at=user.created_at,
        is_admin=user.role == ROLE_ADMIN,
        permissions=permissions,
    )
