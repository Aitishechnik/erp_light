"""Позиции будущих периодов: заведение по названию и привязка к 1С."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.access import RolePermission
from app.models.auth import User
from app.models.planning import SalesPlanCorrection, SalesPlanCorrectionItem

TODAY = date.today()


def _plan(client: TestClient, year: int) -> dict[str, Any]:
    response = client.post("/api/v1/sales-plans", json={"year": year})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _future(client: TestClient, name: str = "Сок яблочный", unit: str = "л") -> dict[str, Any]:
    response = client.post("/api/v1/future-products", json={"name": name, "unit": unit})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _save(
    client: TestClient,
    plan_id: str,
    *,
    items: list[dict[str, Any]],
    clients: list[str],
    rows: list[tuple[str, str]],
) -> Any:
    return client.put(
        f"/api/v1/sales-plans/{plan_id}/items",
        json={
            "items": items,
            "clients": [{"client_id": client_id} for client_id in clients],
            "rows": [
                {"client_id": client_id, "product_id": product_id} for client_id, product_id in rows
            ],
        },
    )


def test_future_product_lives_in_separate_list(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    """Позиция заводится по названию, не попадает в обычную номенклатуру и удаляется."""
    login("sales")
    future = _future(client)
    assert future["is_future"] is True
    assert future["name"] == "Сок яблочный"
    assert future["unit"] == "л"
    assert future["code"].startswith("БУД-")

    listed = client.get("/api/v1/future-products").json()
    assert [row["name"] for row in listed] == ["Сок яблочный"]
    assert listed[0]["plans_count"] == 0
    assert listed[0]["rows_count"] == 0

    regular = client.get("/api/v1/products").json()
    assert all(row["id"] != future["id"] for row in regular)
    planning = client.get("/api/v1/products", params={"include_future": "true"}).json()
    assert any(row["id"] == future["id"] for row in planning)

    assert client.delete(f"/api/v1/future-products/{future['id']}").status_code == 204
    assert client.get("/api/v1/future-products").json() == []


def test_duplicate_name_and_permissions(client: TestClient, login, catalog: dict[str, Any]) -> None:
    login("sales")
    _future(client, "Сок яблочный")
    duplicate = client.post("/api/v1/future-products", json={"name": "сок яблочный", "unit": "л"})
    assert duplicate.status_code == 409, duplicate.text

    login("import")
    denied = client.post("/api/v1/future-products", json={"name": "Новая", "unit": "шт"})
    assert denied.status_code == 403, denied.text


def test_draft_only_mention_is_removed_with_the_future_product(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    """Позиция без количеств — не движение: её можно удалить, черновик очистится."""
    login("sales")
    future = _future(client)
    plan = _plan(client, TODAY.year + 1)
    client_id = str(catalog["customer"].id)
    saved = _save(
        client,
        plan["id"],
        items=[],
        clients=[client_id],
        rows=[(client_id, future["id"])],
    )
    assert saved.status_code == 200, saved.text

    listed = client.get("/api/v1/future-products").json()
    assert listed[0]["plans_count"] == 1
    assert listed[0]["rows_count"] == 1

    assert client.delete(f"/api/v1/future-products/{future['id']}").status_code == 204
    reloaded = client.get(f"/api/v1/sales-plans/{plan['id']}").json()
    assert reloaded["draft_rows"] == []
    assert [row["client_id"] for row in reloaded["draft_clients"]] == [client_id]


def test_used_future_cannot_be_deleted_and_binding_replaces_all_mentions(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    """Привязка заменяет позицию во всех строках, совпадения складываются."""
    login("sales")
    future = _future(client)
    target = catalog["fin"]
    plan = _plan(client, TODAY.year + 1)
    client_id = str(catalog["customer"].id)
    items = [
        {
            "client_id": client_id,
            "product_id": future["id"],
            "month": 3,
            "quantity": "10",
        },
        {
            "client_id": client_id,
            "product_id": str(target.id),
            "month": 3,
            "quantity": "4",
        },
    ]
    saved = _save(
        client,
        plan["id"],
        items=items,
        clients=[client_id],
        rows=[(client_id, future["id"]), (client_id, str(target.id))],
    )
    assert saved.status_code == 200, saved.text

    blocked = client.delete(f"/api/v1/future-products/{future['id']}")
    assert blocked.status_code == 409, blocked.text
    assert "Привяжите" in blocked.json()["detail"]

    denied = client.post(
        f"/api/v1/future-products/{future['id']}/bind",
        json={"product_id": str(target.id)},
    )
    assert denied.status_code == 403, denied.text

    login("commercial")
    bound = client.post(
        f"/api/v1/future-products/{future['id']}/bind",
        json={"product_id": str(target.id)},
    )
    assert bound.status_code == 200, bound.text
    body = bound.json()
    assert body["product_id"] == str(target.id)
    assert body["product_name"] == target.name
    assert body["plan_rows"] == 1
    assert body["plans"] == 1
    assert body["years"] == [TODAY.year + 1]

    reloaded = client.get(f"/api/v1/sales-plans/{plan['id']}").json()
    assert len(reloaded["items"]) == 1
    assert reloaded["items"][0]["product_id"] == str(target.id)
    assert reloaded["items"][0]["quantity"] == "14.000"
    assert {row["product_id"] for row in reloaded["draft_rows"]} == {str(target.id)}
    assert client.get("/api/v1/future-products").json() == []


def test_binding_is_blocked_while_correction_is_open(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    login("sales")
    future = _future(client)
    target = catalog["fin"]
    plan = _plan(client, TODAY.year + 1)
    manager = db_session.execute(select(User).where(User.login == "sales")).scalar_one()
    correction = SalesPlanCorrection(
        plan_id=UUID(plan["id"]), created_by_id=manager.id, status="draft"
    )
    db_session.add(correction)
    db_session.flush()
    db_session.add(
        SalesPlanCorrectionItem(
            correction_id=correction.id,
            client_id=catalog["customer"].id,
            product_id=UUID(future["id"]),
            month=3,
            quantity=Decimal("12"),
            current_quantity=Decimal("0"),
        )
    )
    db_session.commit()

    login("commercial")
    blocked = client.post(
        f"/api/v1/future-products/{future['id']}/bind",
        json={"product_id": str(target.id)},
    )
    assert blocked.status_code == 409, blocked.text
    assert "корректировк" in blocked.json()["detail"]


def test_commercial_without_directory_edit_still_manages_future_products(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Справочник может быть только на чтение — планирование всё равно работает."""
    db_session.add(
        RolePermission(
            role="commercial_director",
            block="directories",
            actions=["view"],
            scope="all",
        )
    )
    db_session.commit()
    login("commercial")

    created = client.post("/api/v1/future-products", json={"name": "Сок манго", "unit": "л"})
    assert created.status_code == 201, created.text
    assert created.json()["is_future"] is True
