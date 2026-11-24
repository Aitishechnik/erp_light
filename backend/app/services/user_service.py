"""Сотрудники: заведение, правка, блокировка, сброс пароля и удаление.

Всё это делает администратор. Его собственная учётная запись через эти функции
не редактируется: роль и активность админа меняются только установочной командой,
иначе можно остаться без единственного администратора.

Удалить можно только сотрудника без истории: если он что-то делал или на нём
висят планы и задачи, удаление оборвало бы журнал и документы. Такого сотрудника
блокируют — вход закрывается, история остаётся.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.auth import (
    ROLE_ADMIN,
    ROLE_TITLES,
    ROLES,
    AuthSession,
    User,
)
from app.schemas.users import PASSWORD_MIN
from app.services import audit_service
from app.services.auth import hash_password

LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class UserAdminError(Exception):
    """Сотрудника нельзя завести или изменить; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_login(raw: str) -> str:
    return raw.strip().lower()


def _validate_login(login: str) -> None:
    if not LOGIN_RE.match(login):
        raise UserAdminError(
            "Логин: 3–64 символа, латиница, цифры, точка, дефис или подчёркивание",
        )


def _validate_role(role: str) -> None:
    if role not in ROLES:
        raise UserAdminError("Такого уровня доступа нет: администратора назначить нельзя")


def _validate_password(password: str) -> None:
    if len(password) < PASSWORD_MIN:
        raise UserAdminError(f"Пароль короче {PASSWORD_MIN} символов")
    if len(password) > 128:
        raise UserAdminError("Пароль длиннее 128 символов")


def _revoke_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


def list_users(db: Session) -> list[User]:
    """Все сотрудники, включая заблокированных: админ должен их видеть."""
    return list(
        db.execute(select(User).order_by(User.is_active.desc(), User.full_name, User.login))
        .scalars()
        .all()
    )


def create_user(
    db: Session, admin: User, *, login: str, full_name: str, password: str, role: str
) -> User:
    login = normalize_login(login)
    _validate_login(login)
    _validate_role(role)
    _validate_password(password)
    full_name = full_name.strip()
    if not full_name:
        raise UserAdminError("Укажите имя сотрудника")
    taken = db.execute(
        select(User.id).where(func.lower(User.login) == login).limit(1)
    ).scalar_one_or_none()
    if taken is not None:
        raise UserAdminError("Такой логин уже занят", status_code=409)

    user = User(
        login=login,
        full_name=full_name,
        role=role,
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    audit_service.record(
        db,
        actor=admin,
        action="user.created",
        summary=f"Заведён сотрудник {full_name} ({ROLE_TITLES[role]})",
        entity_id=user.id,
        entity_label=full_name,
        payload={"login": login, "role": role},
    )
    db.commit()
    return user


def update_user(
    db: Session,
    admin: User,
    user_id: uuid.UUID,
    *,
    full_name: str | None,
    role: str | None,
    is_active: bool | None,
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserAdminError("Сотрудник не найден", status_code=404)
    if user.role == ROLE_ADMIN:
        raise UserAdminError(
            "Учётная запись администратора не редактируется: сменить пароль можно, "
            "роль и блокировку — только установочной командой",
            status_code=403,
        )

    changes: dict[str, object] = {}
    if full_name is not None:
        clean = full_name.strip()
        if not clean:
            raise UserAdminError("Имя сотрудника не может быть пустым")
        if clean != user.full_name:
            changes["full_name"] = {"before": user.full_name, "after": clean}
            user.full_name = clean
    if role is not None and role != user.role:
        _validate_role(role)
        changes["role"] = {"before": user.role, "after": role}
        user.role = role
        # Новые права не должны догнать сотрудника в уже открытой сессии.
        _revoke_sessions(db, user.id)
    if is_active is not None and is_active != user.is_active:
        changes["is_active"] = {"before": user.is_active, "after": is_active}
        user.is_active = is_active
        if not is_active:
            _revoke_sessions(db, user.id)

    if changes:
        audit_service.record(
            db,
            actor=admin,
            action="user.updated",
            summary=f"Изменён сотрудник {user.full_name}: {', '.join(sorted(changes))}",
            entity_id=user.id,
            entity_label=user.full_name,
            payload={"login": user.login, "changes": changes},
        )
    db.commit()
    return user


def reset_password(db: Session, admin: User, user_id: uuid.UUID, password: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserAdminError("Сотрудник не найден", status_code=404)
    if user.role == ROLE_ADMIN and user.id != admin.id:
        raise UserAdminError("Пароль администратора меняет только он сам", status_code=403)
    _validate_password(password)
    user.password_hash = hash_password(password)
    if user.id != admin.id:
        _revoke_sessions(db, user.id)
    audit_service.record(
        db,
        actor=admin,
        action="user.password_reset",
        summary=(
            "Сменён пароль администратора"
            if user.id == admin.id
            else f"Сброшен пароль сотрудника {user.full_name}"
        ),
        entity_id=user.id,
        entity_label=user.full_name,
        payload={"login": user.login},
    )
    db.commit()
    return user


def delete_user(db: Session, admin: User, user_id: uuid.UUID) -> None:
    """Удалить сотрудника без истории. С историей — отказ и совет заблокировать."""
    user = db.get(User, user_id)
    if user is None:
        raise UserAdminError("Сотрудник не найден", status_code=404)
    if user.role == ROLE_ADMIN or user.id == admin.id:
        raise UserAdminError(
            "Администратора удалить нельзя: он один и заводится установочной командой",
            status_code=403,
        )

    actions = int(
        db.execute(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.actor_id == user.id)
        ).scalar_one()
    )
    if actions:
        raise UserAdminError(
            "У сотрудника есть история действий — удаление оборвало бы журнал. "
            "Заблокируйте его: вход закроется, история сохранится.",
            status_code=409,
        )

    login = user.login
    full_name = user.full_name
    db.delete(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise UserAdminError(
            "На сотруднике есть планы, задачи или другие документы — удалить нельзя. "
            "Заблокируйте его: вход закроется, история сохранится.",
            status_code=409,
        ) from exc

    audit_service.record(
        db,
        actor=admin,
        action="user.deleted",
        summary=f"Удалён сотрудник {full_name}",
        entity_label=full_name,
        payload={"login": login},
    )
    db.commit()
