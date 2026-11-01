"""Схемы таск-трекера: задачи, этапы, отчёты и файлы."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class TaskStepIn(BaseModel):
    title: str = Field(min_length=1, max_length=255, description="Название этапа")
    start_date: date
    due_date: date


class TaskStepUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    start_date: date | None = None
    due_date: date | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255, description="Что нужно сделать")
    description: str | None = Field(default=None, max_length=4000)
    priority: str = Field(default="yellow", description="green | yellow | red")
    start_date: date
    due_date: date
    assignee_id: uuid.UUID | None = Field(
        default=None, description="Исполнитель; пусто — задача на себя"
    )
    steps: list[TaskStepIn] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    priority: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    assignee_id: uuid.UUID | None = None


class TaskStatusIn(BaseModel):
    action: str = Field(description="start | postpone | cancel | resume | reopen")


class TaskDependencyIn(BaseModel):
    depends_on_task_id: uuid.UUID
    depends_on_step_id: uuid.UUID | None = Field(
        default=None, description="Этап задачи-предшественника; пусто — вся задача"
    )


class TaskRescheduleIn(BaseModel):
    start_date: date
    due_date: date
    move_steps: bool = Field(
        default=True, description="Сдвинуть этапы на тот же срок, что и задачу"
    )


class TaskReportIn(BaseModel):
    kind: str = Field(description="interim — промежуточный, final — финальный")
    text: str = Field(min_length=3, max_length=4000, description="Что сделано / итог")
    progress: int = Field(default=100, ge=0, le=100, description="Готовность, %")
    step_id: uuid.UUID | None = Field(
        default=None, description="Этап, который закрывает отчёт; пусто — отчёт по задаче"
    )


class TaskDependencyOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    task_title: str
    step_id: uuid.UUID | None
    step_title: str | None
    satisfied: bool = Field(description="Предшественник уже завершён")
    label: str = Field(description="Что ждём: задача или её этап")


class TaskStepOut(BaseModel):
    id: uuid.UUID
    title: str
    start_date: date
    due_date: date
    is_done: bool
    position: int
    has_report: bool = Field(description="По этапу уже есть промежуточный отчёт")
    needs_report: bool = Field(description="Срок этапа наступил, а отчёта ещё нет")


class TaskReportFileOut(BaseModel):
    id: uuid.UUID
    original_name: str
    size_bytes: int
    content_type: str
    uploaded_by_name: str
    created_at: datetime


class TaskReportOut(BaseModel):
    id: uuid.UUID
    kind: str
    kind_title: str
    step_id: uuid.UUID | None
    step_title: str | None
    progress: int
    text: str
    author_id: uuid.UUID
    author_name: str
    created_at: datetime
    files: list[TaskReportFileOut]


class TaskLastReportOut(BaseModel):
    created_at: datetime
    kind: str
    kind_title: str
    author_name: str
    text: str


class TaskActionsOut(BaseModel):
    can_edit: bool
    can_change_status: bool
    can_report: bool
    can_delete: bool
    can_reopen: bool


class TaskAssigneeOut(BaseModel):
    id: uuid.UUID
    full_name: str
    role_title: str


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    priority: str
    priority_title: str
    status: str
    status_title: str
    progress: int
    start_date: date
    due_date: date
    assignee_id: uuid.UUID
    assignee_name: str
    created_by_id: uuid.UUID
    created_by_name: str
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_overdue: bool
    days_overdue: int
    steps: list[TaskStepOut]
    reports_count: int
    files_count: int
    last_report: TaskLastReportOut | None
    is_blocked: bool = Field(description="Ждёт завершения предшественника")
    dynamic_start: bool = Field(
        description="Старт сдвигается вперёд каждый день, пока предшественник не завершён"
    )
    blocked_by: list[str] = Field(description="Кого именно ждёт")


class TaskDetailOut(TaskOut):
    reports: list[TaskReportOut]
    dependencies: list[TaskDependencyOut]
    actions: TaskActionsOut
