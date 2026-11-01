"""Таск-трекер коммерческого отдела: права, этапы, отчёты, файлы и сообщения."""

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

SALES = "Менеджер по продажам (демо)"
SALES2 = "Менеджер по продажам 2 (демо)"
ASSISTANT = "Ассистент отдела продаж (демо)"
COMMERCIAL = "Коммерческий директор (демо)"


@pytest.fixture(autouse=True)
def attachments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Файлы отчётов пишем во временный каталог, а не в data/ проекта."""
    folder = tmp_path / "attachments"
    monkeypatch.setattr(task_service, "ATTACHMENTS_DIR", folder)
    return folder


def day(offset: int = 0) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def assignee_id(client: TestClient, full_name: str) -> str:
    response = client.get("/api/v1/tasks/assignees")
    assert response.status_code == 200, response.text
    person = next(row for row in response.json() if row["full_name"] == full_name)
    return str(person["id"])


def new_task(
    client: TestClient,
    login: Link,
    *,
    creator: str = "commercial",
    assignee: str = SALES,
    **extra: Any,
) -> dict[str, Any]:
    login(creator)
    payload: dict[str, Any] = {
        "title": "Согласовать цены с клиентом",
        "description": "Свести цены и отправить клиенту",
        "priority": "yellow",
        "start_date": day(-2),
        "due_date": day(5),
        "assignee_id": assignee_id(client, assignee),
    }
    payload.update(extra)
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_commercial_department_only(client: TestClient, login: Link) -> None:
    """Задачу ставит только коммерческий или исполнительный директор."""
    task = new_task(client, login)
    assert task["status"] == "in_progress"
    assert task["assignee_name"] == SALES

    # Менеджеры и ассистент задачу поставить не могут.
    login("commercial")
    sales_id = assignee_id(client, SALES)
    for login_name in ("sales", "sales2", "assistant"):
        login(login_name)
        denied = client.post(
            "/api/v1/tasks",
            json={
                "title": "Своя задача",
                "start_date": day(0),
                "due_date": day(3),
                "assignee_id": sales_id,
            },
        )
        assert denied.status_code == 403, (login_name, denied.text)

    # Закупки трекер не видят вовсе.
    login("purchase")
    assert client.get("/api/v1/tasks").json() == []
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 403


def test_visible_to_overseers_and_assignee(client: TestClient, login: Link) -> None:
    task = new_task(client, login)
    login("sales")
    assert [row["id"] for row in client.get("/api/v1/tasks").json()] == [task["id"]]
    login("sales2")
    assert client.get("/api/v1/tasks").json() == []
    login("commercial")
    assert [row["id"] for row in client.get("/api/v1/tasks").json()] == [task["id"]]
    login("executive")
    assert [row["id"] for row in client.get("/api/v1/tasks").json()] == [task["id"]]


def test_executive_can_assign_commercial(client: TestClient, login: Link) -> None:
    """ГД ставит задачу коммерческому директору."""
    task = new_task(client, login, creator="executive", assignee=COMMERCIAL)
    assert task["created_by_name"].startswith("Исполнительный")
    assert task["assignee_name"].startswith("Коммерческий")

    login("executive")
    assert assignee_id(client, COMMERCIAL)


def test_wrong_assignee_rejected(client: TestClient, login: Link) -> None:
    """Коммерческий директор не ставит задачи закупкам и самому ГД."""
    login("commercial")
    purchase = client.get("/api/v1/tasks/assignees").json()
    assert {row["role_title"] for row in purchase} == {
        "Менеджер по продажам",
        "Ассистент отдела продаж",
    }
    login("executive")
    allowed = {row["role_title"] for row in client.get("/api/v1/tasks/assignees").json()}
    assert allowed == {
        "Менеджер по продажам",
        "Ассистент отдела продаж",
        "Коммерческий директор",
    }


def test_manager_cannot_get_assignees(client: TestClient, login: Link) -> None:
    login("sales")
    assert client.get("/api/v1/tasks/assignees").status_code == 403


def test_steps_run_in_order(client: TestClient, login: Link) -> None:
    """Этапы не пересекаются и укладываются в сроки задачи."""
    login("commercial")
    task = new_task(
        client,
        login,
        start_date=day(0),
        due_date=day(29),
        steps=[
            {"title": "Первый", "start_date": day(0), "due_date": day(14)},
            {"title": "Второй", "start_date": day(15), "due_date": day(29)},
        ],
    )
    assert [row["title"] for row in task["steps"]] == ["Первый", "Второй"]

    overlap = client.post(
        f"/api/v1/tasks/{task['id']}/steps",
        json={"title": "Третий", "start_date": day(20), "due_date": day(29)},
    )
    assert overlap.status_code == 422
    assert "пересекается с этапом" in overlap.json()["detail"]

    outside = client.post(
        f"/api/v1/tasks/{task['id']}/steps",
        json={"title": "Поздний", "start_date": day(30), "due_date": day(32)},
    )
    assert outside.status_code == 422


def test_step_closes_only_by_report(client: TestClient, login: Link) -> None:
    """Этап закрывается промежуточным отчётом исполнителя, а не галочкой."""
    task = new_task(
        client,
        login,
        start_date=day(-2),
        due_date=day(9),
        steps=[{"title": "Собрать цены", "start_date": day(-2), "due_date": day(2)}],
    )
    step = task["steps"][0]

    login("commercial")
    denied = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Отчёт директора", "progress": 30},
    )
    assert denied.status_code == 403

    login("sales")
    report = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={
            "kind": "interim",
            "text": "Цены собраны по всем клиентам",
            "progress": 50,
            "step_id": step["id"],
        },
    )
    assert report.status_code == 200, report.text
    body = report.json()
    closed = next(row for row in body["steps"] if row["id"] == step["id"])
    assert closed["is_done"] is True
    assert closed["has_report"] is True
    assert body["reports"][-1]["step_title"] == "Собрать цены"

    again = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Ещё раз", "progress": 60, "step_id": step["id"]},
    )
    assert again.status_code == 409


def test_step_needs_report_when_overdue(client: TestClient, login: Link) -> None:
    task = new_task(
        client,
        login,
        start_date=day(-10),
        due_date=day(3),
        steps=[{"title": "Просроченный этап", "start_date": day(-10), "due_date": day(-1)}],
    )
    assert task["steps"][0]["needs_report"] is True
    assert task["steps"][0]["has_report"] is False


def test_final_report_closes_task_and_notifies_creator(
    client: TestClient, login: Link, db_session: Session
) -> None:
    task = new_task(client, login)
    login("sales")
    final = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "final", "text": "Готово, цены согласованы", "progress": 100},
    )
    assert final.status_code == 200, final.text
    body = final.json()
    assert body["status"] == "done"
    assert body["progress"] == 100

    # Постановщик получил служебное сообщение о финальном отчёте.
    login("commercial")
    messages = client.get("/api/v1/messages").json()
    assert any("выполнена" in row["summary"] for row in messages["rows"])

    events = db_session.execute(
        select(AuditEvent).where(AuditEvent.entity_kind == "task")
    ).scalars()
    assert {"task.created", "task.done"} <= {event.action for event in events}


def test_assignee_gets_message_on_creation_and_cancel(client: TestClient, login: Link) -> None:
    task = new_task(client, login)
    login("sales")
    rows = client.get("/api/v1/messages").json()["rows"]
    assert any("Поставлена задача" in row["summary"] for row in rows)

    login("commercial")
    cancelled = client.post(f"/api/v1/tasks/{task['id']}/status", json={"action": "cancel"})
    assert cancelled.status_code == 200, cancelled.text
    login("sales")
    rows = client.get("/api/v1/messages").json()["rows"]
    assert any("отозвана" in row["summary"] for row in rows)
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["actions"]["can_report"] is False


def test_interim_report_visible_to_creator(client: TestClient, login: Link) -> None:
    task = new_task(client, login)
    login("sales")
    client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Сделал половину", "progress": 50},
    )
    login("commercial")
    rows = client.get("/api/v1/messages").json()["rows"]
    assert any("Отчёт по задаче" in row["summary"] for row in rows)


def test_priority_change_notifies_assignee(client: TestClient, login: Link) -> None:
    task = new_task(client, login)
    login("commercial")
    changed = client.patch(f"/api/v1/tasks/{task['id']}", json={"priority": "red"})
    assert changed.status_code == 200, changed.text
    login("sales")
    rows = client.get("/api/v1/messages").json()["rows"]
    assert any("изменена" in row["summary"].lower() for row in rows)


def test_only_creator_or_exec_changes_task(client: TestClient, login: Link) -> None:
    task = new_task(client, login)
    login("sales")
    assert client.patch(f"/api/v1/tasks/{task['id']}", json={"priority": "red"}).status_code == 403
    login("executive")
    assert client.patch(f"/api/v1/tasks/{task['id']}", json={"priority": "red"}).status_code == 200


def test_closed_task_reopened_by_creator(client: TestClient, login: Link) -> None:
    task = new_task(client, login)
    login("sales")
    client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "final", "text": "Готово", "progress": 100},
    )
    assert (
        client.post(f"/api/v1/tasks/{task['id']}/status", json={"action": "reopen"}).status_code
        == 403
    )
    login("commercial")
    reopened = client.post(f"/api/v1/tasks/{task['id']}/status", json={"action": "reopen"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress"


def test_delete_rules(client: TestClient, login: Link) -> None:
    task = new_task(client, login)
    login("sales")
    client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Промежуточный", "progress": 20},
    )
    login("commercial")
    assert client.delete(f"/api/v1/tasks/{task['id']}").status_code == 409

    other = new_task(client, login, title="Задача без отчётов")
    assert client.delete(f"/api/v1/tasks/{other['id']}").status_code == 204
    assert client.get(f"/api/v1/tasks/{other['id']}").status_code == 404


def test_overdue_flag(client: TestClient, login: Link) -> None:
    task = new_task(client, login, start_date=day(-10), due_date=day(-2))
    assert task["is_overdue"] is True
    assert task["days_overdue"] == 2


def test_report_file_upload_and_download(
    client: TestClient, login: Link, attachments: Path
) -> None:
    task = new_task(client, login)
    login("sales")
    report = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Прикладываю смету", "progress": 30},
    ).json()
    report_id = report["reports"][-1]["id"]
    url = f"/api/v1/tasks/{task['id']}/reports/{report_id}/files"
    uploaded = client.post(url, files={"file": ("смета.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["id"]
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
    task = new_task(client, login)
    login("sales")
    report = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Проверка лимитов", "progress": 10},
    ).json()
    url = f"/api/v1/tasks/{task['id']}/reports/{report['reports'][-1]['id']}/files"
    assert (
        client.post(
            url, files={"file": ("вирус.exe", b"MZ", "application/octet-stream")}
        ).status_code
        == 415
    )

    monkeypatch.setattr(task_service, "FILE_MAX_BYTES", 16)
    assert (
        client.post(url, files={"file": ("смета.pdf", b"x" * 17, "application/pdf")}).status_code
        == 413
    )


def test_progress_comes_from_reports_and_steps(
    client: TestClient, login: Link, db_session: Session
) -> None:
    """Процент на шкале выводится, а не берётся из поля в базе."""
    from app.models.tasks import Task

    task = new_task(client, login)
    # Даже если в базе остался чужой процент, без отчётов задача показывает 0.
    stored = db_session.get(Task, task["id"])
    assert stored is not None
    stored.progress = 30
    db_session.commit()
    login("commercial")
    row = next(item for item in client.get("/api/v1/tasks").json() if item["id"] == task["id"])
    assert row["progress"] == 0

    # Промежуточный отчёт по задаче задаёт процент.
    login("sales")
    client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "interim", "text": "Половина пути", "progress": 40},
    )
    login("commercial")
    row = next(item for item in client.get("/api/v1/tasks").json() if item["id"] == task["id"])
    assert row["progress"] == 40


def test_progress_counts_closed_steps(client: TestClient, login: Link) -> None:
    task = new_task(
        client,
        login,
        start_date=day(0),
        due_date=day(20),
        steps=[
            {"title": "Первый", "start_date": day(0), "due_date": day(9)},
            {"title": "Второй", "start_date": day(10), "due_date": day(20)},
        ],
    )
    login("sales")
    closed = client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={
            "kind": "interim",
            "text": "Первый этап готов",
            "progress": 100,
            "step_id": task["steps"][0]["id"],
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["progress"] == 50
    login("commercial")
    row = next(item for item in client.get("/api/v1/tasks").json() if item["id"] == task["id"])
    assert row["progress"] == 50


def test_reschedule_moves_steps_and_notifies(client: TestClient, login: Link) -> None:
    """Перенос задачи сдвигает этапы на тот же срок и сообщает исполнителю."""
    task = new_task(
        client,
        login,
        start_date=day(0),
        due_date=day(9),
        steps=[{"title": "Этап", "start_date": day(0), "due_date": day(4)}],
    )
    moved = client.post(
        f"/api/v1/tasks/{task['id']}/reschedule",
        json={"start_date": day(3), "due_date": day(12), "move_steps": True},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["start_date"] == day(3)
    assert body["due_date"] == day(12)
    assert body["steps"][0]["start_date"] == day(3)
    assert body["steps"][0]["due_date"] == day(7)

    login("sales")
    rows = client.get("/api/v1/messages").json()["rows"]
    assert any("перенесена" in row["summary"] for row in rows)


def test_reschedule_without_steps_refuses_to_break_them(client: TestClient, login: Link) -> None:
    task = new_task(
        client,
        login,
        start_date=day(0),
        due_date=day(9),
        steps=[{"title": "Этап", "start_date": day(0), "due_date": day(4)}],
    )
    denied = client.post(
        f"/api/v1/tasks/{task['id']}/reschedule",
        json={"start_date": day(3), "due_date": day(12), "move_steps": False},
    )
    assert denied.status_code == 422
    assert "не вмещают этапы" in denied.json()["detail"]


def test_reschedule_closed_task_forbidden(client: TestClient, login: Link) -> None:
    task = new_task(client, login)
    login("sales")
    client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={"kind": "final", "text": "Готово", "progress": 100},
    )
    login("commercial")
    denied = client.post(
        f"/api/v1/tasks/{task['id']}/reschedule",
        json={"start_date": day(1), "due_date": day(10), "move_steps": True},
    )
    assert denied.status_code == 409


def test_step_can_be_added_before_existing(client: TestClient, login: Link) -> None:
    """Свободные даты в начале срока — тоже место для этапа."""
    task = new_task(
        client,
        login,
        start_date=day(0),
        due_date=day(19),
        steps=[{"title": "Второй", "start_date": day(10), "due_date": day(19)}],
    )
    added = client.post(
        f"/api/v1/tasks/{task['id']}/steps",
        json={"title": "Первый", "start_date": day(0), "due_date": day(9)},
    )
    assert added.status_code == 200, added.text
    titles = [row["title"] for row in added.json()["steps"]]
    assert titles == ["Первый", "Второй"]


def test_reschedule_keeps_closed_steps_in_history(client: TestClient, login: Link) -> None:
    """Закрытый этап не переезжает вместе с задачей — это история."""
    task = new_task(
        client,
        login,
        start_date=day(0),
        due_date=day(14),
        steps=[
            {"title": "Закрытый", "start_date": day(0), "due_date": day(4)},
            {"title": "Открытый", "start_date": day(5), "due_date": day(9)},
        ],
    )
    login("sales")
    client.post(
        f"/api/v1/tasks/{task['id']}/reports",
        json={
            "kind": "interim",
            "text": "Первый этап закрыт",
            "progress": 50,
            "step_id": task["steps"][0]["id"],
        },
    )
    login("commercial")
    moved = client.post(
        f"/api/v1/tasks/{task['id']}/reschedule",
        json={"start_date": day(5), "due_date": day(20), "move_steps": True},
    )
    assert moved.status_code == 200, moved.text
    steps = {row["title"]: row for row in moved.json()["steps"]}
    assert steps["Закрытый"]["start_date"] == day(0)
    assert steps["Закрытый"]["due_date"] == day(4)
    assert steps["Открытый"]["start_date"] == day(10)
    assert steps["Открытый"]["due_date"] == day(14)

    # После переноса начало срока свободно — новый этап можно поставить туда.
    added = client.post(
        f"/api/v1/tasks/{task['id']}/steps",
        json={"title": "Новый", "start_date": day(5), "due_date": day(9)},
    )
    assert added.status_code == 200, added.text
