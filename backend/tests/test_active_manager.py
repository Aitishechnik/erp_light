"""«Активный менеджер»: личный статус продаж независимо от должности."""

from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import User

TODAY = date.today()
YEAR = TODAY.year


def _user_id(client: TestClient, login: str) -> str:
    rows = client.get("/api/v1/admin/users").json()
    row = next(row for row in rows if row["login"] == login)
    return str(row["id"])


def _set_manager(client: TestClient, sign_in: Callable[[str], None], name: str, value: bool) -> Any:
    sign_in("admin")
    response = client.patch(
        f"/api/v1/admin/users/{_user_id(client, name)}", json={"is_manager": value}
    )
    return response


def _item(catalog: dict[str, Any], quantity: str = "10") -> dict[str, Any]:
    return {
        "client_id": str(catalog["customer"].id),
        "product_id": str(catalog["fin"].id),
        "month": TODAY.month,
        "quantity": quantity,
    }


def _fill(client: TestClient, plan_id: str, catalog: dict[str, Any]) -> None:
    response = client.put(f"/api/v1/sales-plans/{plan_id}/items", json={"items": [_item(catalog)]})
    assert response.status_code == 200, response.text


def test_admin_marks_any_role_as_manager_and_it_appears_in_lists(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    login("admin")
    created = client.post(
        "/api/v1/admin/users",
        json={
            "login": "assistant_manager",
            "full_name": "Ассистент Продающий",
            "password": "test-password",
            "role": "sales_assistant",
            "is_manager": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_manager"] is True

    login("assistant_manager")
    me = client.get("/api/v1/auth/me").json()
    assert me["is_manager"] is True
    assert me["role"] == "sales_assistant"

    # Свой план доступен без прав уровня: статус менеджера даёт личные продажи.
    assert client.get("/api/v1/sales-plans").status_code == 200
    plan = client.post("/api/v1/sales-plans", json={"year": YEAR})
    assert plan.status_code == 201, plan.text
    assert str(plan.json()["manager_id"]) == me["id"]
    _fill(client, plan.json()["id"], catalog)

    # Утверждать по-прежнему может только должность.
    assert client.post(f"/api/v1/sales-plans/{plan.json()['id']}/submit").status_code == 200
    assert client.post(f"/api/v1/sales-plans/{plan.json()['id']}/approve").status_code == 403

    login("commercial")
    managers = client.get("/api/v1/users/managers").json()
    assert "assistant_manager" in {row["login"] for row in managers}
    assert client.post(f"/api/v1/sales-plans/{plan.json()['id']}/approve").status_code == 200


def test_manager_list_accepts_any_position(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    login("admin")
    client.patch(
        f"/api/v1/admin/users/{_user_id(client, 'commercial')}",
        json={"is_manager": True},
    )
    login("commercial")
    managers = client.get("/api/v1/users/managers").json()
    assert "commercial" in {row["login"] for row in managers}
    assert "assistant" not in {row["login"] for row in managers}

    # Клиента можно закрепить за коммерческим директором.
    client_row = client.post(
        "/api/v1/counterparties",
        json={
            "name": "ООО Новый клиент",
            "is_customer": True,
            "manager_id": str(client.get("/api/v1/auth/me").json()["id"]),
        },
    )
    assert client_row.status_code == 201, client_row.text
    assert client_row.json()["manager_name"] == "Коммерческий директор (демо)"


def test_commercial_director_approves_own_plan(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    assert _set_manager(client, login, "commercial", True).status_code == 200

    login("commercial")
    me = client.get("/api/v1/auth/me").json()
    created = client.post("/api/v1/sales-plans", json={"year": YEAR, "manager_id": me["id"]})
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    _fill(client, plan_id, catalog)
    assert client.post(f"/api/v1/sales-plans/{plan_id}/submit").status_code == 200
    # Цепочку не ломаем: свой план утверждает сам коммерческий директор.
    approved = client.post(f"/api/v1/sales-plans/{plan_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_annual_plan_includes_manager_of_any_role(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    assert _set_manager(client, login, "commercial", True).status_code == 200

    login("commercial")
    me = client.get("/api/v1/auth/me").json()
    created = client.post("/api/v1/sales-plans", json={"year": YEAR, "manager_id": me["id"]})
    assert created.status_code == 201, created.text
    _fill(client, created.json()["id"], catalog)
    client.post(f"/api/v1/sales-plans/{created.json()['id']}/submit")
    client.post(f"/api/v1/sales-plans/{created.json()['id']}/approve")

    annual = client.get("/api/v1/annual-sales-plans", params={"year": YEAR}).json()
    names = {row["manager_name"] for row in annual["managers"]}
    assert "Коммерческий директор (демо)" in names


def test_manager_flag_does_not_grant_approval_or_foreign_plans(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    assert _set_manager(client, login, "assistant", True).status_code == 200

    login("sales")
    own = client.post("/api/v1/sales-plans", json={"year": YEAR})
    assert own.status_code == 201, own.text

    login("assistant")
    assistant_plan = client.post("/api/v1/sales-plans", json={"year": YEAR})
    assert assistant_plan.status_code == 201, assistant_plan.text
    listed = client.get("/api/v1/sales-plans").json()
    assert [row["id"] for row in listed] == [assistant_plan.json()["id"]]
    assert client.get(f"/api/v1/sales-plans/{own.json()['id']}").status_code == 403


def test_unflag_is_blocked_while_data_exists(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    assert _set_manager(client, login, "assistant", True).status_code == 200
    login("assistant")
    plan = client.post("/api/v1/sales-plans", json={"year": YEAR})
    assert plan.status_code == 201, plan.text

    blocked = _set_manager(client, login, "assistant", False)
    assert blocked.status_code == 409, blocked.text
    assert "передайте" in blocked.json()["detail"]

    # Без данных галочка снимается.
    login("admin")
    client.delete(f"/api/v1/sales-plans/{plan.json()['id']}")
    assert _set_manager(client, login, "assistant", False).status_code == 200


def test_plan_and_client_cannot_be_assigned_to_unflagged_employee(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    executive = db_session.query(User).filter(User.login == "executive").one()

    login("commercial")
    plan = client.post("/api/v1/sales-plans", json={"year": YEAR, "manager_id": str(executive.id)})
    assert plan.status_code == 400, plan.text
    assert "ведёт клиентов" in plan.json()["detail"]

    client_row = client.post(
        "/api/v1/counterparties",
        json={
            "name": "ООО Не тот менеджер",
            "is_customer": True,
            "manager_id": str(executive.id),
        },
    )
    assert client_row.status_code == 400, client_row.text
    assert "не ведёт клиентов" in client_row.json()["detail"]
