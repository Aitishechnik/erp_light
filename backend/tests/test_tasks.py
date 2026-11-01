"""Таск-трекер: права, статусы, отчёты и файлы по контракту docs/data-contract-tasks.md."""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.services import task_service

Link = Callable[[str], None]
AttachmentDir = Path


@pytest.fixture(autouse=True)
def attachments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Файлы отчётов пишем во временный каталог, а не в data/ проекта."""
    folder = tmp_path / "attachments"
    monkeypatch.setattr(task_service, "ATTACHMENTS_DIR", folder)
    return folder


def day(offset: int = 0) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def make_task(client: TestClient, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Подготовить отчёт по продажам",
        "description": "Свести цифры за квартал",
        "priority": "yellow",
        "start_date": day(-3),
        "due_date": day(4),
    }
    payload.update(extra)
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_task_sees_only_participants(client: TestClient, login: Link) -> None:
    """Менеджер 2 не видит чужую задачу, директор видит все."""
    login("sales")
    task = make_task(client)
    login("sales2")
    assert client.get("/api/v1/tasks").json() == []
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 403
    login("commercial")
    rows = client.get("/api/v1/tasks").json()
    assert [row["id"] for row in rows] == [task["id"]]


def test_assignee_sees_task_and_can_start(client: TestClient, login: Link) -> None:
    """Исполнитель видит задачу и может взять её в работу."""
    login("sales")
    assignees = client.get("/api/v1/tasks/assignees").json()
    sales2 = next(row for row in assignees if row["full_name"].startswith("Менеджер по продажам 2"))
    task = make_task(client, assignee_id=sales2["id"])
    login("sales2")
    assert client.get("/api/v1/tasks").json()[0]["id"] == task["id"]
    started = client.post(f"/api/v1/tasks/{task['id']}/status", json={"action": "start"})
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_progress"
    postponed = client.post(f"/api/v1/tasks/{task['id']}/status", json={"action": "postpone"})
    assert postponed.json()["status"] == "postponed"


def test_only_creator_changes_task(client: TestClient, login: Link) -> None:
    login("sales")
    task = make_task(client)
    login("sales2")
    denied = client.patch(f"/api/v1/tasks/{task['id']}", json={"priority": "red"})
    assert denied.status_code == 403
    login("sales")
    changed = client.patch(f"/api/v1/tasks/{task['id']}", json={"priority": "red"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["priority_title"] == "Высокий"


def test_step_must_fit_task_dates(client: TestClient, login: Link) -> None:
    login("sales")
    response = client.post(
        "/api/v1/tasks",
        json={
            "title": "Задача с этапом",
            "start_date": day(0),
            "due_date": day(5),
            "steps": [{"title": "Этап", "start_date": day(-1), "due_date": day(2)}],
        },
    )
    assert response.status_code == 422, response.text
    assert "выходит за сроки" in response.json()["detail"]

    task = make_task(client)
    bad = client.post(
        f"/api/v1/tasks/{task['id']}/steps",
        json={"title": "Поздний этап", "start_date": day(3), "due_date": day(9)},
    )
    assert bad.status_code == 422


def test_interim_report_moves_progress_final_closes(
    client: TestClient, login: Link, db_session: Session
) -> None:
    login("sales")
    task = make_task(client)
    interim = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Собрал половину данных", "progress": 40},
    )
    assert interim.status_code == 200, interim.text
    body = interim.json()
    assert body["progress"] == 40
    assert body["status"] == "in_progress"
    assert body["reports"][-1]["kind_title"] == "Промежуточный"

    final = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "final", "text": "Отчёт готов и отправлен", "progress": 100},
    )
    assert final.status_code == 200, final.text
    done = final.json()
    assert done["status"] == "done"
    assert done["progress"] == 100
    assert done["closed_at"] is not None
    assert done["actions"]["can_report"] is False

    events = db_session.execute(
        select(AuditEvent).where(AuditEvent.entity_kind == "task")
    ).scalars()
    actions = {event.action for event in events}
    assert {"task.created", "task.report_added", "task.done"} <= actions


def test_closed_task_cannot_get_report(client: TestClient, login: Link) -> None:
    login("sales")
    task = make_task(client)
    client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "final", "text": "Готово", "progress": 100},
    )
    again = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Ещё немного", "progress": 50},
    )
    assert again.status_code == 409
    reopened = client.post(f"/api/v1/tasks/{task['id']}/status", json={"action": "reopen"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress"


def test_outsider_cannot_report(client: TestClient, login: Link) -> None:
    login("sales")
    task = make_task(client)
    login("sales2")
    denied = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Влез без прав", "progress": 10},
    )
    assert denied.status_code == 403


def test_delete_with_reports_forbidden(client: TestClient, login: Link) -> None:
    login("sales")
    task = make_task(client)
    client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Промежуточный отчёт", "progress": 20},
    )
    denied = client.delete(f"/api/v1/tasks/{task['id']}")
    assert denied.status_code == 409
    assert "отменить" in denied.json()["detail"]

    other = make_task(client, title="Задача без отчётов")
    assert client.delete(f"/api/v1/tasks/{other['id']}").status_code == 204
    assert client.get(f"/api/v1/tasks/{other['id']}").status_code == 404


def test_overdue_flag(client: TestClient, login: Link) -> None:
    login("sales")
    task = make_task(client, start_date=day(-10), due_date=day(-2))
    row = client.get("/api/v1/tasks").json()[0]
    assert row["is_overdue"] is True
    assert row["days_overdue"] == 2
    assert task["is_overdue"] is True


def test_report_file_upload_and_download(
    client: TestClient, login: Link, attachments: Path
) -> None:
    login("sales")
    task = make_task(client)
    report = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Прикладываю смету", "progress": 30},
    ).json()
    report_id = report["reports"][-1]["id"]
    url = f"/api/v1/tasks/{task['id']}/reports/{report_id}/files"
    uploaded = client.post(url, files={"file": ("смета.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["id"]
    assert uploaded.json()["original_name"] == "смета.pdf"
    assert list((attachments / task["id"]).iterdir())

    downloaded = client.get(f"{url}/{file_id}")
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-1.4 test"
    disposition = unquote(downloaded.headers["content-disposition"])
    assert "смета.pdf" in disposition

    login("sales2")
    assert client.get(f"{url}/{file_id}").status_code == 403


def test_report_file_limits(
    client: TestClient, login: Link, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("sales")
    task = make_task(client)
    report = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Проверка лимитов", "progress": 10},
    ).json()
    url = f"/api/v1/tasks/{task['id']}/reports/{report['reports'][-1]['id']}/files"
    bad_type = client.post(url, files={"file": ("вирус.exe", b"MZ", "application/octet-stream")})
    assert bad_type.status_code == 415

    monkeypatch.setattr(task_service, "FILE_MAX_BYTES", 16)
    too_big = client.post(url, files={"file": ("смета.pdf", b"x" * 17, "application/pdf")})
    assert too_big.status_code == 413
