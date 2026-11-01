"""Таск-трекер: правила задач, этапов, отчётов и файлов.

Правила собраны здесь, а не в API: экран и тесты должны видеть одно и то же.
Ключевые решения — в ``docs/data-contract-tasks.md``:

* видит задачу постановщик, исполнитель и три директора;
* финальный отчёт закрывает задачу, промежуточный двигает процент;
* файлы живут на диске, в базе — только описание;
* просрочка не хранится, а считается от срока окончания.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import ROOT_DIR
from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_TITLES,
    User,
)
from app.models.tasks import (
    CLOSED_TASK_STATUSES,
    FILE_EXTENSIONS,
    FILE_MAX_BYTES,
    FILES_PER_REPORT,
    REPORT_KIND_TITLES,
    REPORT_KINDS,
    TASK_PRIORITIES,
    TASK_PRIORITY_TITLES,
    TASK_STATUS_TITLES,
    Task,
    TaskReport,
    TaskReportFile,
    TaskStep,
)
from app.schemas.tasks import (
    TaskActionsOut,
    TaskAssigneeOut,
    TaskCreate,
    TaskDetailOut,
    TaskLastReportOut,
    TaskOut,
    TaskReportFileOut,
    TaskReportIn,
    TaskReportOut,
    TaskStatusIn,
    TaskStepIn,
    TaskStepOut,
    TaskStepUpdate,
    TaskUpdate,
)
from app.services import audit_service

# Кто видит и правит задачи сверх участников.
DIRECTOR_ROLES = (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
)

# Куда складываем файлы отчётов. Каталог вне git (data/ в .gitignore).
ATTACHMENTS_DIR = ROOT_DIR / "data" / "attachments"


class TaskError(Exception):
    """Нарушение бизнес-правила задачи; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _today() -> date:
    return date.today()


def _now() -> datetime:
    return datetime.now(UTC)


def _is_director(user: User) -> bool:
    return user.role in DIRECTOR_ROLES


def _is_participant(user: User, task: Task) -> bool:
    return user.id in (task.assignee_id, task.created_by_id)


def _can_view(user: User, task: Task) -> bool:
    return _is_director(user) or _is_participant(user, task)


def _require_view(user: User, task: Task) -> None:
    if not _can_view(user, task):
        raise TaskError("Задача вам недоступна", status_code=403)


def _require_manage(user: User, task: Task) -> None:
    """Менять сроки, приоритет, исполнителя и описание может постановщик и директор."""
    if user.id != task.created_by_id and not _is_director(user):
        raise TaskError("Менять задачу может постановщик или директор", status_code=403)


def _require_participant(user: User, task: Task) -> None:
    if not _is_participant(user, task) and not _is_director(user):
        raise TaskError("Действие доступно участникам задачи", status_code=403)


def _check_dates(start: date, due: date, *, what: str = "Сроки задачи") -> None:
    if due < start:
        raise TaskError(f"{what}: дата окончания раньше даты начала", status_code=422)


def _check_priority(priority: str) -> None:
    if priority not in TASK_PRIORITIES:
        raise TaskError("Приоритет: зелёный, жёлтый или красный", status_code=422)


def _check_step_in_task(task: Task, start: date, due: date) -> None:
    _check_dates(start, due, what="Сроки этапа")
    if start < task.start_date or due > task.due_date:
        raise TaskError(
            "Этап выходит за сроки задачи: расширьте сроки задачи или сузьте этап",
            status_code=422,
        )


def _load(db: Session, task_id: uuid.UUID) -> Task:
    task = db.execute(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.steps))
        .options(selectinload(Task.reports).selectinload(TaskReport.files))
    ).scalar_one_or_none()
    if task is None:
        raise TaskError("Задача не найдена", status_code=404)
    return task


def _assignee(db: Session, assignee_id: uuid.UUID | None, author: User) -> User:
    if assignee_id is None:
        return author
    person = db.get(User, assignee_id)
    if person is None or not person.is_active:
        raise TaskError("Исполнитель не найден или отключён", status_code=422)
    return person


def _reports(task: Task) -> list[TaskReport]:
    return sorted(task.reports, key=lambda row: (row.created_at, str(row.id)))


def _last_report(task: Task) -> TaskLastReportOut | None:
    reports = _reports(task)
    if not reports:
        return None
    last = reports[-1]
    return TaskLastReportOut(
        created_at=last.created_at,
        kind=last.kind,
        kind_title=REPORT_KIND_TITLES.get(last.kind, last.kind),
        author_name=last.author.full_name if last.author else "",
        text=last.text,
    )


