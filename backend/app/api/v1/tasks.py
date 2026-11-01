"""API таск-трекера: задачи, этапы, отчёты и файлы к отчётам."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.schemas.tasks import (
    TaskAssigneeOut,
    TaskCreate,
    TaskDetailOut,
    TaskOut,
    TaskReportFileOut,
    TaskReportIn,
    TaskStatusIn,
    TaskStepIn,
    TaskStepUpdate,
    TaskUpdate,
)
from app.services import task_service as service
from app.services.task_service import TaskError

router = APIRouter(tags=["tasks"])


def _fail(exc: TaskError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/tasks/assignees", response_model=list[TaskAssigneeOut])
def list_assignees(user: CurrentUser, db: DbSession) -> list[TaskAssigneeOut]:
    """Сотрудники, которых можно назначить исполнителем."""
    return service.list_assignees(db)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    user: CurrentUser,
    db: DbSession,
    mine: bool = Query(default=False, description="Только задачи, где я участник"),
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None, description="green | yellow | red"),
    overdue: bool = Query(default=False, description="Только просроченные"),
    assignee_id: Annotated[uuid.UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query(description="Окончание не раньше даты")] = None,
    date_to: Annotated[date | None, Query(description="Начало не позже даты")] = None,
) -> list[TaskOut]:
    """Список задач для Ганта."""
    try:
        return service.list_tasks(
            db,
            user,
            mine=mine,
            status=status_filter,
            priority=priority,
            overdue=overdue,
            assignee_id=assignee_id,
            date_from=date_from,
            date_to=date_to,
        )
    except TaskError as exc:
        raise _fail(exc) from exc


@router.post("/tasks", response_model=TaskDetailOut, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, user: CurrentUser, db: DbSession) -> TaskDetailOut:
    try:
        return service.create_task(db, user, payload)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
def get_task(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> TaskDetailOut:
    try:
        return service.get_task(db, user, task_id)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.patch("/tasks/{task_id}", response_model=TaskDetailOut)
def update_task(
    task_id: uuid.UUID, payload: TaskUpdate, user: CurrentUser, db: DbSession
) -> TaskDetailOut:
    try:
        return service.update_task(db, user, task_id, payload)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    try:
        service.delete_task(db, user, task_id)
    except TaskError as exc:
        raise _fail(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tasks/{task_id}/status", response_model=TaskDetailOut)
def change_status(
    task_id: uuid.UUID, payload: TaskStatusIn, user: CurrentUser, db: DbSession
) -> TaskDetailOut:
    """Взять в работу, отложить, отменить или вернуть в работу."""
    try:
        return service.change_status(db, user, task_id, payload)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.post("/tasks/{task_id}/steps", response_model=TaskDetailOut)
def add_step(
    task_id: uuid.UUID, payload: TaskStepIn, user: CurrentUser, db: DbSession
) -> TaskDetailOut:
    try:
        return service.add_step(db, user, task_id, payload)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.patch("/tasks/{task_id}/steps/{step_id}", response_model=TaskDetailOut)
def update_step(
    task_id: uuid.UUID,
    step_id: uuid.UUID,
    payload: TaskStepUpdate,
    user: CurrentUser,
    db: DbSession,
) -> TaskDetailOut:
    try:
        return service.update_step(db, user, task_id, step_id, payload)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.delete("/tasks/{task_id}/steps/{step_id}", response_model=TaskDetailOut)
def delete_step(
    task_id: uuid.UUID, step_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> TaskDetailOut:
    try:
        return service.delete_step(db, user, task_id, step_id)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.post("/tasks/{task_id}/reports", response_model=TaskDetailOut)
def add_report(
    task_id: uuid.UUID, payload: TaskReportIn, user: CurrentUser, db: DbSession
) -> TaskDetailOut:
    """Промежуточный отчёт двигает процент, финальный закрывает задачу."""
    try:
        return service.add_report(db, user, task_id, payload)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.post("/tasks/{task_id}/reports/{report_id}/files", response_model=TaskReportFileOut)
def upload_report_file(
    task_id: uuid.UUID,
    report_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="Файл отчёта: pdf, xlsx, docx, картинка, zip")],
) -> TaskReportFileOut:
    try:
        return service.upload_report_file(db, user, task_id, report_id, file)
    except TaskError as exc:
        raise _fail(exc) from exc


@router.get("/tasks/{task_id}/reports/{report_id}/files/{file_id}")
def download_report_file(
    task_id: uuid.UUID,
    report_id: uuid.UUID,
    file_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> FileResponse:
    try:
        path, name, content_type = service.report_file_path(db, user, task_id, file_id)
    except TaskError as exc:
        raise _fail(exc) from exc
    return FileResponse(path, filename=name, media_type=content_type or "application/octet-stream")


@router.delete(
    "/tasks/{task_id}/reports/{report_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_report_file(
    task_id: uuid.UUID,
    report_id: uuid.UUID,
    file_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        service.delete_report_file(db, user, task_id, file_id)
    except TaskError as exc:
        raise _fail(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
