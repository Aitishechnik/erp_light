"""Стенд таск-трекера: пять демонстрационных задач с этапами и отчётами.

Запуск после ``make db-bootstrap`` и ``make seed-users``:

    backend/.venv/bin/python scripts/stand_tasks.py

Скрипт идемпотентен: если задачи уже есть, он ничего не делает. Даты считаются
от сегодняшнего дня, поэтому стенд всегда «живой» — есть просроченная задача и
задача с запасом по сроку.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import app.models  # noqa: E402,F401 — регистрирует таблицы в Base.metadata
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models.auth import User  # noqa: E402
from app.models.tasks import Task, TaskReport, TaskStep  # noqa: E402


def _user(db: Session, login: str) -> User:
    user = db.execute(select(User).where(User.login == login)).scalar_one_or_none()
    if user is None:
        raise SystemExit(f"Нет пользователя {login}: сначала `make seed-users`")
    return user


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        existing = db.execute(select(func.count()).select_from(Task)).scalar_one()
        if existing:
            print(f"В базе уже {existing} задач — стенд не меняю.")
            return

        sales = _user(db, "sales")
        import_manager = _user(db, "import")
        commercial = _user(db, "commercial")
        purchase = _user(db, "purchase")
        today = date.today()

        def moment(days_ago: int) -> datetime:
            return datetime.now(UTC) - timedelta(days=days_ago)

        tasks: list[Task] = []

        # 1. Красная, в работе, половина пути.
        price = Task(
            title="Согласовать матрицу цен на ноябрь",
            description="Свести цены по 12 клиентам и отправить коммерческому директору.",
            priority="red",
            status="in_progress",
            progress=40,
            start_date=today - timedelta(days=4),
            due_date=today + timedelta(days=5),
            assignee_id=sales.id,
            created_by_id=commercial.id,
            created_at=moment(6),
            updated_at=moment(1),
        )
        price.steps.extend(
            [
                TaskStep(
                    title="Собрать цены за октябрь",
                    start_date=today - timedelta(days=4),
                    due_date=today - timedelta(days=2),
                    is_done=True,
                    position=0,
                ),
                TaskStep(
                    title="Согласовать скидки по ключевым клиентам",
                    start_date=today - timedelta(days=1),
                    due_date=today + timedelta(days=3),
                    is_done=False,
                    position=1,
                ),
            ]
        )
        price.reports.append(
            TaskReport(
                author_id=sales.id,
                kind="interim",
                progress=40,
                text="Собрал цены по десяти клиентам из двенадцати, осталось два крупных.",
                created_at=moment(1),
            )
        )
        tasks.append(price)

        # 2. Жёлтая, новая, срок с запасом.
        tasks.append(
            Task(
                title="Подготовить план продаж на декабрь",
                description="Черновик плана по клиентам с учётом новых договоров.",
                priority="yellow",
                status="new",
                progress=0,
                start_date=today + timedelta(days=3),
                due_date=today + timedelta(days=18),
                assignee_id=sales.id,
                created_by_id=commercial.id,
                created_at=moment(2),
                updated_at=moment(2),
            )
        )

        # 3. Зелёная, в работе у импорта.
        customs = Task(
            title="Проверить поступления из Китая",
            description="Сверить даты, курсы и суммы по трём партиям.",
            priority="green",
            status="in_progress",
            progress=60,
            start_date=today - timedelta(days=9),
            due_date=today + timedelta(days=2),
            assignee_id=import_manager.id,
            created_by_id=import_manager.id,
            created_at=moment(9),
            updated_at=moment(1),
        )
        customs.steps.append(
            TaskStep(
                title="Сверить три партии с инвойсами",
                start_date=today - timedelta(days=9),
                due_date=today + timedelta(days=1),
                is_done=False,
                position=0,
            )
        )
        customs.reports.append(
            TaskReport(
                author_id=import_manager.id,
                kind="interim",
                progress=60,
                text="Две партии сошлись, по третьей жду курс ЦБ за дату оформления.",
                created_at=moment(1),
            )
        )
        tasks.append(customs)

        # 4. Просроченная красная, отложена.
        tasks.append(
            Task(
                title="Закрыть итоги октября",
                description="Свести план/факт и зафиксировать причины отклонений.",
                priority="red",
                status="postponed",
                progress=30,
                start_date=today - timedelta(days=20),
                due_date=today - timedelta(days=3),
                assignee_id=commercial.id,
                created_by_id=commercial.id,
                created_at=moment(20),
                updated_at=moment(2),
            )
        )

        # 5. Выполненная: закрыта финальным отчётом.
        countries = Task(
            title="Обновить справочник стран и сроки доставки",
            description="Добавить ОАЭ, поправить срок по Турции.",
            priority="yellow",
            status="done",
            progress=100,
            start_date=today - timedelta(days=14),
            due_date=today - timedelta(days=7),
            assignee_id=purchase.id,
            created_by_id=commercial.id,
            created_at=moment(14),
            updated_at=moment(7),
            closed_at=moment(7),
        )
        countries.reports.append(
            TaskReport(
                author_id=purchase.id,
                kind="final",
                progress=100,
                text="Справочник обновлён: ОАЭ — 40 дней, Турция — 21 день. Проверено на плане закупок.",
                created_at=moment(7),
            )
        )
        tasks.append(countries)

        db.add_all(tasks)
        db.commit()

    print("Готово: 5 задач, 3 этапа, 3 отчёта.")


if __name__ == "__main__":
    main()
