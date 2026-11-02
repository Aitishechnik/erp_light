"""Служебные сообщения и журнал действий.

Проверяем главное: критические события попадают исполнительному директору,
другие роли их пока не получают, прочитанность работает, а журнал показывает
свои действия всем, а исполнительному — все.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.auth import User
from app.services import audit_service
from app.services.plan_freeze import editable_months
from tests.test_month_results import month, sales_xlsx, upload_sales


def _user(db: Session, login: str) -> User:
    return db.execute(select(User).where(User.login == login)).scalars().one()


def _approve_plan(client: TestClient, login, catalog: dict[str, Any], db: Session) -> None:
    """План на 2026 год: создаём, заполняем, отправляем, утверждаем."""
    login("commercial")
    manager_id = _user(db, "sales").id
    created = client.post("/api/v1/sales-plans", json={"year": 2026, "manager_id": str(manager_id)})
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    # Месяц берём незамороженный: прошедшие месяцы 2026 года править нельзя.
    editable = editable_months(2026)
    items = [
        {
            "client_id": str(catalog["customer"].id),
            "product_id": str(catalog["fin"].id),
            "month": editable[-1] if editable else 12,
            "quantity": "100",
        }
    ]
    assert (
        client.put(f"/api/v1/sales-plans/{plan_id}/items", json={"items": items}).status_code == 200
    )
    login("sales")
    assert client.post(f"/api/v1/sales-plans/{plan_id}/submit").status_code == 200
    login("commercial")
    assert client.post(f"/api/v1/sales-plans/{plan_id}/approve").status_code == 200


def test_plan_approval_goes_to_executive_only(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _approve_plan(client, login, catalog, db_session)

    login("commercial")
    as_commercial = client.get("/api/v1/messages").json()
    assert as_commercial["rows"] == []
    assert as_commercial["unread"] == 0

    login("executive")
    as_executive = client.get("/api/v1/messages").json()
    actions = [row["action"] for row in as_executive["rows"]]
    assert actions == ["sales_plan.approved", "sales_plan.items_changed"]
    assert as_executive["unread"] == 2
    assert as_executive["rows"][0]["level"] == "critical"
    assert "Менеджер по продажам" in as_executive["rows"][0]["summary"]
    assert client.get("/api/v1/messages/count").json() == {"unread": 2}


def test_messages_can_be_marked_read(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _approve_plan(client, login, catalog, db_session)
    login("executive")
    rows = client.get("/api/v1/messages").json()["rows"]
    assert rows and rows[0]["read"] is False

    marked = client.post("/api/v1/messages/read", json={"ids": [row["id"] for row in rows]})
    assert marked.status_code == 200, marked.text
    assert marked.json() == {"unread": 0}
    assert client.get("/api/v1/messages?unread=1").json()["rows"] == []

    _approve_second_event(client, login, catalog, db_session)
    login("executive")
    assert client.get("/api/v1/messages/count").json() == {"unread": 1}
    assert client.post("/api/v1/messages/read-all").json() == {"unread": 0}


def _approve_second_event(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Ещё одно критическое событие: правка номенклатуры."""
    login("commercial")
    updated = client.patch(
        f"/api/v1/products/{catalog['fin'].id}", json={"name": "Смесь ореховая 2"}
    )
    assert updated.status_code == 200, updated.text


