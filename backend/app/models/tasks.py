"""Таск-трекер: задачи, этапы, отчёты менеджера и файлы к отчётам.

Задача — одна строка Ганта верхнего уровня; этапы дают второй уровень.
Промежуточный отчёт двигает процент готовности, финальный закрывает задачу.
Отчёты не редактируются: это история. Просрочка не хранится — считается от
даты окончания при чтении.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.auth import User

# Приоритет: зелёный — можно сдвинуть, жёлтый — обычный, красный — срочно.
TASK_PRIORITIES = ("green", "yellow", "red")

TASK_PRIORITY_TITLES = {
    "green": "Низкий",
    "yellow": "Обычный",
    "red": "Высокий",
}

# Статусы: новая → в работе → выполнена; отложена и отменена — боковые.
TASK_STATUSES = ("new", "in_progress", "postponed", "done", "cancelled")

TASK_STATUS_TITLES = {
    "new": "Новая",
    "in_progress": "В работе",
    "postponed": "Отложена",
    "done": "Выполнена",
    "cancelled": "Отменена",
}

# Закрытые задачи правкам не подлежат, кроме возврата в работу.
CLOSED_TASK_STATUSES = ("done", "cancelled")

REPORT_KINDS = ("interim", "final")

REPORT_KIND_TITLES = {
    "interim": "Промежуточный",
    "final": "Финальный",
}

# Файлы отчёта: что принимаем и сколько.
FILE_EXTENSIONS = (".pdf", ".xlsx", ".xls", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".zip")
FILE_MAX_BYTES = 10 * 1024 * 1024
FILES_PER_REPORT = 10


class Task(Base):
    """Задача сотрудника: сроки, приоритет, исполнитель и постановщик."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="yellow")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    assignee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    assignee: Mapped[User] = relationship(foreign_keys=[assignee_id], lazy="joined")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="joined")
    steps: Mapped[list[TaskStep]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStep.position",
    )
    reports: Mapped[list[TaskReport]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskReport.created_at",
    )


class TaskStep(Base):
    """Этап задачи: строка второго уровня на Ганте."""

    __tablename__ = "task_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    task: Mapped[Task] = relationship(back_populates="steps")


class TaskReport(Base):
    """Отчёт менеджера по задаче: промежуточный или финальный."""

    __tablename__ = "task_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    task: Mapped[Task] = relationship(back_populates="reports")
    author: Mapped[User] = relationship(lazy="joined")
    files: Mapped[list[TaskReportFile]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="TaskReportFile.created_at",
    )


class TaskReportFile(Base):
    """Файл, приложенный к отчёту. Сам файл лежит на диске, здесь — описание."""

    __tablename__ = "task_report_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("task_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    report: Mapped[TaskReport] = relationship(back_populates="files")
    uploaded_by: Mapped[User] = relationship(lazy="joined")
