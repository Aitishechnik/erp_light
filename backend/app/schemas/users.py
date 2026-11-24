"""Схемы управления сотрудниками: их заводит и правит администратор."""

from __future__ import annotations

from pydantic import BaseModel, Field

PASSWORD_MIN = 8


class AdminUserIn(BaseModel):
    """Новый сотрудник."""

    login: str = Field(min_length=3, max_length=64)
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    # Ключ уровня доступа из шести бизнес-ролей; админа назначить нельзя.
    role: str


class AdminUserUpdate(BaseModel):
    """Правка сотрудника: любое поле можно не передавать."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = None
    is_active: bool | None = None


class PasswordIn(BaseModel):
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
