"""Сквозные сценарии годового плана продаж."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import ROLE_SALES_MANAGER, User
from app.models.domain import Product
from app.services.auth import hash_password

TODAY = date.today()


@pytest.fixture
def products(db_session: Session) -> list[Product]:
    goods = Product(code="SKU-1", name="Товар 1", kind="goods", unit="шт")
    material = Product(code="SKU-2", name="Материал 2", kind="material", unit="кг")
    db_session.add_all([goods, material])
    db_session.commit()
    return [goods, material]


def _item(product: Product, month: int, quantity: str, price: str) -> dict[str, str | int]:
    return {"product_id": str(product.id), "month": month, "quantity": quantity, "price": price}


def _create_plan(client: TestClient, year: int, **extra: object) -> dict[str, Any]:
    response = client.post("/api/v1/sales-plans", json={"year": year, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_manager_fills_and_commercial_director_approves(
    client: TestClient, login, products: list[Product]
) -> None:
    login("sales")
    me = client.get("/api/v1/auth/me").json()
    plan = _create_plan(client, TODAY.year)
    assert plan["status"] == "draft"
    assert plan["manager_id"] == me["id"]

    month = TODAY.month
    updated = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], month, "10", "100.00")]},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["items"][0]["amount"] == "1000.00"
    assert body["total_amount"] == "1000.00"
    # Деньги уходят строкой — точность не теряется.
    assert isinstance(body["items"][0]["price"], str)
    assert month in body["editable_months"]

    submitted = client.post(f"/api/v1/sales-plans/{plan['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "on_review"

    login("commercial")
    approved = client.post(f"/api/v1/sales-plans/{plan['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["status_title"] == "Утверждён"

    login("sales")
    denied = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[1], TODAY.month, "5", "10.00")]},
    )
    assert denied.status_code == 409


def test_commercial_director_creates_plan_and_rejects(
    client: TestClient, login, products: list[Product]
) -> None:
    login("commercial")
    managers = client.get("/api/v1/users", params={"role": "sales_manager"}).json()
    assert len(managers) == 1
    manager_id = managers[0]["id"]

    plan = _create_plan(client, TODAY.year, manager_id=manager_id)
    assert (
        client.post(f"/api/v1/sales-plans/{plan['id']}/send-to-fill").json()["status"] == "filling"
    )

    login("sales")
    filled = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "3", "50.00")]},
    )
    assert filled.status_code == 200, filled.text
    assert client.post(f"/api/v1/sales-plans/{plan['id']}/submit").json()["status"] == "on_review"

    login("commercial")
    rejected = client.post(
        f"/api/v1/sales-plans/{plan['id']}/reject", json={"reason": "Мало объёма"}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "filling"
    assert "Мало объёма" in rejected.json()["notes"]


def test_second_plan_for_same_year_and_manager_is_conflict(client: TestClient, login) -> None:
    login("sales")
    _create_plan(client, TODAY.year)
    second = client.post("/api/v1/sales-plans", json={"year": TODAY.year})
    assert second.status_code == 409
    assert "уже есть" in second.json()["detail"]


def test_empty_plan_cannot_be_submitted(client: TestClient, login) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    response = client.post(f"/api/v1/sales-plans/{plan['id']}/submit")
    assert response.status_code == 400
    assert "пустой план" in response.json()["detail"]


def test_past_year_is_frozen(client: TestClient, login, products: list[Product]) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year - 1)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], 1, "1", "1.00")]},
    )
    assert response.status_code == 409
    assert "Замороженные месяцы" in response.json()["detail"]


def test_past_month_of_current_year_is_frozen(
    client: TestClient, login, products: list[Product]
) -> None:
    if TODAY.month == 1:
        pytest.skip("в январе прошлых месяцев текущего года нет")
    login("sales")
    plan = _create_plan(client, TODAY.year)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], 1, "1", "1.00")]},
    )
    assert response.status_code == 409
    assert "Замороженные месяцы" in response.json()["detail"]


def test_manager_sees_only_own_plans(
    client: TestClient, login, products: list[Product], db_session: Session
) -> None:
    login("sales")
    own = _create_plan(client, TODAY.year)

    other = User(
        login="sales-2",
        full_name="Второй менеджер",
        role=ROLE_SALES_MANAGER,
        password_hash=hash_password("test-password"),
    )
    db_session.add(other)
    db_session.commit()

    login("commercial")
    foreign = _create_plan(client, TODAY.year, manager_id=str(other.id))

    login("sales")
    listed = client.get("/api/v1/sales-plans").json()
    assert [row["id"] for row in listed] == [own["id"]]
    assert client.get(f"/api/v1/sales-plans/{foreign['id']}").status_code == 403


def test_commercial_director_edit_returns_approved_plan_to_review(
    client: TestClient, login, products: list[Product]
) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "10", "100.00")]},
    )
    client.post(f"/api/v1/sales-plans/{plan['id']}/submit")

    login("commercial")
    client.post(f"/api/v1/sales-plans/{plan['id']}/approve")
    edited = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "12", "100.00")]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "on_review"
    assert Decimal(edited.json()["total_amount"]) == Decimal("1200.00")


def test_duplicate_row_is_rejected(client: TestClient, login, products: list[Product]) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [
                _item(products[0], TODAY.month, "1", "1.00"),
                _item(products[0], TODAY.month, "2", "1.00"),
            ]
        },
    )
    assert response.status_code == 400
    assert "две строки" in response.json()["detail"]