def _overdue(task: Task) -> tuple[bool, int]:
    if task.status in CLOSED_TASK_STATUSES:
        return False, 0
    today = _today()
    if task.due_date >= today:
        return False, 0
    return True, (today - task.due_date).days


def _base(task: Task) -> dict[str, Any]:
    is_overdue, days = _overdue(task)
    reports = _reports(task)
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "priority_title": TASK_PRIORITY_TITLES.get(task.priority, task.priority),
        "status": task.status,
        "status_title": TASK_STATUS_TITLES.get(task.status, task.status),
        "progress": task.progress,
        "start_date": task.start_date,
        "due_date": task.due_date,
        "assignee_id": task.assignee_id,
        "assignee_name": task.assignee.full_name if task.assignee else "",
        "created_by_id": task.created_by_id,
        "created_by_name": task.created_by.full_name if task.created_by else "",
        "closed_at": task.closed_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "is_overdue": is_overdue,
        "days_overdue": days,
        "steps": [
            TaskStepOut(
                id=step.id,
                title=step.title,
                start_date=step.start_date,
                due_date=step.due_date,
                is_done=step.is_done,
                position=step.position,
            )
            for step in sorted(task.steps, key=lambda row: (row.position, str(row.id)))
        ],
        "reports_count": len(reports),
        "files_count": sum(len(report.files) for report in reports),
        "last_report": _last_report(task),
    }


def _to_out(task: Task) -> TaskOut:
    return TaskOut(**_base(task))


def _actions(user: User, task: Task) -> TaskActionsOut:
    """Что можно делать с задачей — по этому экран рисует кнопки."""
    manage = user.id == task.created_by_id or _is_director(user)
    participant = _is_participant(user, task) or _is_director(user)
    closed = task.status in CLOSED_TASK_STATUSES
    return TaskActionsOut(
        can_edit=manage and not closed,
        can_change_status=participant and not closed,
        can_report=participant and not closed,
        can_delete=manage and not task.reports,
        can_reopen=manage and closed,
    )


def _to_detail(task: Task, user: User) -> TaskDetailOut:
    reports = [
        TaskReportOut(
            id=report.id,
            kind=report.kind,
            kind_title=REPORT_KIND_TITLES.get(report.kind, report.kind),
            progress=report.progress,
            text=report.text,
            author_id=report.author_id,
            author_name=report.author.full_name if report.author else "",
            created_at=report.created_at,
            files=[
                TaskReportFileOut(
                    id=file.id,
                    original_name=file.original_name,
                    size_bytes=file.size_bytes,
                    content_type=file.content_type,
                    uploaded_by_name=file.uploaded_by.full_name if file.uploaded_by else "",
                    created_at=file.created_at,
                )
                for file in sorted(report.files, key=lambda row: (row.created_at, str(row.id)))
            ],
        )
        for report in _reports(task)
    ]
    return TaskDetailOut(**_base(task), reports=reports, actions=_actions(user, task))


