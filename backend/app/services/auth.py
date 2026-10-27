"""Пароли, сессии входа и сид пользователей.

Пароль хранится как pbkdf2-sha256 с солью; в cookie уходит случайный токен,
в базе лежит только его sha256-хеш.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_IMPORT_MANAGER,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_SALES_MANAGER,
    AuthSession,
    User,
)
from app.services import audit_service

SESSION_COOKIE = "erp_lite_session"
PBKDF2_ITERATIONS = 210_000
DEFAULT_SESSION_TTL_DAYS = 30


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    _, iterations_raw, salt_hex, hash_hex = parts
    try:
        iterations = int(iterations_raw)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest.hex(), hash_hex)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate(db: Session, login: str, password: str) -> User | None:
    user = db.execute(select(User).where(User.login == login)).scalars().one_or_none()
    if user is None or not user.is_active:
        _log_failure(db, login)
        return None
    if not verify_password(password, user.password_hash):
        _log_failure(db, login)
        return None
    return user


def _log_failure(db: Session, login: str) -> None:
    """Неудачный вход — критическое событие для исполнительного директора."""
    audit_service.record(
        db,
        actor=None,
        action="auth.login_failed",
        summary=f"Неудачная попытка входа: {login}",
        actor_login=login,
        entity_label=login,
    )
    db.commit()


def create_session(db: Session, user: User, *, ttl_days: int = DEFAULT_SESSION_TTL_DAYS) -> str:
    """Создаёт сессию и возвращает токен для cookie."""
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        )
    )
    db.commit()
    return token


def resolve_session(db: Session, token: str) -> User | None:
    """Пользователь по токену сессии; просроченные сессии удаляются."""
    row = (
        db.execute(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        .scalars()
        .one_or_none()
    )
    if row is None:
        return None
    if row.expires_at <= datetime.now(UTC):
        db.delete(row)
        db.commit()
        return None
    user = row.user
    return user if user.is_active else None


def delete_session(db: Session, token: str) -> None:
    row = (
        db.execute(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        .scalars()
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.commit()


# Демонстрационные пользователи: по одному на роль.
DEMO_USERS: tuple[tuple[str, str, str], ...] = (
    (ROLE_SALES_MANAGER, "sales", "Менеджер по продажам (демо)"),
    (ROLE_SALES_MANAGER, "sales2", "Менеджер по продажам 2 (демо)"),
    (ROLE_SALES_MANAGER, "sales3", "Менеджер по продажам 3 (демо)"),
    (ROLE_COMMERCIAL_DIRECTOR, "commercial", "Коммерческий директор (демо)"),
    (ROLE_PURCHASE_DIRECTOR, "purchase", "Директор по закупкам (демо)"),
    (ROLE_IMPORT_MANAGER, "import", "Менеджер по закупкам, импорт (демо)"),
    (ROLE_EXECUTIVE_DIRECTOR, "executive", "Исполнительный директор (демо)"),
)


def seed_demo_users(db: Session, password: str) -> list[User]:
    """Создаёт/обновляет по одному пользователю на роль. Идемпотентно."""
    created: list[User] = []
    for role, login, full_name in DEMO_USERS:
        user = db.execute(select(User).where(User.login == login)).scalars().one_or_none()
        if user is None:
            user = User(
                login=login,
                full_name=full_name,
                role=role,
                password_hash=hash_password(password),
            )
            db.add(user)
        else:
            user.role = role
            user.full_name = full_name
            user.password_hash = hash_password(password)
            user.is_active = True
        created.append(user)
    db.commit()
    return created
