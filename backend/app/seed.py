"""Сид демонстрационных пользователей: по одному на роль.

    SEED_PASSWORD=<пароль> python -m app.seed
    make seed-users            # сгенерирует пароль и напечатает его

Пароль обязателен: без него команда генерирует случайный и печатает один раз.
"""

from __future__ import annotations

import os
import secrets

import app.models  # noqa: F401 — регистрирует таблицы в Base.metadata
from app.db import Base, SessionLocal, engine
from app.services.auth import DEMO_USERS, seed_demo_users


def main() -> None:
    password = os.environ.get("SEED_PASSWORD") or secrets.token_urlsafe(12)
    generated = "SEED_PASSWORD" not in os.environ
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        users = seed_demo_users(db, password)

    print("Пользователи (логин — роль):")
    for (role, login, full_name), user in zip(DEMO_USERS, users, strict=True):
        print(f"  {login:<10} {full_name} [{role}] — id {user.id}")
    if generated:
        print(f"\nСгенерирован пароль для всех демо-пользователей: {password}")
        print("Сохраните его: повторный запуск без SEED_PASSWORD сменит пароль.")
    else:
        print("\nПароль взят из SEED_PASSWORD.")


if __name__ == "__main__":
    main()