def _audit(
    db: Session,
    user: User,
    action: str,
    task: Task,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> None:
    audit_service.record(
        db,
        actor=user,
        action=action,
        summary=summary,
        entity_id=task.id,
        entity_label=task.title,
        payload=payload,
    )


def list_tasks(
    db: Session,
    user: User,
    *,
    mine: bool = False,
    status: str | None = None,
    priority: str | None = None,
    overdue: bool = False,
    assignee_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[TaskOut]:
    """Список задач: директора видят все, остальные — только свои."""
    statement = (
        select(Task)
        .options(selectinload(Task.steps))
        .options(selectinload(Task.reports).selectinload(TaskReport.files))
    )
    if mine or not _is_director(user):
        statement = statement.where((Task.assignee_id == user.id) | (Task.created_by_id == user.id))
    if status:
        statement = statement.where(Task.status == status)
    if priority:
        if priority not in TASK_PRIORITIES:
            raise TaskError("Приоритет: зелёный, жёлтый или красный", status_code=422)
        statement = statement.where(Task.priority == priority)
    if assignee_id:
        statement = statement.where(Task.assignee_id == assignee_id)
    if date_from:
        statement = statement.where(Task.due_date >= date_from)
    if date_to:
        statement = statement.where(Task.start_date <= date_to)
    tasks = db.execute(statement).scalars().all()
    result = [_to_out(task) for task in tasks]
    if overdue:
        result = [row for row in result if row.is_overdue]
    result.sort(key=lambda row: (row.start_date, row.due_date, row.title))
    return result


def get_task(db: Session, user: User, task_id: uuid.UUID) -> TaskDetailOut:
    task = _load(db, task_id)
    _require_view(user, task)
    return _to_detail(task, user)


def list_assignees(db: Session) -> list[TaskAssigneeOut]:
    """Кого можно назначить исполнителем: все активные сотрудники."""
    users = db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
    return [
        TaskAssigneeOut(
            id=user.id,
            full_name=user.full_name,
            role_title=ROLE_TITLES.get(user.role, user.role),
        )
        for user in users.scalars().all()
    ]


def create_task(db: Session, user: User, payload: TaskCreate) -> TaskDetailOut:
    """Поставить задачу: по умолчанию на себя, сроки и этапы проверяются сразу."""
    _check_dates(payload.start_date, payload.due_date)
    _check_priority(payload.priority)
    assignee = _assignee(db, payload.assignee_id, user)
    task = Task(
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        priority=payload.priority,
        status="new",
        progress=0,
        start_date=payload.start_date,
        due_date=payload.due_date,
        assignee_id=assignee.id,
        created_by_id=user.id,
    )
    for index, step in enumerate(payload.steps):
        _check_dates(step.start_date, step.due_date, what="Сроки этапа")
        if step.start_date < payload.start_date or step.due_date > payload.due_date:
            raise TaskError(
                "Этап выходит за сроки задачи: расширьте сроки задачи или сузьте этап",
                status_code=422,
            )
        task.steps.append(
            TaskStep(
                title=step.title.strip(),
                start_date=step.start_date,
                due_date=step.due_date,
                is_done=False,
                position=index,
            )
        )
    db.add(task)
    db.flush()
    _audit(
        db,
        user,
        "task.created",
        task,
        f"Поставлена задача «{task.title}» на {assignee.full_name}",
    )
    db.commit()
    return _to_detail(_load(db, task.id), user)


def update_task(db: Session, user: User, task_id: uuid.UUID, payload: TaskUpdate) -> TaskDetailOut:
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    changes: list[str] = []
    if payload.title is not None:
        task.title = payload.title.strip()
        changes.append("название")
    if payload.description is not None:
        task.description = payload.description.strip() or None
        changes.append("описание")
    if payload.priority is not None:
        _check_priority(payload.priority)
        if payload.priority != task.priority:
            task.priority = payload.priority
            changes.append("приоритет")
    if payload.assignee_id is not None and payload.assignee_id != task.assignee_id:
        person = _assignee(db, payload.assignee_id, user)
        task.assignee_id = person.id
        changes.append("исполнитель")
    start = payload.start_date or task.start_date
    due = payload.due_date or task.due_date
    if start != task.start_date or due != task.due_date:
        _check_dates(start, due)
        overdue_steps = [
            step for step in task.steps if step.start_date < start or step.due_date > due
        ]
        if overdue_steps:
            raise TaskError(
                "Новые сроки задачи не вмещают этапы: сначала поправьте этапы",
                status_code=422,
            )
        task.start_date = start
        task.due_date = due
        changes.append("сроки")
    if not changes:
        return _to_detail(task, user)
    task.updated_at = _now()
    _audit(
        db,
        user,
        "task.updated",
        task,
        f"Изменена задача «{task.title}»: {', '.join(changes)}",
        payload={"changes": changes},
    )
    db.commit()
    return _to_detail(_load(db, task_id), user)


_STATUS_FLOW: dict[str, tuple[str, ...]] = {
    "start": ("new", "postponed"),
    "resume": ("postponed",),
    "postpone": ("new", "in_progress"),
    "cancel": ("new", "in_progress", "postponed"),
    "reopen": ("done", "cancelled"),
}

_STATUS_ACTION_TITLES = {
    "start": "взята в работу",
    "resume": "возвращена в работу",
    "postpone": "отложена",
    "cancel": "отменена",
    "reopen": "возвращена в работу",
}


def change_status(
    db: Session, user: User, task_id: uuid.UUID, payload: TaskStatusIn
) -> TaskDetailOut:
    """Смена статуса: закрывает только финальный отчёт, а не эта ручка."""
    task = _load(db, task_id)
    _require_view(user, task)
    action = payload.action
    if action not in _STATUS_FLOW:
        raise TaskError("Неизвестное действие со статусом", status_code=422)
    if action == "reopen":
        _require_manage(user, task)
    else:
        _require_participant(user, task)
    allowed_from = _STATUS_FLOW[action]
    if task.status not in allowed_from:
        raise TaskError(
            f"В статусе «{TASK_STATUS_TITLES.get(task.status, task.status)}» действие недоступно",
            status_code=409,
        )
    if action == "cancel":
        task.status = "cancelled"
        task.closed_at = _now()
    elif action == "postpone":
        task.status = "postponed"
    elif action == "reopen":
        task.status = "in_progress"
        task.closed_at = None
        if task.progress >= 100:
            task.progress = 90
    else:
        task.status = "in_progress"
    task.updated_at = _now()
    if action == "reopen":
        _audit(db, user, "task.reopened", task, f"Задача «{task.title}» возвращена в работу")
    else:
        _audit(
            db,
            user,
            "task.status_changed",
            task,
            f"Задача «{task.title}» {_STATUS_ACTION_TITLES[action]}",
            payload={"status": task.status},
        )
    db.commit()
    return _to_detail(_load(db, task_id), user)


def add_step(db: Session, user: User, task_id: uuid.UUID, payload: TaskStepIn) -> TaskDetailOut:
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    _check_step_in_task(task, payload.start_date, payload.due_date)
    position = max((step.position for step in task.steps), default=-1) + 1
    task.steps.append(
        TaskStep(
            title=payload.title.strip(),
            start_date=payload.start_date,
            due_date=payload.due_date,
            is_done=False,
            position=position,
        )
    )
    task.updated_at = _now()
    db.commit()
    return _to_detail(_load(db, task_id), user)


def _find_step(task: Task, step_id: uuid.UUID) -> TaskStep:
    for step in task.steps:
        if step.id == step_id:
            return step
    raise TaskError("Этап не найден", status_code=404)


def update_step(
    db: Session,
    user: User,
    task_id: uuid.UUID,
    step_id: uuid.UUID,
    payload: TaskStepUpdate,
) -> TaskDetailOut:
    """Этап правит постановщик; галочку «выполнен» может ставить и исполнитель."""
    task = _load(db, task_id)
    _require_view(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    step = _find_step(task, step_id)
    only_done = (
        payload.title is None
        and payload.start_date is None
        and payload.due_date is None
        and payload.is_done is not None
    )
    if not only_done:
        _require_manage(user, task)
    else:
        _require_participant(user, task)
    start = payload.start_date or step.start_date
    due = payload.due_date or step.due_date
    if payload.title is not None:
        step.title = payload.title.strip()
    if payload.start_date is not None or payload.due_date is not None:
        _check_step_in_task(task, start, due)
        step.start_date = start
        step.due_date = due
    if payload.is_done is not None:
        step.is_done = payload.is_done
    task.updated_at = _now()
    db.commit()
    return _to_detail(_load(db, task_id), user)


def delete_step(db: Session, user: User, task_id: uuid.UUID, step_id: uuid.UUID) -> TaskDetailOut:
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    step = _find_step(task, step_id)
    task.steps.remove(step)
    task.updated_at = _now()
    db.commit()
    return _to_detail(_load(db, task_id), user)


def add_report(db: Session, user: User, task_id: uuid.UUID, payload: TaskReportIn) -> TaskDetailOut:
    """Промежуточный отчёт двигает процент, финальный закрывает задачу."""
    task = _load(db, task_id)
    _require_view(user, task)
    _require_participant(user, task)
    if payload.kind not in REPORT_KINDS:
        raise TaskError("Отчёт: промежуточный или финальный", status_code=422)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    text = payload.text.strip()
    if len(text) < 3:
        raise TaskError("Опишите, что сделано: не короче 3 символов", status_code=422)
    if payload.kind == "final":
        report = TaskReport(author_id=user.id, kind="final", progress=100, text=text)
        task.progress = 100
        task.status = "done"
        task.closed_at = _now()
    else:
        if payload.progress > 100:
            raise TaskError("Готовность: от 0 до 100 %", status_code=422)
        report = TaskReport(
            author_id=user.id,
            kind="interim",
            progress=payload.progress,
            text=text,
        )
        task.progress = payload.progress
        if task.status in ("new", "postponed"):
            task.status = "in_progress"
    task.updated_at = _now()
    task.reports.append(report)
    if payload.kind == "final":
        _audit(
            db,
            user,
            "task.done",
            task,
            f"Задача «{task.title}» выполнена — финальный отчёт",
        )
    else:
        _audit(
            db,
            user,
            "task.report_added",
            task,
            f"Отчёт по задаче «{task.title}»: готовность {payload.progress} %",
            payload={"progress": payload.progress},
        )
    db.commit()
    return _to_detail(_load(db, task_id), user)


def _report_of(task: Task, report_id: uuid.UUID) -> TaskReport:
    for report in task.reports:
        if report.id == report_id:
            return report
    raise TaskError("Отчёт не найден", status_code=404)


def upload_report_file(
    db: Session,
    user: User,
    task_id: uuid.UUID,
    report_id: uuid.UUID,
    upload: UploadFile,
) -> TaskReportFileOut:
    """Прикрепить файл к отчёту: проверяем права, размер, тип и количество."""
    task = _load(db, task_id)
    _require_view(user, task)
    _require_participant(user, task)
    report = _report_of(task, report_id)
    if len(report.files) >= FILES_PER_REPORT:
        raise TaskError(f"К отчёту можно приложить не больше {FILES_PER_REPORT} файлов")
    name = Path(upload.filename or "файл").name
    extension = Path(name).suffix.lower()
    if extension not in FILE_EXTENSIONS:
        raise TaskError(
            "Такой файл приложить нельзя: pdf, xlsx, docx, картинки или zip",
            status_code=415,
        )
    content = upload.file.read(FILE_MAX_BYTES + 1)
    if len(content) > FILE_MAX_BYTES:
        raise TaskError("Файл больше 10 МБ", status_code=413)
    if not content:
        raise TaskError("Файл пустой", status_code=422)
    folder = ATTACHMENTS_DIR / str(task.id)
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    (folder / stored_name).write_bytes(content)
    record = TaskReportFile(
        task_id=task.id,
        original_name=name[:255],
        stored_name=stored_name,
        size_bytes=len(content),
        content_type=upload.content_type or "application/octet-stream",
        uploaded_by_id=user.id,
    )
    report.files.append(record)
    db.flush()
    db.commit()
    db.refresh(record)
    return TaskReportFileOut(
        id=record.id,
        original_name=record.original_name,
        size_bytes=record.size_bytes,
        content_type=record.content_type,
        uploaded_by_name=user.full_name,
        created_at=record.created_at,
    )


def report_file_path(
    db: Session, user: User, task_id: uuid.UUID, file_id: uuid.UUID
) -> tuple[Path, str, str]:
    """Путь к файлу и имя для скачивания; права проверяются по задаче."""
    task = _load(db, task_id)
    _require_view(user, task)
    record = db.get(TaskReportFile, file_id)
    if record is None or record.task_id != task.id:
        raise TaskError("Файл не найден", status_code=404)
    path = ATTACHMENTS_DIR / str(task.id) / record.stored_name
    if not path.is_file():
        raise TaskError("Файл потерян на диске", status_code=404)
    return path, record.original_name, record.content_type


def delete_report_file(db: Session, user: User, task_id: uuid.UUID, file_id: uuid.UUID) -> None:
    task = _load(db, task_id)
    _require_view(user, task)
    record = db.get(TaskReportFile, file_id)
    if record is None or record.task_id != task.id:
        raise TaskError("Файл не найден", status_code=404)
    report_author = db.get(TaskReport, record.report_id)
    allowed = (
        _is_director(user)
        or user.id == record.uploaded_by_id
        or (report_author is not None and report_author.author_id == user.id)
    )
    if not allowed:
        raise TaskError("Удалить файл может автор отчёта или директор", status_code=403)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — файлы менять нельзя", status_code=409)
    (ATTACHMENTS_DIR / str(task.id) / record.stored_name).unlink(missing_ok=True)
    db.delete(record)
    db.commit()


def delete_task(db: Session, user: User, task_id: uuid.UUID) -> None:
    """Удалить задачу можно, только пока по ней нет отчётов."""
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.reports:
        raise TaskError(
            "По задаче уже есть отчёты — её можно отменить, но не удалить",
            status_code=409,
        )
    folder = ATTACHMENTS_DIR / str(task.id)
    if folder.is_dir():
        for file in folder.iterdir():
            file.unlink(missing_ok=True)
        folder.rmdir()
    _audit(db, user, "task.deleted", task, f"Задача «{task.title}» удалена")
    db.delete(task)
    db.commit()
