"""Помесячный план продаж: окно 23 — последний день, причины и автозатверждение."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import SalesPlan, SalesPlanItem
from app.services import monthly_sales_plan_service as service
from app.services.monthly_sales_plan_service import window_bounds, window_state


def _freeze(monkeypatch: pytest.MonkeyPatch, value: date) -> None:
    class FakeDate(date):
        @classmethod
        def today(cls) -> FakeDate:
            return cls(value.year, value.month, value.day)

    monkeypatch.setattr(service, "date", FakeDate)


@pytest.fixture
def setup(db_session: Session, users: None) -> dict[str, Any]:
    sales = db_session.execute(select(User).where(User.login == "sales")).scalars().one()
    commercial = db_session.execute(select(User).where(User.login == "commercial")).scalars().one()
    product = Product(code="SKU-1", name="Изюм", kind="finished", unit="кг")
    product2 = Product(code="SKU-2", name="Курага", kind="finished", unit="кг")
    first = Counterparty(
        name="ООО Ромашка", name_key="ооо ромашка", is_customer=True, manager_id=sales.id
    )
    second = Counterparty(
        name="ООО Вектор", name_key="ооо вектор", is_customer=True, manager_id=sales.id
    )
    db_session.add_all([product, product2, first, second])
    db_session.flush()

    plan = SalesPlan(
        year=2026,
        manager_id=sales.id,
        created_by_id=commercial.id,
        status="approved",
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add_all(
        [
            SalesPlanItem(
                plan_id=plan.id,
                client_id=first.id,
                product_id=product.id,
                month=12,
                quantity=Decimal("100"),
            ),
            SalesPlanItem(
                plan_id=plan.id,
                client_id=first.id,
                product_id=product2.id,
                month=12,
                quantity=Decimal("50"),
            ),
            SalesPlanItem(
                plan_id=plan.id,
                client_id=second.id,
                product_id=product.id,
                month=12,
                quantity=Decimal("30"),
            ),
            # Январь: месячного плана нет, значит в сравнении он равен годовому.
            SalesPlanItem(
                plan_id=plan.id,
                client_id=first.id,
                product_id=product.id,
                month=1,
                quantity=Decimal("70"),
            ),
        ]
    )
    db_session.commit()
    return {
        "sales": sales,
        "commercial": commercial,
        "product": product,
        "product2": product2,
        "first": first,
        "second": second,
    }


def _plan(client: TestClient, *, year: int = 2026, month: int = 12) -> dict[str, Any]:
    response = client.get("/api/v1/monthly-sales-plans", params={"year": year, "month": month})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "client_id": item["client_id"],
            "product_id": item["product_id"],
            "quantity": item["quantity"],
            "reason": item["reason"],
        }
        for item in plan["items"]
    ]


def test_window_is_23_to_last_day_of_previous_month() -> None:
    assert window_bounds(2026, 12) == (date(2026, 11, 23), date(2026, 11, 30))
    assert window_bounds(2027, 1) == (date(2026, 12, 23), date(2026, 12, 31))
    assert window_bounds(2026, 3) == (date(2026, 2, 23), date(2026, 2, 28))

    assert window_state(2026, 12, today=date(2026, 11, 22)) == "not_started"
    assert window_state(2026, 12, today=date(2026, 11, 23)) == "open"
    assert window_state(2026, 12, today=date(2026, 11, 30)) == "open"
    assert window_state(2026, 12, today=date(2026, 12, 1)) == "closed"


def test_plan_copies_annual_and_change_requires_reason(
    client: TestClient,
    login,
    setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze(monkeypatch, date(2026, 11, 25))
    login("sales")

    plan = _plan(client)
    assert plan["status"] == "draft"
    assert plan["window_state"] == "open"
    assert plan["can_edit"] is True
    assert len(plan["items"]) == 3
    assert all(item["annual_quantity"] == item["quantity"] for item in plan["items"])

    items = _items(plan)
    items[0]["quantity"] = "110.000"
    items[0]["reason"] = None
    denied = client.put("/api/v1/monthly-sales-plans/2026/12", json={"items": items})
    assert denied.status_code == 400
    assert "причину" in denied.json()["detail"]

    items[0]["reason"] = "Клиент подтвердил доп. объём"
    saved = client.put("/api/v1/monthly-sales-plans/2026/12", json={"items": items})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["changed_lines"] == 1
    changed = next(item for item in body["items"] if item["quantity"] == "110.000")
    assert changed["reason"] == "Клиент подтвердил доп. объём"

    history = client.get("/api/v1/monthly-sales-plans/2026/12/history")
    assert history.status_code == 200, history.text
    events = history.json()
    assert len(events) == 1
    assert events[0]["kind"] == "edit"
    assert events[0]["new_quantity"] == "110.000"
    assert events[0]["reason"] == "Клиент подтвердил доп. объём"


def test_removed_and_new_positions_show_in_plan_fact(
    client: TestClient,
    login,
    setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze(monkeypatch, date(2026, 11, 25))
    login("sales")
    plan = _plan(client)
    items = _items(plan)
    removed = next(
        item
        for item in items
        if item["client_id"] == str(setup["first"].id)
        and item["product_id"] == str(setup["product2"].id)
    )
    removed["quantity"] = "0"
    removed["reason"] = "Сеть вывела позицию из торговой матрицы"
    items.append(
        {
            "client_id": str(setup["second"].id),
            "product_id": str(setup["product2"].id),
            "quantity": "40",
            "reason": "Новая позиция по запросу сети",
        }
    )
    saved = client.put("/api/v1/monthly-sales-plans/2026/12", json={"items": items})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert any(item["is_removed"] for item in body["items"])
    assert any(item["is_new"] for item in body["items"])

    login("commercial")
    approved = client.post(
        "/api/v1/monthly-sales-plans/2026/12/approve",
        params={"manager_id": str(setup["sales"].id)},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    detail = client.get("/api/v1/plan-fact/2026/12")
    assert detail.status_code == 200, detail.text
    rows = detail.json()["rows"]
    zero = next(
        row
        for row in rows
        if row["client_id"] == str(setup["first"].id)
        and row["product_id"] == str(setup["product2"].id)
    )
    assert zero["annual_quantity"] == "50.000"
    assert zero["monthly_quantity"] == "0.000"
    assert zero["fact_quantity"] == "0.000"
    assert zero["removed"] is True
    assert zero["plan_reason"] == "Сеть вывела позицию из торговой матрицы"

    fresh = next(
        row
        for row in rows
        if row["client_id"] == str(setup["second"].id)
        and row["product_id"] == str(setup["product2"].id)
    )
    assert fresh["is_new"] is True
    assert fresh["annual_quantity"] == "0.000"
    assert fresh["monthly_quantity"] == "40.000"


def test_unrevised_month_equals_annual_and_approved_plan_is_used_in_month_results(
    client: TestClient,
    login,
    setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze(monkeypatch, date(2026, 11, 25))
    login("sales")
    plan = _plan(client)
    items = _items(plan)
    target = next(
        item
        for item in items
        if item["client_id"] == str(setup["first"].id)
        and item["product_id"] == str(setup["product"].id)
    )
    target["quantity"] = "110.000"
    target["reason"] = "Клиент подтвердил доп. объём"
    assert (
        client.put("/api/v1/monthly-sales-plans/2026/12", json={"items": items}).status_code == 200
    )

    login("commercial")
    assert (
        client.post(
            "/api/v1/monthly-sales-plans/2026/12/approve",
            params={"manager_id": str(setup["sales"].id)},
        ).status_code
        == 200
    )

    summary = client.get("/api/v1/plan-fact", params={"year": 2026})
    assert summary.status_code == 200, summary.text
    months = {row["month"]: row for row in summary.json()["months"]}
    assert months[1]["monthly_state"] == "none"
    assert months[1]["monthly_quantity"] == months[1]["annual_quantity"]
    assert months[12]["monthly_state"] == "approved"
    assert months[12]["revised"] is True

    results = client.get("/api/v1/month-results", params={"year": 2026, "month": 12})
    assert results.status_code == 200, results.text
    row = next(
        row
        for row in results.json()["rows"]
        if row["client_id"] == str(setup["first"].id)
        and row["product_id"] == str(setup["product"].id)
    )
    assert row["plan_quantity"] == "110.000"


def test_closed_window_approves_automatically_and_blocks_edits(
    client: TestClient,
    login,
    setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze(monkeypatch, date(2026, 11, 25))
    login("sales")
    plan = _plan(client)
    items = _items(plan)
    items[0]["quantity"] = "90.000"
    items[0]["reason"] = "Сократили из-за остатков"
    assert (
        client.put("/api/v1/monthly-sales-plans/2026/12", json={"items": items}).status_code == 200
    )

    _freeze(monkeypatch, date(2027, 1, 5))
    closed = _plan(client)
    assert closed["status"] == "approved"
    assert closed["window_state"] == "closed"
    assert closed["approved_by_name"] is None
    assert closed["can_edit"] is False

    denied = client.put(
        "/api/v1/monthly-sales-plans/2026/12",
        json={
            "items": [
                {
                    "client_id": str(setup["first"].id),
                    "product_id": str(setup["product"].id),
                    "quantity": "1",
                }
            ]
        },
    )
    assert denied.status_code == 409
    assert "закрыто" in denied.json()["detail"]


def test_plan_is_not_opened_before_window(
    client: TestClient,
    login,
    setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze(monkeypatch, date(2026, 11, 10))
    login("sales")
    response = client.get("/api/v1/monthly-sales-plans", params={"year": 2026, "month": 12})
    assert response.status_code == 409
    assert "не открылось" in response.json()["detail"]


def test_manager_cannot_open_another_managers_plan(
    client: TestClient,
    login,
    setup: dict[str, Any],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze(monkeypatch, date(2026, 11, 25))
    other = db_session.execute(select(User).where(User.login == "sales2")).scalars().one()
    login("sales")
    response = client.get(
        "/api/v1/monthly-sales-plans",
        params={"year": 2026, "month": 12, "manager_id": str(other.id)},
    )
    assert response.status_code == 403
