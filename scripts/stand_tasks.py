"""Стенд таск-трекера: задачи коммерческого отдела с этапами и отчётами.

Запуск после ``make db-bootstrap`` и ``make seed-users``:

    backend/.venv/bin/python scripts/stand_tasks.py          # добавить, если задач нет
    RESET=1 backend/.venv/bin/python scripts/stand_tasks.py  # пересобрать стенд

Ставит задачи коммерческий директор (менеджерам и ассистенту) и исполнительный
директор (коммерческому директору). Даты считаются от сегодняшнего дня: на стенде
всегда есть задача в работе, просроченная и закрытая.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import app.models  # noqa: E402,F401 — регистрирует таблицы в Base.metadata
from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models.auth import User  # noqa: E402
from app.models.tasks import Task, TaskReport, TaskReportFile, TaskStep  # noqa: E402


def _user(db: Session, login: str) -> User:
    user = db.execute(select(User).where(User.login == login)).scalar_one_or_none()
    if user is None:
        raise SystemExit(f"Нет пользователя {login}: сначала `make seed-users`")
    return user


def _reset(db: Session) -> None:
    """Убрать прежний стенд: отчёты, этапы и задачи (файлы — отдельно, на диске)."""
    db.execute(delete(TaskReportFile))
    db.execute(delete(TaskReport))
    db.execute(delete(TaskStep))
    db.execute(delete(Task))
    db.commit()


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if os.environ.get("RESET"):
            _reset(db)
        existing = db.execute(select(func.count()).select_from(Task)).scalar_one()
        if existing:
            print(f"В базе уже {existing} задач — добавьте RESET=1, чтобы пересобрать.")
            return

        sales = _user(db, "sales")
        sales2 = _user(db, "sales2")
        assistant = _user(db, "assistant")
        commercial = _user(db, "commercial")
        executive = _user(db, "executive")
        today = date.today()

        def moment(days_ago: int) -> datetime:
            return datetime.now(UTC) - timedelta(days=days_ago)

        def report(
            author: User, kind: str, progress: int, text: str, days_ago: int, step: TaskStep | None
        ) -> TaskReport:
            return TaskReport(
                author_id=author.id,
                kind=kind,
                progress=progress,
                text=text,
                step_id=step.id if step else None,
                created_at=moment(days_ago),
            )

        tasks: list[Task] = []

        # 1. Красная, в работе: первый этап уже закрыт отчётом, второй идёт.
        price = Task(
            title="Согласовать матрицу цен на ноябрь",
            description="Свести цены по 12 клиентам и отправить коммерческому директору.",
            priority="red",
            status="in_progress",
            progress=40,
            start_date=today - timedelta(days=6),
            due_date=today + timedelta(days=6),
            assignee_id=sales.id,
            created_by_id=commercial.id,
            created_at=moment(8),
            updated_at=moment(1),
        )
        step_done = TaskStep(
            title="Собрать цены за октябрь",
            start_date=today - timedelta(days=6),
            due_date=today - timedelta(days=3),
            is_done=True,
            position=0,
        )
        step_open = TaskStep(
            title="Согласовать скидки по ключевым клиентам",
            start_date=today - timedelta(days=2),
            due_date=today + timedelta(days=6),
            is_done=False,
            position=1,
        )
        price.steps.extend([step_done, step_open])
        price.reports.append(
            report(
                sales,
                "interim",
                40,
                "Собрал цены по десяти клиентам из двенадцати, осталось два крупных.",
                3,
                step_done,
            )
        )
        tasks.append(price)

        # 2. Жёлтая, в работе у ассистента: этап просрочен, отчёта ещё нет.
        catalog = Task(
            title="Обновить карточки клиентов в справочнике",
            description="Проверить ИНН, контакты и менеджера у активных покупателей.",
            priority="yellow",
            status="in_progress",
            progress=25,
            start_date=today - timedelta(days=12),
            due_date=today + timedelta(days=2),
            assignee_id=assistant.id,
            created_by_id=commercial.id,
            created_at=moment(12),
            updated_at=moment(5),
        )
        late_step = TaskStep(
            title="Сверить ИНН у десяти клиентов",
            start_date=today - timedelta(days=12),
            due_date=today - timedelta(days=2),
            is_done=False,
            position=0,
        )
        catalog.steps.append(late_step)
        catalog.reports.append(
            report(
                assistant,
                "interim",
                25,
                "Проверила четыре карточки, у одной расходится ИНН — уточняю.",
                5,
                None,
            )
        )
        tasks.append(catalog)

        # 3. Зелёная, отложена менеджером.
        tasks.append(
            Task(
                title="Подготовить план продаж на декабрь",
                description="Черновик плана по клиентам с учётом новых договоров.",
                priority="green",
                status="postponed",
                progress=0,
                start_date=today + timedelta(days=3),
                due_date=today + timedelta(days=18),
                assignee_id=sales2.id,
                created_by_id=commercial.id,
                created_at=moment(2),
                updated_at=moment(1),
            )
        )

        # 4. Просроченная красная — от исполнительного директора коммерческому.
        tasks.append(
            Task(
                title="Закрыть итоги октября",
                description="Свести план/факт и зафиксировать причины отклонений.",
                priority="red",
                status="in_progress",
                progress=30,
                start_date=today - timedelta(days=20),
                due_date=today - timedelta(days=4),
                assignee_id=commercial.id,
                created_by_id=executive.id,
                created_at=moment(20),
                updated_at=moment(3),
            )
        )

        # 5. Выполненная: финальный отчёт закрыл задачу.
        handbook = Task(
            title="Обновить регламент отдела продаж",
            description="Добавить раздел о работе с новыми клиентами и сроках ответа.",
            priority="yellow",
            status="done",
            progress=100,
            start_date=today - timedelta(days=14),
            due_date=today - timedelta(days=7),
            assignee_id=assistant.id,
            created_by_id=commercial.id,
            created_at=moment(14),
            updated_at=moment(7),
            closed_at=moment(7),
        )
        handbook.reports.append(
            report(
                assistant,
                "final",
                100,
                "Регламент обновлён: раздел про новых клиентов и срок ответа 4 часа.",
                7,
                None,
            )
        )
        tasks.append(handbook)

        db.add_all(tasks)
        db.commit()

    print("Готово: 5 задач коммерческого отдела, 3 этапа, 4 отчёта.")


if __name__ == "__main__":
    main()
