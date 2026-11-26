"""Сквозные сценарии годового плана продаж (клиент × товар × месяц)."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import ROLE_SALES_MANAGER, User
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import SalesPlanItem
from app.services.auth import hash_password

TODAY = date.today()


@pytest.fixture
def products(db_session: Session) -> list[Product]:
    goods = Product(code="SKU-1", name="Товар 1", kind="finished", unit="шт")
    material = Product(code="SKU-2", name="Материал 2", kind="material", unit="кг")
    db_session.add_all([goods, material])
    db_session.commit()
    return [goods, material]


@pytest.fixture
def clients(db_session: Session) -> list[Counterparty]:
    first = Counterparty(
        name="ООО Ромашка", name_key="ооо ромашка", inn="7701234567", is_customer=True
    )
    second = Counterparty(name="ООО Вектор", name_key="ооо вектор", is_customer=True)
    db_session.add_all([first, second])
    db_session.commit()
    return [first, second]


def _item(
    product: Product, month: int, quantity: str, client_row: Counterparty
) -> dict[str, str | int]:
    return {
        "client_id": str(client_row.id),
        "product_id": str(product.id),
        "month": month,
        "quantity": quantity,
    }


def _create_plan(client: TestClient, year: int, **extra: object) -> dict[str, Any]:
    response = client.post("/api/v1/sales-plans", json={"year": year, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_manager_fills_and_commercial_director_approves(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    login("sales")
    me = client.get("/api/v1/auth/me").json()
    plan = _create_plan(client, TODAY.year)
    assert plan["status"] == "draft"
    assert plan["manager_id"] == me["id"]

    month = TODAY.month
    updated = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], month, "10", clients[0])]},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["items"][0]["client_name"] == "ООО Ромашка"
    assert body["items"][0]["quantity"] == "10.000"
    # Количество уходит строкой — точность не теряется.
    assert isinstance(body["items"][0]["quantity"], str)
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
        json={"items": [_item(products[1], TODAY.month, "5", clients[0])]},
    )
    assert denied.status_code == 409


def test_purchase_roles_see_sales_plans_read_only(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    saved = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "10", clients[0])]},
    )
    assert saved.status_code == 200, saved.text

    login("purchase")
    listed = client.get("/api/v1/sales-plans")
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [plan["id"]]
    detail = client.get(f"/api/v1/sales-plans/{plan['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["items"][0]["quantity"] == "10.000"

    # Просмотр — да, правка, создание и утверждение — нет.
    denied = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[1], TODAY.month, "5", clients[0])]},
    )
    assert denied.status_code == 403, denied.text
    assert client.post(f"/api/v1/sales-plans/{plan['id']}/approve").status_code == 403
    assert client.post("/api/v1/sales-plans", json={"year": TODAY.year + 1}).status_code == 403

    login("import")
    assert client.get("/api/v1/sales-plans").status_code == 200


def test_same_product_for_two_clients_is_allowed(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    saved = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [
                _item(products[0], TODAY.month, "10", clients[0]),
                _item(products[0], TODAY.month, "4", clients[1]),
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert [row["client_name"] for row in body["items"]] == ["ООО Вектор", "ООО Ромашка"]
    assert [row["quantity"] for row in body["items"]] == ["4.000", "10.000"]


def test_line_without_client_is_rejected(
    client: TestClient, login, products: list[Product]
) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [
                {
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "1",
                }
            ]
        },
    )
    assert response.status_code == 422


def test_unknown_client_is_rejected(client: TestClient, login, products: list[Product]) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [
                {
                    "client_id": "00000000-0000-0000-0000-000000000000",
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "1",
                }
            ]
        },
    )
    assert response.status_code == 404
    assert "Клиент не найден" in response.json()["detail"]


def test_commercial_director_creates_plan_and_rejects(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    login("commercial")
    managers = client.get("/api/v1/users", params={"role": "sales_manager"}).json()
    # В демо-сиде три менеджера по продажам: sales, sales2, sales3.
    assert {row["login"] for row in managers} >= {"sales", "sales2", "sales3"}
    manager_id = next(row["id"] for row in managers if row["login"] == "sales")

    plan = _create_plan(client, TODAY.year, manager_id=manager_id)
    assert (
        client.post(f"/api/v1/sales-plans/{plan['id']}/send-to-fill").json()["status"] == "filling"
    )

    login("sales")
    filled = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "3", clients[0])]},
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


def test_past_year_is_frozen(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year - 1)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], 1, "1", clients[0])]},
    )
    assert response.status_code == 409
    assert "Замороженные месяцы" in response.json()["detail"]


def test_past_month_of_current_year_is_frozen(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    if TODAY.month == 1:
        pytest.skip("в январе прошлых месяцев текущего года нет")
    login("sales")
    plan = _create_plan(client, TODAY.year)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], 1, "1", clients[0])]},
    )
    assert response.status_code == 409
    assert "Замороженные месяцы" in response.json()["detail"]


def test_manager_sees_only_own_plans(
    client: TestClient, login, clients: list[Counterparty], db_session: Session
) -> None:
    login("sales")
    own = _create_plan(client, TODAY.year)

    other = User(
        login="sales-2",
        full_name="Второй менеджер",
        role=ROLE_SALES_MANAGER,
        password_hash=hash_password("test-password"),
        is_manager=True,
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
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "10", clients[0])]},
    )
    client.post(f"/api/v1/sales-plans/{plan['id']}/submit")

    login("commercial")
    client.post(f"/api/v1/sales-plans/{plan['id']}/approve")
    edited = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "12", clients[0])]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "on_review"
    assert Decimal(edited.json()["items"][0]["quantity"]) == Decimal("12.000")


def test_duplicate_row_is_rejected(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [
                _item(products[0], TODAY.month, "1", clients[0]),
                _item(products[0], TODAY.month, "2", clients[0]),
            ]
        },
    )
    assert response.status_code == 400
    assert "две строки" in response.json()["detail"]


def test_admin_manages_any_sales_plan(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    """Исполнительный директор создаёт, правит, отправляет и утверждает планы."""
    login("sales")
    manager_id = client.get("/api/v1/auth/me").json()["id"]

    login("executive")
    plan = _create_plan(client, TODAY.year, manager_id=manager_id)
    assert plan["manager_id"] == manager_id
    saved = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "15", clients[0])]},
    )
    assert saved.status_code == 200, saved.text
    assert client.delete(f"/api/v1/sales-plans/{plan['id']}").status_code == 204

    plan = _create_plan(client, TODAY.year, manager_id=manager_id)
    assert (
        client.put(
            f"/api/v1/sales-plans/{plan['id']}/items",
            json={"items": [_item(products[0], TODAY.month, "20", clients[0])]},
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/sales-plans/{plan['id']}/submit").status_code == 200
    approved = client.post(f"/api/v1/sales-plans/{plan['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_draft_rows_without_quantities_are_saved(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    """Клиент и позиции сохраняются ещё до ввода количеств — и переживают перезагрузку."""
    login("sales")
    plan = _create_plan(client, TODAY.year)
    payload = {
        "items": [],
        "clients": [{"client_id": str(clients[0].id)}],
        "rows": [
            {"client_id": str(clients[0].id), "product_id": str(products[0].id)},
            {"client_id": str(clients[0].id), "product_id": str(products[1].id)},
        ],
    }
    saved = client.put(f"/api/v1/sales-plans/{plan['id']}/items", json=payload)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["items"] == []
    assert [row["client_id"] for row in body["draft_clients"]] == [str(clients[0].id)]
    assert {row["product_id"] for row in body["draft_rows"]} == {
        str(products[0].id),
        str(products[1].id),
    }
    assert body["draft_rows"][0]["unit"] in {"шт", "кг"}

    # Повторное сохранение без количеств не обнуляет состав черновика.
    again = client.put(f"/api/v1/sales-plans/{plan['id']}/items", json=payload)
    assert again.status_code == 200, again.text
    assert len(again.json()["draft_rows"]) == 2

    reloaded = client.get(f"/api/v1/sales-plans/{plan['id']}").json()
    assert len(reloaded["draft_rows"]) == 2
    assert reloaded["draft_clients"][0]["client_name"] == "ООО Ромашка"


def test_legacy_empty_save_does_not_wipe_filled_plan(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    """Старый клиент без состава черновика не может стереть заполненный план."""
    login("sales")
    plan = _create_plan(client, TODAY.year)
    saved = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [_item(products[0], TODAY.month, "10", clients[0])]},
    )
    assert saved.status_code == 200, saved.text

    wiped = client.put(f"/api/v1/sales-plans/{plan['id']}/items", json={"items": []})
    assert wiped.status_code == 409, wiped.text
    assert "обнулить" in wiped.json()["detail"]

    reloaded = client.get(f"/api/v1/sales-plans/{plan['id']}").json()
    assert len(reloaded["items"]) == 1
    assert reloaded["items"][0]["quantity"] == "10.000"


def test_unknown_product_in_draft_is_rejected(
    client: TestClient, login, clients: list[Counterparty]
) -> None:
    login("sales")
    plan = _create_plan(client, TODAY.year)
    response = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [],
            "clients": [{"client_id": str(clients[0].id)}],
            "rows": [
                {
                    "client_id": str(clients[0].id),
                    "product_id": "00000000-0000-0000-0000-000000000000",
                }
            ],
        },
    )
    assert response.status_code == 404, response.text
    assert "номенклатуры" in response.json()["detail"]


def test_draft_row_and_client_can_be_removed(
    client: TestClient, login, products: list[Product], clients: list[Counterparty]
) -> None:
    """Убрать позицию или клиента из черновика можно, пока нет замороженных объёмов."""
    login("sales")
    plan = _create_plan(client, TODAY.year + 1)
    first, second = str(clients[0].id), str(clients[1].id)
    saved = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [
                _item(products[0], 1, "5", clients[0]),
                _item(products[0], 1, "7", clients[1]),
            ],
            "clients": [{"client_id": first}, {"client_id": second}],
            "rows": [
                {"client_id": first, "product_id": str(products[0].id)},
                {"client_id": second, "product_id": str(products[0].id)},
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    # Убрали позицию у первого клиента: строка исчезла, клиент остался.
    row_removed = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [_item(products[0], 1, "7", clients[1])],
            "clients": [{"client_id": first}, {"client_id": second}],
            "rows": [{"client_id": second, "product_id": str(products[0].id)}],
        },
    )
    assert row_removed.status_code == 200, row_removed.text
    body = row_removed.json()
    assert [row["client_id"] for row in body["items"]] == [second]
    assert {row["client_id"] for row in body["draft_clients"]} == {first, second}
    assert all(row["client_id"] != first for row in body["draft_rows"])

    # Убрали обоих клиентов: план снова пустой, как только его создали.
    cleared = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [], "clients": [], "rows": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["items"] == []
    assert cleared.json()["draft_clients"] == []
    assert cleared.json()["draft_rows"] == []


def test_frozen_rows_block_removing_client_or_position(
    client: TestClient,
    login,
    products: list[Product],
    clients: list[Counterparty],
    db_session: Session,
) -> None:
    """Строку с объёмом в замороженном месяце удалить нельзя — она вернулась бы."""
    login("sales")
    plan = _create_plan(client, TODAY.year - 1)
    db_session.add(
        SalesPlanItem(
            plan_id=UUID(plan["id"]),
            client_id=clients[0].id,
            product_id=products[0].id,
            month=1,
            quantity=Decimal("5"),
        )
    )
    db_session.commit()

    without_client = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={"items": [], "clients": [], "rows": []},
    )
    assert without_client.status_code == 409, without_client.text
    assert "замороженных" in without_client.json()["detail"]

    without_row = client.put(
        f"/api/v1/sales-plans/{plan['id']}/items",
        json={
            "items": [],
            "clients": [{"client_id": str(clients[0].id)}],
            "rows": [],
        },
    )
    assert without_row.status_code == 409, without_row.text
    assert "замороженных" in without_row.json()["detail"]

    reloaded = client.get(f"/api/v1/sales-plans/{plan['id']}").json()
    assert len(reloaded["items"]) == 1
    assert reloaded["items"][0]["quantity"] == "5.000"
