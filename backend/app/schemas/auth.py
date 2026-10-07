"""Схемы входа и пользователя."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.auth import ROLE_TITLES, User


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    login: str
    full_name: str
    role: str
    role_title: str


def user_out(user: User) -> UserOut:
    """Пользователь с русским названием роли."""
    return UserOut(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        role=user.role,
        role_title=ROLE_TITLES.get(user.role, user.role),
    )
