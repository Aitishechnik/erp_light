"""Таск-трекер коммерческого отдела: задачи, этапы, отчёты и файлы.

Правила — в ``docs/data-contract-tasks.md``:

* ставит задачи коммерческий и исполнительный директора, исполняют менеджеры
  по продажам, ассистент отдела продаж и коммерческий директор (если поставил ГД);
* задача принимается автоматически: исполнитель не подтверждает её, а сразу
  получает служебное сообщение;
* этапы идут по порядку и не пересекаются, этап закрывается только промежуточным
  отчётом исполнителя;
* финальный отчёт закрывает задачу, постановщик получает сообщение об отчётах;
* файлы живут на диске, в базе — только описание; просрочка не хранится.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import ROOT_DIR
from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_SALES_ASSISTANT,
    ROLE_SALES_MANAGER,
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
    TaskDependency,
    TaskReport,
    TaskReportFile,
    TaskStep,
)
from app.schemas.tasks import (
    TaskActionsOut,
    TaskAssigneeOut,
    TaskCreate,
    TaskDependencyIn,
    TaskDependencyOut,
    TaskDetailOut,
    TaskLastReportOut,
    TaskOut,
    TaskReportFileOut,
    TaskReportIn,
    TaskReportOut,
    TaskRescheduleIn,
    TaskStatusIn,
    TaskStepIn,
    TaskStepOut,
    TaskStepUpdate,
    TaskUpdate,
)
from app.services import audit_service

# Кто ставит задачи: коммерческий отдел во главе с исполнительным директором.
TASK_CREATOR_ROLES = (ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR)

# Кто видит все задачи отдела: коммерческий и исполнительный директора.
TASK_OVERSEER_ROLES = (ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR)

# Кому можно ставить задачу — зависит от того, кто ставит.
ASSIGNABLE_BY: dict[str, tuple[str, ...]] = {
    ROLE_COMMERCIAL_DIRECTOR: (ROLE_SALES_MANAGER, ROLE_SALES_ASSISTANT),
    ROLE_EXECUTIVE_DIRECTOR: (
        ROLE_SALES_MANAGER,
        ROLE_SALES_ASSISTANT,
        ROLE_COMMERCIAL_DIRECTOR,
    ),
}

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


def _is_overseer(user: User) -> bool:
    return user.role in TASK_OVERSEER_ROLES


def _is_participant(user: User, task: Task) -> bool:
    return user.id in (task.assignee_id, task.created_by_id)


def _can_view(user: User, task: Task) -> bool:
    return _is_overseer(user) or _is_participant(user, task)


def _require_view(user: User, task: Task) -> None:
    if not _can_view(user, task):
        raise TaskError("Задача вам недоступна", status_code=403)


def _require_manage(user: User, task: Task) -> None:
    """Менять задачу может постановщик и исполнительный директор."""
    if user.id != task.created_by_id and user.role != ROLE_EXECUTIVE_DIRECTOR:
        raise TaskError(
            "Менять задачу может постановщик или исполнительный директор", status_code=403
        )


def _require_creator(user: User) -> None:
    if user.role not in TASK_CREATOR_ROLES:
        raise TaskError("Задачи ставит коммерческий или исполнительный директор", status_code=403)


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


def _step_order(task: Task, skip_id: uuid.UUID | None = None) -> list[TaskStep]:
    """Этапы по датам: порядок задаёт календарь, а не порядок добавления."""
    return sorted(
        (step for step in task.steps if step.id != skip_id),
        key=lambda row: (row.start_date, row.position, str(row.id)),
    )


def _check_step_overlap(
    task: Task, start: date, due: date, *, skip_id: uuid.UUID | None = None
) -> None:
    """Этапы не пересекаются, но могут стоять в любом свободном месте срока."""
    for step in _step_order(task, skip_id):
        if start <= step.due_date and due >= step.start_date:
            raise TaskError(
                f"Этап пересекается с этапом «{step.title}» "
                f"({step.start_date:%d.%m.%Y} — {step.due_date:%d.%m.%Y}): "
                "выберите другие даты",
                status_code=422,
            )


def _renumber(task: Task) -> None:
    """Порядковый номер этапа — его место на календаре."""
    ordered = sorted(task.steps, key=lambda row: (row.start_date, row.position, str(row.id)))
    for index, step in enumerate(ordered):
        step.position = index


def _load(db: Session, task_id: uuid.UUID) -> Task:
    task = db.execute(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.steps))
        .options(selectinload(Task.reports).selectinload(TaskReport.files))
        .options(selectinload(Task.dependencies).joinedload(TaskDependency.depends_on))
        .options(selectinload(Task.dependencies).joinedload(TaskDependency.step))
    ).scalar_one_or_none()
    if task is None:
        raise TaskError("Задача не найдена", status_code=404)
    return task


def _assignee(db: Session, assignee_id: uuid.UUID | None, author: User) -> User:
    if assignee_id is None:
        raise TaskError("Выберите исполнителя задачи", status_code=422)
    person = db.get(User, assignee_id)
    if person is None or not person.is_active:
        raise TaskError("Исполнитель не найден или отключён", status_code=422)
    allowed = ASSIGNABLE_BY.get(author.role, ())
    if person.role not in allowed:
        titles = ", ".join(ROLE_TITLES.get(role, role) for role in allowed)
        raise TaskError(f"Эту задачу может исполнять: {titles}", status_code=422)
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


def _overdue(task: Task, due: date) -> tuple[bool, int]:
    if task.status in CLOSED_TASK_STATUSES:
        return False, 0
    today = _today()
    if due >= today:
        return False, 0
    return True, (today - due).days


def _effective_dates(task: Task, blocked: bool) -> tuple[date, date, int]:
    """Пока задача ждёт мастера, её старт привязан к окну мастера.

    Начало = сегодня, но не раньше старта мастера и не позже его окончания:
    мастер ещё не начался — задача стоит на дне его старта; мастер в работе —
    задача едет вместе с сегодняшним днём; мастер просрочен — задача ждёт на
    последнем дне мастера. Окончание сдвигается на ту же величину.
    Возвращает начало, окончание и сдвиг в днях относительно плана.
    """
    start, due = task.start_date, task.due_date
    if not blocked:
        return start, due, 0
    masters = [
        dep.depends_on
        for dep in task.dependencies
        if not _dep_satisfied(dep) and dep.depends_on is not None
    ]
    if not masters:
        target = _today()
    else:
        # Ориентир — мастер с самым поздним окончанием: начало не раньше его
        # старта, но и не позже его окончания (дальше задача ждёт на месте).
        anchor = max(masters, key=lambda master: master.due_date)
        target = min(max(_today(), anchor.start_date), anchor.due_date)
    shift = (target - start).days
    return target, due + timedelta(days=shift), shift


def _dep_satisfied(dep: TaskDependency) -> bool:
    """Задача-предшественник закрыта или её этап закрыт отчётом."""
    if dep.depends_on_step_id is not None:
        return bool(dep.step is not None and dep.step.is_done)
    return dep.depends_on is not None and dep.depends_on.status == "done"


def _dep_label(dep: TaskDependency) -> str:
    title = dep.depends_on.title if dep.depends_on else "задача"
    if dep.step is not None:
        return f"этап «{dep.step.title}» задачи «{title}»"
    return f"задача «{title}»"


def _dependency_out(dep: TaskDependency) -> TaskDependencyOut:
    return TaskDependencyOut(
        id=dep.id,
        task_id=dep.depends_on_task_id,
        task_title=dep.depends_on.title if dep.depends_on else "",
        step_id=dep.depends_on_step_id,
        step_title=dep.step.title if dep.step is not None else None,
        satisfied=_dep_satisfied(dep),
        label=_dep_label(dep),
    )


def _blocked_by(task: Task) -> list[str]:
    return [_dep_label(dep) for dep in task.dependencies if not _dep_satisfied(dep)]


def _freeze_start(db: Session, user: User, dependent: Task, *, target: date | None = None) -> None:
    """Разблокировали задачу — фиксируем её старт в плане.

    Без ``target`` берём сегодняшний день (мастер закрыт). При снятии
    зависимости передаём дату, на которой задача остановилась.
    """
    if dependent.status in CLOSED_TASK_STATUSES or _blocked_by(dependent):
        return
    if target is None:
        target = _today()
    shift = (target - dependent.start_date).days
    if shift == 0:
        return
    dependent.start_date = dependent.start_date + timedelta(days=shift)
    dependent.due_date = dependent.due_date + timedelta(days=shift)
    for step in dependent.steps:
        if step.is_done:
            continue
        step.start_date = step.start_date + timedelta(days=shift)
        step.due_date = step.due_date + timedelta(days=shift)
    _renumber(dependent)
    dependent.updated_at = _now()
    _record(
        db,
        user,
        "task.updated",
        dependent,
        f"Задача «{dependent.title}» разблокирована: старт "
        f"{dependent.start_date:%d.%m.%Y} — {dependent.due_date:%d.%m.%Y}",
        audience=_audience(dependent.assignee),
    )


def _unfreeze_dependents(db: Session, user: User, master: Task) -> None:
    """Мастер завершён: зависимые задачи фиксируют сегодняшний старт."""
    ids = db.execute(
        select(TaskDependency.task_id).where(TaskDependency.depends_on_task_id == master.id)
    ).scalars()
    for dependent_id in set(ids):
        _freeze_start(db, user, _load(db, dependent_id))


def _step_reported(task: Task, step: TaskStep) -> bool:
    return any(report.step_id == step.id for report in task.reports)


def _progress(task: Task) -> int:
    """Шкала выполнения: доля закрытых этапов, иначе — процент последнего отчёта.

    Значение всегда выводится из отчётов и этапов, а не берётся из поля в базе:
    иначе задача без единого отчёта могла бы показывать чужой процент.
    """
    if task.status == "done":
        return 100
    if task.steps:
        closed = sum(1 for step in task.steps if step.is_done)
        return round(closed / len(task.steps) * 100)
    reports = _reports(task)
    return reports[-1].progress if reports else 0


def _base(task: Task) -> dict[str, Any]:
    blocked_by = _blocked_by(task)
    start_date, due_date, shift = _effective_dates(task, bool(blocked_by))
    is_overdue, days = _overdue(task, due_date)
    reports = _reports(task)
    today = _today()
    closed = task.status in CLOSED_TASK_STATUSES
    steps: list[TaskStepOut] = []
    for step in sorted(task.steps, key=lambda row: (row.start_date, row.position)):
        has_report = _step_reported(task, step)
        steps.append(
            TaskStepOut(
                id=step.id,
                title=step.title,
                start_date=step.start_date + timedelta(days=shift),
                due_date=step.due_date + timedelta(days=shift),
                is_done=step.is_done,
                position=step.position,
                has_report=has_report,
                needs_report=not has_report
                and not step.is_done
                and step.due_date < today
                and not closed,
            )
        )
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "priority_title": TASK_PRIORITY_TITLES.get(task.priority, task.priority),
        "status": task.status,
        "status_title": TASK_STATUS_TITLES.get(task.status, task.status),
        "progress": _progress(task),
        "start_date": start_date,
        "due_date": due_date,
        "assignee_id": task.assignee_id,
        "assignee_name": task.assignee.full_name if task.assignee else "",
        "created_by_id": task.created_by_id,
        "created_by_name": task.created_by.full_name if task.created_by else "",
        "closed_at": task.closed_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "is_overdue": is_overdue,
        "days_overdue": days,
        "steps": steps,
        "is_blocked": bool(blocked_by),
        "dynamic_start": bool(blocked_by) and shift != 0,
        "blocked_by": blocked_by,
        "reports_count": len(reports),
        "files_count": sum(len(report.files) for report in reports),
        "last_report": _last_report(task),
    }


def _to_out(task: Task) -> TaskOut:
    return TaskOut(**_base(task))


def _actions(user: User, task: Task) -> TaskActionsOut:
    """Что можно делать с задачей — по этому экран рисует кнопки."""
    manage = user.id == task.created_by_id or user.role == ROLE_EXECUTIVE_DIRECTOR
    closed = task.status in CLOSED_TASK_STATUSES
    return TaskActionsOut(
        can_edit=manage and not closed,
        can_change_status=(manage or user.id == task.assignee_id) and not closed,
        can_report=user.id == task.assignee_id and not closed,
        can_delete=manage and not task.reports,
        can_reopen=manage and closed,
    )


def _to_detail(task: Task, user: User) -> TaskDetailOut:
    step_titles = {step.id: step.title for step in task.steps}
    reports = [
        TaskReportOut(
            id=report.id,
            kind=report.kind,
            kind_title=REPORT_KIND_TITLES.get(report.kind, report.kind),
            step_id=report.step_id,
            step_title=step_titles.get(report.step_id) if report.step_id else None,
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
    return TaskDetailOut(
        **_base(task),
        reports=reports,
        dependencies=[_dependency_out(dep) for dep in task.dependencies],
        actions=_actions(user, task),
    )


def _record(
    db: Session,
    user: User,
    action: str,
    task: Task,
    summary: str,
    *,
    audience: list[str],
    payload: dict[str, Any] | None = None,
    task_link: bool = True,
) -> None:
    """Событие журнала; ``audience`` делает его ещё и служебным сообщением."""
    audit_service.record(
        db,
        actor=user,
        action=action,
        summary=summary,
        entity_id=task.id if task_link else None,
        entity_label=task.title,
        payload=payload,
        audience=audience,
    )


def _audience(*users: User | None, roles: tuple[str, ...] = ()) -> list[str]:
    """Адресаты сообщения: сотрудники без повторов плюс роли."""
    markers: list[str] = []
    for person in users:
        if person is None:
            continue
        marker = audit_service.user_marker(person)
        if marker not in markers:
            markers.append(marker)
    markers.extend(role for role in roles if role not in markers)
    return markers


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
    """Директора видят все задачи отдела, остальные — только свои."""
    statement = (
        select(Task)
        .options(selectinload(Task.steps))
        .options(selectinload(Task.reports).selectinload(TaskReport.files))
        .options(selectinload(Task.dependencies).joinedload(TaskDependency.depends_on))
        .options(selectinload(Task.dependencies).joinedload(TaskDependency.step))
    )
    if mine or not _is_overseer(user):
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


def list_assignees(db: Session, user: User) -> list[TaskAssigneeOut]:
    """Кого можно назначить: список зависит от роли постановщика."""
    _require_creator(user)
    roles = ASSIGNABLE_BY.get(user.role, ())
    users = db.execute(
        select(User).where(User.is_active.is_(True), User.role.in_(roles)).order_by(User.full_name)
    )
    return [
        TaskAssigneeOut(
            id=person.id,
            full_name=person.full_name,
            role_title=ROLE_TITLES.get(person.role, person.role),
        )
        for person in users.scalars().all()
    ]


def create_task(db: Session, user: User, payload: TaskCreate) -> TaskDetailOut:
    """Поставить задачу: она сразу в работе, исполнитель не подтверждает её."""
    _require_creator(user)
    _check_dates(payload.start_date, payload.due_date)
    _check_priority(payload.priority)
    assignee = _assignee(db, payload.assignee_id, user)
    task = Task(
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        priority=payload.priority,
        status="in_progress",
        progress=0,
        start_date=payload.start_date,
        due_date=payload.due_date,
        assignee_id=assignee.id,
        created_by_id=user.id,
    )
    for position, step in enumerate(payload.steps):
        _check_step_in_task(task, step.start_date, step.due_date)
        _check_step_overlap(task, step.start_date, step.due_date)
        task.steps.append(
            TaskStep(
                title=step.title.strip(),
                start_date=step.start_date,
                due_date=step.due_date,
                is_done=False,
                position=position,
            )
        )
    _renumber(task)
    db.add(task)
    db.flush()
    _record(
        db,
        user,
        "task.created",
        task,
        f"Поставлена задача «{task.title}» — срок до {task.due_date:%d.%m.%Y}",
        audience=_audience(assignee),
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
    previous_assignee = task.assignee
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
        if any(step.start_date < start or step.due_date > due for step in task.steps):
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
    _record(
        db,
        user,
        "task.updated",
        task,
        f"Изменена задача «{task.title}»: {', '.join(changes)}",
        audience=_audience(task.assignee, previous_assignee),
    )
    db.commit()
    return _to_detail(_load(db, task_id), user)


_STATUS_FLOW: dict[str, tuple[str, ...]] = {
    "start": ("new",),
    "resume": ("postponed",),
    "postpone": ("new", "in_progress"),
    "cancel": ("new", "in_progress", "postponed"),
    "reopen": ("done", "cancelled"),
}

_STATUS_ACTION_TITLES = {
    "start": "взята в работу",
    "resume": "возобновлена",
    "postpone": "отложена",
    "cancel": "отозвана",
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
    if action in ("reopen", "cancel"):
        _require_manage(user, task)
    elif (
        user.id not in (task.assignee_id, task.created_by_id)
        and user.role != ROLE_EXECUTIVE_DIRECTOR
    ):
        raise TaskError("Действие доступно участникам задачи", status_code=403)
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
    summary = f"Задача «{task.title}» {_STATUS_ACTION_TITLES[action]}"
    if action == "reopen":
        _record(
            db,
            user,
            "task.reopened",
            task,
            summary,
            audience=_audience(task.assignee, roles=(ROLE_EXECUTIVE_DIRECTOR,)),
        )
    else:
        _record(
            db,
            user,
            "task.status_changed",
            task,
            summary,
            audience=_audience(task.assignee),
            payload={"status": task.status},
        )
    db.commit()
    return _to_detail(_load(db, task_id), user)


def reschedule_task(
    db: Session, user: User, task_id: uuid.UUID, payload: TaskRescheduleIn
) -> TaskDetailOut:
    """Перенести задачу: новые сроки; этапы при желании сдвигаются вместе с ней."""
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    _check_dates(payload.start_date, payload.due_date)
    delta = (payload.start_date - task.start_date).days
    if payload.move_steps and delta:
        # Закрытые этапы — история: их даты не переписываем при переносе.
        for step in task.steps:
            if step.is_done:
                continue
            step.start_date = step.start_date + timedelta(days=delta)
            step.due_date = step.due_date + timedelta(days=delta)
    outside = [
        step
        for step in task.steps
        if not step.is_done
        and (step.start_date < payload.start_date or step.due_date > payload.due_date)
    ]
    if outside:
        first = outside[0]
        raise TaskError(
            "Новые сроки не вмещают этапы: "
            f"«{first.title}» идёт {first.start_date:%d.%m.%Y} — {first.due_date:%d.%m.%Y}. "
            "Включите перенос этапов или поправьте их даты",
            status_code=422,
        )
    task.start_date = payload.start_date
    task.due_date = payload.due_date
    _renumber(task)
    task.updated_at = _now()
    _record(
        db,
        user,
        "task.updated",
        task,
        f"Задача «{task.title}» перенесена: {task.start_date:%d.%m.%Y} — "
        f"{task.due_date:%d.%m.%Y}",
        audience=_audience(task.assignee),
    )
    db.commit()
    return _to_detail(_load(db, task_id), user)


def add_step(db: Session, user: User, task_id: uuid.UUID, payload: TaskStepIn) -> TaskDetailOut:
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    position = max((step.position for step in task.steps), default=-1) + 1
    _check_step_in_task(task, payload.start_date, payload.due_date)
    _check_step_overlap(task, payload.start_date, payload.due_date)
    task.steps.append(
        TaskStep(
            title=payload.title.strip(),
            start_date=payload.start_date,
            due_date=payload.due_date,
            is_done=False,
            position=position,
        )
    )
    _renumber(task)
    task.updated_at = _now()
    summary = f"В задаче «{task.title}» новый этап «{payload.title.strip()}»"
    _record(
        db,
        user,
        "task.updated",
        task,
        summary,
        audience=_audience(task.assignee),
    )
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
    """Этап правит постановщик; закрывается этап только отчётом исполнителя."""
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    step = _find_step(task, step_id)
    start = payload.start_date or step.start_date
    due = payload.due_date or step.due_date
    if payload.title is not None:
        step.title = payload.title.strip()
    if payload.start_date is not None or payload.due_date is not None:
        _check_step_in_task(task, start, due)
        _check_step_overlap(task, start, due, skip_id=step.id)
        step.start_date = start
        step.due_date = due
        _renumber(task)
    task.updated_at = _now()
    summary = f"Изменён этап «{step.title}» задачи «{task.title}»"
    _record(db, user, "task.updated", task, summary, audience=_audience(task.assignee))
    db.commit()
    return _to_detail(_load(db, task_id), user)


def delete_step(db: Session, user: User, task_id: uuid.UUID, step_id: uuid.UUID) -> TaskDetailOut:
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    step = _find_step(task, step_id)
    if _step_reported(task, step):
        raise TaskError(
            "По этапу уже есть отчёт — этап не удаляем, чтобы не терять историю",
            status_code=409,
        )
    task.steps.remove(step)
    _renumber(task)
    task.updated_at = _now()
    summary = f"Удалён этап «{step.title}» задачи «{task.title}»"
    _record(db, user, "task.updated", task, summary, audience=_audience(task.assignee))
    db.commit()
    return _to_detail(_load(db, task_id), user)


def _depends_on(db: Session, start_id: uuid.UUID, target_id: uuid.UUID) -> bool:
    """Есть ли путь по зависимостям от start_id к target_id (для проверки циклов)."""
    seen: set[uuid.UUID] = set()
    stack = [start_id]
    while stack:
        current = stack.pop()
        if current == target_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        rows = db.execute(
            select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == current)
        ).scalars()
        stack.extend(rows)
    return False


def add_dependency(
    db: Session, user: User, task_id: uuid.UUID, payload: TaskDependencyIn
) -> TaskDetailOut:
    """Поставить зависимость: задача ждёт завершения другой задачи или её этапа."""
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    if payload.depends_on_task_id == task.id:
        raise TaskError("Задача не может зависеть от себя", status_code=422)
    prerequisite = _load(db, payload.depends_on_task_id)
    _require_view(user, prerequisite)
    step: TaskStep | None = None
    if payload.depends_on_step_id is not None:
        step = _find_step(prerequisite, payload.depends_on_step_id)
    if _depends_on(db, prerequisite.id, task.id):
        raise TaskError(
            "Так получится замкнутый круг зависимостей: выберите другую задачу",
            status_code=422,
        )
    for dep in task.dependencies:
        if dep.depends_on_task_id == prerequisite.id and dep.depends_on_step_id == (
            step.id if step else None
        ):
            raise TaskError("Такая зависимость уже есть", status_code=409)
    db.add(
        TaskDependency(
            task_id=task.id,
            depends_on_task_id=prerequisite.id,
            depends_on_step_id=step.id if step else None,
            created_by_id=user.id,
        )
    )
    task.updated_at = _now()
    _record(
        db,
        user,
        "task.updated",
        task,
        f"Задача «{task.title}» теперь ждёт "
        + (
            f"этап «{step.title}» задачи «{prerequisite.title}»"
            if step
            else f"задачу «{prerequisite.title}»"
        ),
        audience=_audience(task.assignee),
    )
    db.commit()
    db.expire_all()
    return _to_detail(_load(db, task_id), user)


def delete_dependency(
    db: Session, user: User, task_id: uuid.UUID, dependency_id: uuid.UUID
) -> TaskDetailOut:
    task = _load(db, task_id)
    _require_view(user, task)
    _require_manage(user, task)
    dependency = next((row for row in task.dependencies if row.id == dependency_id), None)
    if dependency is None:
        raise TaskError("Зависимость не найдена", status_code=404)
    label = _dep_label(dependency)
    # Фиксируем ту дату, на которой задача стояла под зависимостью.
    frozen_start, _, _ = _effective_dates(task, True)
    task.dependencies.remove(dependency)
    db.flush()
    _freeze_start(db, user, task, target=frozen_start)
    task.updated_at = _now()
    _record(
        db,
        user,
        "task.updated",
        task,
        f"Задача «{task.title}» больше не ждёт {label}",
        audience=_audience(task.assignee),
    )
    db.commit()
    db.expire_all()
    return _to_detail(_load(db, task_id), user)


def add_report(db: Session, user: User, task_id: uuid.UUID, payload: TaskReportIn) -> TaskDetailOut:
    """Отчёт присылает исполнитель: промежуточный закрывает этап, финальный — задачу."""
    task = _load(db, task_id)
    _require_view(user, task)
    if user.id != task.assignee_id:
        raise TaskError("Отчёт по задаче присылает исполнитель", status_code=403)
    blocked = _blocked_by(task)
    if blocked:
        raise TaskError("Задача ждёт завершения: " + "; ".join(blocked), status_code=409)
    if payload.kind not in REPORT_KINDS:
        raise TaskError("Отчёт: промежуточный или финальный", status_code=422)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — сначала верните её в работу", status_code=409)
    text = payload.text.strip()
    if len(text) < 3:
        raise TaskError("Опишите, что сделано: не короче 3 символов", status_code=422)
    step: TaskStep | None = None
    if payload.step_id is not None:
        if payload.kind != "interim":
            raise TaskError("Финальный отчёт — по задаче целиком, без этапа", status_code=422)
        step = _find_step(task, payload.step_id)
        if step.is_done or _step_reported(task, step):
            raise TaskError("Этап уже закрыт отчётом", status_code=409)

    if payload.kind == "final":
        report = TaskReport(author_id=user.id, kind="final", progress=100, text=text)
        task.progress = 100
        task.status = "done"
        task.closed_at = _now()
    else:
        report = TaskReport(
            author_id=user.id,
            kind="interim",
            step_id=step.id if step else None,
            progress=payload.progress,
            text=text,
        )
        if step is not None:
            step.is_done = True
            # Готовность задачи по этапам — доля закрытых, а не процент из отчёта.
            total = len(task.steps) or 1
            closed = sum(1 for row in task.steps if row.is_done)
            task.progress = round(closed / total * 100)
            report.progress = task.progress
        else:
            task.progress = payload.progress
        if task.status in ("new", "postponed"):
            task.status = "in_progress"
    task.updated_at = _now()
    task.reports.append(report)
    db.flush()
    _unfreeze_dependents(db, user, task)

    creator = task.created_by
    if payload.kind == "final":
        summary = f"Задача «{task.title}» выполнена — финальный отчёт"
        _record(
            db,
            user,
            "task.done",
            task,
            summary,
            audience=_audience(creator, roles=(ROLE_EXECUTIVE_DIRECTOR,)),
        )
    else:
        if step is not None:
            summary = (
                f"Этап «{step.title}» задачи «{task.title}» закрыт — "
                f"промежуточный отчёт, готовность {payload.progress} %"
            )
        else:
            summary = f"Отчёт по задаче «{task.title}»: готовность {payload.progress} %"
        _record(
            db,
            user,
            "task.report_added",
            task,
            summary,
            audience=_audience(creator),
            payload={"progress": payload.progress, "step_id": str(step.id) if step else None},
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
    if (
        user.id not in (task.assignee_id, task.created_by_id)
        and user.role != ROLE_EXECUTIVE_DIRECTOR
    ):
        raise TaskError("Приложить файл может исполнитель или постановщик", status_code=403)
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
    file = db.get(TaskReportFile, file_id)
    if file is None or file.task_id != task.id:
        raise TaskError("Файл не найден", status_code=404)
    path = ATTACHMENTS_DIR / str(task.id) / file.stored_name
    if not path.is_file():
        raise TaskError("Файл потерян на диске", status_code=404)
    return path, file.original_name, file.content_type


def delete_report_file(db: Session, user: User, task_id: uuid.UUID, file_id: uuid.UUID) -> None:
    task = _load(db, task_id)
    _require_view(user, task)
    file = db.get(TaskReportFile, file_id)
    if file is None or file.task_id != task.id:
        raise TaskError("Файл не найден", status_code=404)
    report = db.get(TaskReport, file.report_id)
    allowed = (
        user.role == ROLE_EXECUTIVE_DIRECTOR
        or user.id == file.uploaded_by_id
        or (report is not None and report.author_id == user.id)
    )
    if not allowed:
        raise TaskError("Удалить файл может автор отчёта или директор", status_code=403)
    if task.status in CLOSED_TASK_STATUSES:
        raise TaskError("Задача закрыта — файлы менять нельзя", status_code=409)
    (ATTACHMENTS_DIR / str(task.id) / file.stored_name).unlink(missing_ok=True)
    db.delete(file)
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
    _record(
        db,
        user,
        "task.deleted",
        task,
        f"Задача «{task.title}» удалена",
        audience=_audience(task.assignee, roles=(ROLE_EXECUTIVE_DIRECTOR,)),
        task_link=False,
    )
    db.delete(task)
    db.commit()
