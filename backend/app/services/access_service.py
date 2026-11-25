"""Сборка прав уровня: значения по умолчанию плюс переопределения из базы.

Менеджер зависимостей прикрепляет готовый профиль к пользователю
(``user.access_profile``), поэтому проверки в сервисах не ходят в базу на каждый
вызов. Админ меняет права — это отдельный запрос, следующий запрос пользователя
уже увидит новую матрицу.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.access import RolePermission
from app.models.auth import ROLE_ADMIN, ROLE_TITLES, ROLES, User
from app.permissions import (
    BLOCK_BY_KEY,
    BLOCKS,
    DEFAULTS,
    LEVEL_DESCRIPTIONS,
    Rights,
    defaults_for,
)
from app.services import audit_service


class AccessError(Exception):
    """Нельзя сохранить права: переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def profile(db: Session, user: User) -> dict[str, Rights]:
    """Права пользователя: стартовая матрица, поверх — сохранённые переопределения."""
    rights = dict(defaults_for(user.role))
    if user.role != ROLE_ADMIN:
        rows = (
            db.execute(select(RolePermission).where(RolePermission.role == user.role))
            .scalars()
            .all()
        )
        for row in rows:
            rights[row.block] = Rights(frozenset(row.actions), row.scope)
    return rights


def attach(db: Session, user: User) -> User:
    """Прикрепить профиль к пользователю текущего запроса."""
    setattr(user, "access_profile", profile(db, user))  # noqa: B010
    return user


def level_rights(db: Session, role: str) -> dict[str, Rights]:
    """Права уровня без привязки к пользователю (для конструктора)."""
    rights = dict(defaults_for(role))
    if role != ROLE_ADMIN:
        rows = db.execute(select(RolePermission).where(RolePermission.role == role)).scalars().all()
        for row in rows:
            rights[row.block] = Rights(frozenset(row.actions), row.scope)
    return rights


def blocks_payload() -> list[dict[str, object]]:
    """Описание блоков для конструктора: что можно включать."""
    return [
        {
            "key": block.key,
            "title": block.title,
            "group": block.group,
            "scoped": block.scoped,
            "actions": [{"key": action.key, "title": action.title} for action in block.actions],
        }
        for block in BLOCKS
    ]


def levels_payload(db: Session) -> list[dict[str, object]]:
    """Шесть уровней с их текущими правами."""
    return [
        {
            "key": role,
            "title": ROLE_TITLES[role],
            "description": LEVEL_DESCRIPTIONS.get(role, ""),
            "rights": {
                block: {"actions": sorted(rights.actions), "scope": rights.scope}
                for block, rights in level_rights(db, role).items()
            },
        }
        for role in ROLES
    ]


def save_level(
    db: Session, admin: User, role: str, rights: dict[str, tuple[Iterable[str], str]]
) -> dict[str, object]:
    """Сохранить права уровня. Меняет только то, что отличается от значений по умолчанию."""
    if role not in ROLES:
        raise AccessError("Права администратора не редактируются", status_code=403)

    changes: list[dict[str, object]] = []
    for block_key, (actions_raw, scope) in rights.items():
        block = BLOCK_BY_KEY.get(block_key)
        if block is None:
            raise AccessError(f"Неизвестный блок прав: {block_key}")
        known = {action.key for action in block.actions}
        actions = list(dict.fromkeys(str(action) for action in actions_raw))
        unknown = [action for action in actions if action not in known]
        if unknown:
            raise AccessError(f"Неизвестное действие: {', '.join(unknown)}")
        if scope not in ("own", "all"):
            raise AccessError("Охват: «свои» или «все»")
        if not block.scoped and scope != "all":
            raise AccessError(f"Блок «{block.title}» не бывает «только свои»")
        if "view" in known and "view" not in actions and actions:
            raise AccessError(
                f"«{block.title}»: без права смотреть остальные действия бессмысленны"
            )

    before = level_rights(db, role)
    for block_key, (actions_raw, scope) in rights.items():
        chosen = frozenset(str(action) for action in actions_raw)
        default = defaults_for(role).get(block_key)
        current = before.get(block_key)
        # Блок, которого у уровня нет по умолчанию, не храним пустым: пустая
        # запись ничего не разрешает и только засоряет таблицу настроек.
        if default is None and not chosen:
            db.execute(
                delete(RolePermission).where(
                    RolePermission.role == role, RolePermission.block == block_key
                )
            )
            if current is not None:
                changes.append(
                    {
                        "block": block_key,
                        "before": sorted(current.actions),
                        "after": [],
                        "scope_before": current.scope,
                        "scope_after": scope,
                    }
                )
            continue
        if default == Rights(chosen, scope):
            db.execute(
                delete(RolePermission).where(
                    RolePermission.role == role, RolePermission.block == block_key
                )
            )
        else:
            row = db.get(RolePermission, (role, block_key))
            if row is None:
                db.add(
                    RolePermission(
                        role=role,
                        block=block_key,
                        actions=sorted(chosen),
                        scope=scope,
                        updated_by_id=admin.id,
                    )
                )
            else:
                row.actions = sorted(chosen)
                row.scope = scope
                row.updated_by_id = admin.id
        if current is None or current.actions != chosen or current.scope != scope:
            changes.append(
                {
                    "block": block_key,
                    "before": sorted(current.actions) if current else [],
                    "after": sorted(chosen),
                    "scope_before": current.scope if current else "all",
                    "scope_after": scope,
                }
            )

    if changes:
        audit_service.record(
            db,
            actor=admin,
            action="access.changed",
            summary=f"Изменены права уровня «{ROLE_TITLES[role]}»: блоков {len(changes)}",
            entity_label=ROLE_TITLES[role],
            payload={"level": role, "changes": changes},
        )
    db.commit()
    return {
        "key": role,
        "title": ROLE_TITLES[role],
        "description": LEVEL_DESCRIPTIONS.get(role, ""),
        "rights": {
            block: {"actions": sorted(rights.actions), "scope": rights.scope}
            for block, rights in level_rights(db, role).items()
        },
    }


def defaults_snapshot(role: str) -> dict[str, Rights]:
    """Стартовая матрица уровня — для сброса и тестов."""
    return dict(DEFAULTS.get(role, {}))