def test_month_close_and_decision_are_logged(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _approve_plan(client, login, catalog, db_session)
    login("commercial")
    content = sales_xlsx([("ООО Ромашка", [("Смесь ореховая", "90", "9000")])])
    uploaded = upload_sales(client, content)
    assert uploaded.status_code == 200, uploaded.text
    decided = client.put(
        "/api/v1/month-results/2026/10/decision",
        json={
            "decision": "transfer_purchase",
            "target_year": 2026,
            "target_month": 11,
            "comment": "переносим закупку",
        },
    )
    assert decided.status_code == 200, decided.text
    assert client.post("/api/v1/month-results/2026/10/close").status_code == 200

    actions = [row["action"] for row in client.get("/api/v1/audit?limit=20").json()]
    assert "month.closed" in actions
    assert "month.decision_set" in actions

    # Закрытый месяц в сообщениях читается как решение с месяцем переноса.
    login("executive")
    summaries = [row["summary"] for row in client.get("/api/v1/messages?limit=20").json()["rows"]]
    assert any("11.2026" in text for text in summaries)
    assert month(client, 2026, 10)["status"] == "closed"


def test_journal_shows_own_actions_and_everything_for_executive(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _approve_plan(client, login, catalog, db_session)

    # Своё критическое действие менеджера: удаление своего черновика.
    login("sales")
    created = client.post("/api/v1/sales-plans", json={"year": 2027})
    assert created.status_code == 201, created.text
    assert client.delete(f"/api/v1/sales-plans/{created.json()['id']}").status_code == 204

    own = client.get("/api/v1/audit?limit=50").json()
    assert [row["action"] for row in own] == ["sales_plan.deleted"]
    assert own[0]["actor_name"] == "Менеджер по продажам (демо)"

    login("executive")
    everything = client.get("/api/v1/audit?limit=50").json()
    actions = [row["action"] for row in everything]
    assert "sales_plan.approved" in actions
    assert "sales_plan.deleted" in actions
    assert len(everything) > len(own)


def test_failed_login_is_logged(client: TestClient, login, db_session: Session) -> None:
    client.post("/api/v1/auth/login", json={"login": "commercial", "password": "не тот"})
    events = db_session.execute(select(AuditEvent).where(AuditEvent.action == "auth.login_failed"))
    rows = events.scalars().all()
    assert len(rows) == 1
    assert rows[0].level == "critical"
    assert rows[0].payload == {"login": "commercial"}

    login("executive")
    messages = client.get("/api/v1/messages").json()["rows"]
    assert any(row["action"] == "auth.login_failed" for row in messages)


def test_event_links_to_object(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _approve_plan(client, login, catalog, db_session)
    login("executive")
    rows = client.get("/api/v1/messages").json()["rows"]
    plan_link = next(row for row in rows if row["action"] == "sales_plan.approved")["link"]
    assert plan_link.startswith("#/sales-plan/2026/")
    assert plan_link.endswith(rows[0]["entity_id"]) or plan_link.endswith(
        next(row for row in rows if row["action"] == "sales_plan.approved")["entity_id"]
    )


def test_cleanup_offered_from_march_every_month(db_session: Session, users: None) -> None:
    executive = _user(db_session, "executive")
    assert audit_service.cleanup_year_for(date(2026, 2, 28)) is None
    assert audit_service.cleanup_year_for(date(2026, 3, 1)) == 2025

    # Запись прошлого года: её и предлагаем почистить.
    old = AuditEvent(
        action="country.updated",
        level="critical",
        summary="старая запись",
        is_message=False,
        audience=[],
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
    )
    db_session.add(old)
    db_session.commit()

    audit_service.maybe_offer_cleanup(db_session, executive, today=date(2026, 3, 1))
    first = (
        db_session.execute(select(AuditEvent).where(AuditEvent.action == "audit.cleanup_offered"))
        .scalars()
        .all()
    )
    assert len(first) == 1
    assert "2025" in first[0].summary

    # В том же месяце второй раз не предлагаем, в следующем — снова.
    audit_service.maybe_offer_cleanup(db_session, executive, today=date(2026, 3, 20))
    assert (
        len(
            db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "audit.cleanup_offered")
            )
            .scalars()
            .all()
        )
        == 1
    )


def test_cleanup_deletes_previous_year(db_session: Session, users: None) -> None:
    executive = _user(db_session, "executive")
    old = AuditEvent(
        action="country.updated",
        level="critical",
        summary="старая запись",
        is_message=False,
        audience=[],
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
    )
    fresh = AuditEvent(
        action="country.updated",
        level="critical",
        summary="свежая запись",
        is_message=False,
        audience=[],
        created_at=datetime(2026, 1, 10, tzinfo=UTC),
    )
    db_session.add_all([old, fresh])
    db_session.commit()

    deleted = audit_service.cleanup_journal(db_session, executive, 2025)
    assert deleted == 1
    left = db_session.execute(select(AuditEvent.summary)).scalars().all()
    assert "старая запись" not in left
    assert "свежая запись" in left
    assert "Журнал за 2025 год очищен" in " ".join(left)


def test_journal_keeps_addressed_messages_after_reading(client: TestClient, login) -> None:
    """Колокольчик показывает только непрочитанное, журнал — и прочитанное тоже."""
    login("commercial")
    people = {row["full_name"]: row["id"] for row in client.get("/api/v1/tasks/assignees").json()}
    start = date.today().isoformat()
    created = client.post(
        "/api/v1/tasks",
        json={
            "title": "Сообщение в журнале",
            "start_date": start,
            "due_date": start,
            "assignee_id": people["Менеджер по продажам (демо)"],
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    login("sales")
    journal = client.get("/api/v1/audit", params={"limit": 100}).json()
    assert any(row["action"] == "task.created" and row["entity_id"] == task_id for row in journal)

    unread = client.get("/api/v1/messages", params={"unread": True}).json()["rows"]
    message = next(row for row in unread if row["entity_id"] == task_id)
    assert client.post("/api/v1/messages/read", json={"ids": [message["id"]]}).status_code == 200

    left = client.get("/api/v1/messages", params={"unread": True}).json()["rows"]
    assert all(row["entity_id"] != task_id for row in left)
    after = client.get("/api/v1/audit", params={"limit": 100}).json()
    assert any(row["entity_id"] == task_id for row in after)

    # Чужому менеджеру адресованное не показываем.
    login("sales2")
    other = client.get("/api/v1/audit", params={"limit": 100}).json()
    assert all(row["entity_id"] != task_id for row in other)
