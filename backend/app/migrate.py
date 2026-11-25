"""Миграции схемы: SQL-файлы из backend/migrations по порядку.

Первая миграция появилась, когда схема перестала быть одноразовой: на рабочем
стенде уже есть сотрудники, планы и клиенты, и ``create_all`` не умеет
добавлять колонки в существующие таблицы.

Каждый файл применяется один раз; имя файла пишется в ``schema_migrations``.
Запуск: ``make db-migrate`` (или ``python -m app.migrate``).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _ensure_registry(conn: Connection) -> None:
    conn.execute(
        text(
            "create table if not exists schema_migrations ("
            "name text primary key, "
            "applied_at timestamptz not null default now())"
        )
    )


def _applied(conn: Connection) -> set[str]:
    rows = conn.execute(text("select name from schema_migrations")).scalars().all()
    return set(rows)


def apply_pending(conn: Connection) -> list[str]:
    """Применяет новые файлы и возвращает их имена."""
    _ensure_registry(conn)
    applied = _applied(conn)
    done: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        conn.exec_driver_sql(path.read_text(encoding="utf-8"))
        conn.execute(
            text("insert into schema_migrations (name) values (:name)"),
            {"name": path.name},
        )
        done.append(path.name)
    return done


def main() -> None:
    with engine.begin() as conn:
        done = apply_pending(conn)
    if done:
        print("Применены миграции: " + ", ".join(done))
    else:
        print("Схема актуальна: новых миграций нет")


if __name__ == "__main__":
    main()
