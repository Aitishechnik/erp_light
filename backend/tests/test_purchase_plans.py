"""План закупок сырья на основании финально согласованного годового плана продаж."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty
from app.models.domain import Batch, BatchItem, Product, StockBalance
from app.models.planning import PurchasePlan
from app.services.purchase_need import (
    cover_group,
    cover_schedule,
    order_year_month,
    split_annual,
)

TODAY = date.today()
YEAR = TODAY.year + 1


def _sales_plan(
    client: TestClient,
    login,
    manager: str,
    product: Product,
    customer: Counterparty,
    month: int,
    quantity: str,
) -> str:
    login(manager)
    created = client.post("/api/v1/sales-plans", json={"year": YEAR})
    assert created.status_code == 201, created.text
    plan_id = str(created.json()["id"])
    saved = client.put(
        f"/api/v1/sales-plans/{plan_id}/items",
        json={
            "items": [
                {
                    "client_id": str(customer.id),
                    "product_id": str(product.id),
                    "month": month,
                    "quantity": quantity,
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert client.post(f"/api/v1/sales-plans/{plan_id}/submit").status_code == 200
    login("commercial")
    approved = client.post(f"/api/v1/sales-plans/{plan_id}/approve")
    assert approved.status_code == 200, approved.text
    return plan_id


def _make_annual(client: TestClient, login, catalog: dict[str, Any]) -> dict[str, str]:
    plan_ids = {
        "sales": _sales_plan(client, login, "sales", catalog["fin"], catalog["customer"], 1, "100"),
        "sales2": _sales_plan(
            client, login, "sales2", catalog["fin"], catalog["customer"], 2, "200"
        ),
        "sales3": _sales_plan(
            client, login, "sales3", catalog["fin2"], catalog["customer"], 1, "50"
        ),
    }
    login("commercial")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit").status_code == 200
    login("executive")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve").status_code == 200
    return plan_ids


def _resubmit_annual(client: TestClient, login) -> None:
    login("commercial")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit").status_code == 200
    login("executive")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve").status_code == 200


def _create_plan(client: TestClient, login) -> dict[str, Any]:
    login("purchase")
    response = client.post("/api/v1/purchase-plans", json={"year": YEAR})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _item(
    catalog: dict[str, Any],
    *,
    sales: str = "fin",
    raw: str = "raw",
    country: str = "thailand",
    quantity: str = "30",
    price: str | None = "500.00",
    supplier: str | None = "supplier",
) -> dict[str, Any]:
    return {
        "sales_product_id": str(catalog[sales].id),
        "product_id": str(catalog[raw].id),
        "country_id": str(catalog[country].id),
        "quantity": quantity,
        "price_rub": price,
        "supplier_id": str(catalog[supplier].id) if supplier else None,
    }


def _save(client: TestClient, plan_id: str, items: list[dict[str, Any]]) -> Any:
    return client.put(f"/api/v1/purchase-plans/{plan_id}/items", json={"items": items})


def _correct_sales(
    client: TestClient,
    login,
    plan_id: str,
    customer: Counterparty,
    product: Product,
    month: int,
    quantity: str,
) -> None:
    login("sales")
    created = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_id})
    assert created.status_code == 201, created.text
    correction_id = str(created.json()["id"])
    saved = client.put(
        f"/api/v1/sales-plan-corrections/{correction_id}/items",
        json={
            "items": [
                {
                    "client_id": str(customer.id),
                    "product_id": str(product.id),
                    "month": month,
                    "quantity": quantity,
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert client.post(f"/api/v1/sales-plan-corrections/{correction_id}/submit").status_code == 200
    login("commercial")
    approved = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve")
    assert approved.status_code == 200, approved.text


def test_plan_is_built_from_approved_annual_plan(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    login("purchase")
    missing = client.post("/api/v1/purchase-plans", json={"year": YEAR})
    assert missing.status_code == 409, missing.text
    assert "годового плана продаж" in missing.json()["detail"]

    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    assert plan["status"] == "draft"
    assert plan["source"]["state"] == "ok"
    assert plan["source"]["changes"] == []
    positions = {row["code"]: row for row in plan["positions"]}
    assert set(positions) == {"FIN-1", "FIN-2"}
    assert positions["FIN-1"]["total"] == "300.000"
    assert positions["FIN-1"]["months"] == [
        {"month": 1, "quantity": "100.000"},
        {"month": 2, "quantity": "200.000"},
    ]
    assert positions["FIN-1"]["decomposed"] is False
    assert positions["FIN-2"]["total"] == "50.000"
    assert plan["items"] == []

    duplicate = client.post("/api/v1/purchase-plans", json={"year": YEAR})
    assert duplicate.status_code == 409, duplicate.text


def test_raw_rows_split_by_months_and_lead_time(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="30", price="500.00")])
    assert saved.status_code == 200, saved.text
    body = saved.json()
    item = body["items"][0]
    assert item["product_code"] == "RAW-1"
    assert item["country_name"] == "Таиланд"
    assert item["delivery_days"] == 90
    assert item["quantity"] == "30.000"
    assert [(row["month"], row["quantity"]) for row in item["schedule"]] == [
        (1, "10.000"),
        (2, "20.000"),
    ]
    assert [(row["order_year"], row["order_month"]) for row in item["schedule"]] == [
        (YEAR - 1, 10),
        (YEAR - 1, 11),
    ]
    assert all(row["overdue"] is False for row in item["schedule"])
    # Пока ничего не пришло и остатка нет, покрытия нет: нужно докупить всё.
    assert [row["covered"] for row in item["schedule"]] == ["0.000", "0.000"]
    assert [row["share"] for row in item["schedule"]] == ["0.0", "0.0"]
    assert item["stock_quantity"] == "0"
    assert item["stock_date"] is None
    position = next(row for row in body["positions"] if row["code"] == "FIN-1")
    assert position["decomposed"] is True
    assert sum(Decimal(row["quantity"]) for row in item["schedule"]) == Decimal("30.000")

    # Вторая строка того же сырья из другой страны — свой срок и свой график.
    second = _save(
        client,
        plan["id"],
        [
            _item(catalog, raw="raw", country="thailand", quantity="20", price="500.00"),
            _item(catalog, raw="raw2", country="china", quantity="10", price="300.00"),
        ],
    )
    assert second.status_code == 200, second.text
    rows = second.json()["items"]
    assert {row["country_name"] for row in rows} == {"Таиланд", "Китай"}
    assert {row["delivery_days"] for row in rows} == {90, 65}
    assert len(rows) == 2


def test_rounding_keeps_annual_total(client: TestClient, login, catalog: dict[str, Any]) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, country="fast", quantity="10")])
    assert saved.status_code == 200, saved.text
    schedule = saved.json()["items"][0]["schedule"]
    assert [row["quantity"] for row in schedule] == ["3.333", "6.667"]
    assert sum(Decimal(row["quantity"]) for row in schedule) == Decimal("10.000")
    # Срок доставки 30 дней: январь заказываем в декабре прошлого года.
    assert (schedule[0]["order_year"], schedule[0]["order_month"]) == (YEAR - 1, 12)


@pytest.mark.parametrize(
    ("plan_year", "month", "delivery_days", "expected"),
    [
        (2027, 1, 0, (2027, 1)),
        (2027, 5, 30, (2027, 4)),
        (2027, 5, 31, (2027, 3)),
        (2027, 5, 60, (2027, 3)),
        (2027, 5, 65, (2027, 2)),
        (2027, 5, 90, (2027, 2)),
        (2027, 1, 90, (2026, 10)),
        (2027, 1, 365, (2025, 12)),
    ],
)
def test_order_year_month(
    plan_year: int, month: int, delivery_days: int, expected: tuple[int, int]
) -> None:
    assert order_year_month(plan_year, month, delivery_days) == expected


def test_split_annual_is_deterministic() -> None:
    months = {1: Decimal("100"), 2: Decimal("200"), 3: Decimal("100")}
    rows = split_annual(Decimal("20"), months, 90, 2027, today=date(2026, 10, 21))
    assert [row.quantity for row in rows] == [Decimal("5.000"), Decimal("10.000"), Decimal("5.000")]
    assert sum(row.quantity for row in rows) == Decimal("20")
    assert rows[0].overdue is False
    assert rows[0].order_month == 10
    assert rows[0].order_year == 2026


def test_coverage_caps_share_and_carries_surplus() -> None:
    """Пришло больше потребности месяца: 100 %, излишек идёт на следующие месяцы."""
    schedule = split_annual(
        Decimal("30"), {1: Decimal("100"), 2: Decimal("200")}, 90, 2027, today=date(2026, 10, 21)
    )
    rows = cover_schedule(schedule, {1: Decimal("50")})
    assert [row.need for row in rows] == [Decimal("10.000"), Decimal("20.000")]
    assert [row.covered for row in rows] == [Decimal("10.000"), Decimal("20.000")]
    assert [row.remaining for row in rows] == [Decimal("0.000"), Decimal("0.000")]
    assert [row.carry for row in rows] == [Decimal("40.000"), Decimal("20.000")]
    assert [row.share for row in rows] == [Decimal("100.0"), Decimal("100.0")]

    # Приход попадает в свой месяц: февральский не закрывает январскую потребность.
    late = cover_schedule(schedule, {2: Decimal("50")})
    assert [row.covered for row in late] == [Decimal("0"), Decimal("20.000")]
    assert late[0].remaining == Decimal("10.000")

    # Остаток на складе работает как приход первого месяца.
    stock = cover_schedule(schedule, {}, Decimal("12"))
    assert [row.covered for row in stock] == [Decimal("10.000"), Decimal("2.000")]
    assert stock[1].remaining == Decimal("18.000")
    assert stock[-1].carry == Decimal("0")


def test_coverage_counts_our_arrivals_only(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Покрытие считаем по своим приходам: остаток на складе — только справка."""
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="30", price="500.00")])
    assert saved.status_code == 200, saved.text
    item_id = saved.json()["items"][0]["id"]

    stock_day = date(2026, 10, 28)
    batch = Batch(
        batch_number="ИТ-2027-0001",
        batch_date=date(2026, 12, 11),
        currency="RUB",
        source="1c",
    )
    early = Batch(
        batch_number="ИТ-2026-0099",
        batch_date=date(2026, 10, 1),
        currency="RUB",
        source="1c",
    )
    db_session.add_all([batch, early])
    db_session.flush()
    db_session.add_all(
        [
            BatchItem(
                batch_id=batch.id,
                product_id=catalog["raw"].id,
                quantity=Decimal("25"),
                purchase_plan_item_id=item_id,
            ),
            BatchItem(
                batch_id=early.id,
                product_id=catalog["raw"].id,
                quantity=Decimal("5"),
                purchase_plan_item_id=item_id,
            ),
            StockBalance(
                product_id=catalog["raw"].id,
                balance_date=stock_day,
                opening=Decimal("8"),
                income=Decimal("8"),
                outcome=Decimal("0"),
                closing=Decimal("8"),
            ),
        ]
    )
    db_session.commit()

    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    item = body["items"][0]
    # Остаток склада показываем, но в покрытие он не идёт.
    assert item["stock_quantity"] == "8.000"
    assert item["stock_date"] == stock_day.isoformat()
    assert item["fact_quantity"] == "30.000"

    schedule = item["schedule"]
    assert [row["quantity"] for row in schedule] == ["10.000", "20.000"]
    assert [row["covered"] for row in schedule] == ["10.000", "20.000"]
    assert [row["share"] for row in schedule] == ["100.0", "100.0"]
    assert [row["remaining"] for row in schedule] == ["0.000", "0.000"]
    assert [row["carry"] for row in schedule] == ["20.000", "0.000"]
    assert item["carry_forward"] == "0.000"


def test_cover_group_shares_the_arrival_between_rows() -> None:
    """Один приход закрывает потребность всех строк одного сырья."""
    first = split_annual(
        Decimal("30"), {1: Decimal("100"), 2: Decimal("200")}, 90, 2027, today=date(2026, 10, 21)
    )
    second = split_annual(Decimal("15"), {1: Decimal("50")}, 65, 2027, today=date(2026, 10, 21))
    shared = cover_group({"first": first, "second": second}, {1: Decimal("40")})

    # Январь: нужно 10 + 15, пришло 40 — закрываем всё, излишек 15 идёт в февраль.
    assert [(row.need, row.covered, row.carry) for row in shared["first"]] == [
        (Decimal("10.000"), Decimal("10.000"), Decimal("15.000")),
        (Decimal("20.000"), Decimal("15.000"), Decimal("0")),
    ]
    assert shared["first"][1].remaining == Decimal("5.000")
    assert [(row.need, row.covered, row.share) for row in shared["second"]] == [
        (Decimal("15.000"), Decimal("15.000"), Decimal("100.0")),
    ]

    # Не хватает на всех: делим пропорционально потребности месяца.
    tight = cover_group(
        {
            "a": split_annual(Decimal("10"), {1: Decimal("10")}, 0, 2027),
            "b": split_annual(Decimal("10"), {1: Decimal("10")}, 0, 2027),
            "c": split_annual(Decimal("10"), {1: Decimal("10")}, 0, 2027),
        },
        {1: Decimal("10")},
    )
    assert [tight[key][0].covered for key in ("a", "b", "c")] == [
        Decimal("3.334"),
        Decimal("3.333"),
        Decimal("3.333"),
    ]
    assert sum(row[0].covered for row in tight.values()) == Decimal("10.000")


def test_coverage_is_shared_by_raw_material(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Партия, привязанная к одной строке, перекрывает все позиции с этим сырьём."""
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(
        client,
        plan["id"],
        [
            _item(catalog, sales="fin", raw="raw", quantity="30"),
            _item(catalog, sales="fin2", raw="raw", quantity="15", country="china"),
        ],
    )
    assert saved.status_code == 200, saved.text
    items = {item["sales_product_id"]: item for item in saved.json()["items"]}
    first_id = items[str(catalog["fin"].id)]["id"]

    batch = Batch(
        batch_number="ИТ-2027-0100",
        batch_date=date(YEAR, 1, 15),
        currency="RUB",
        source="1c",
    )
    db_session.add(batch)
    db_session.flush()
    db_session.add(
        BatchItem(
            batch_id=batch.id,
            product_id=catalog["raw"].id,
            quantity=Decimal("40"),
            purchase_plan_item_id=first_id,
        )
    )
    db_session.commit()

    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    items = {item["sales_product_id"]: item for item in body["items"]}
    first = items[str(catalog["fin"].id)]
    second = items[str(catalog["fin2"].id)]

    # Приход лежит только на первой строке, но закрывает и вторую позицию.
    assert first["fact_quantity"] == "40.000"
    assert second["fact_quantity"] == "0"
    assert [(row["quantity"], row["covered"]) for row in first["schedule"]] == [
        ("10.000", "10.000"),
        ("20.000", "15.000"),
    ]
    assert first["schedule"][1]["remaining"] == "5.000"
    assert [(row["quantity"], row["covered"]) for row in second["schedule"]] == [
        ("15.000", "15.000"),
    ]
    assert second["schedule"][0]["share"] == "100.0"
    assert (first["carry_forward"], second["carry_forward"]) == ("0.000", "0.000")
    # В сумме по строкам перекрыто ровно то, что пришло: 40 из 45.
    covered = sum(Decimal(row["covered"]) for item in (first, second) for row in item["schedule"])
    assert covered == Decimal("40.000")


def test_validation_keeps_previous_rows(client: TestClient, login, catalog: dict[str, Any]) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    assert _save(client, plan["id"], [_item(catalog)]).status_code == 200

    material = _save(client, plan["id"], [_item(catalog, raw="material")])
    assert material.status_code == 400, material.text
    assert "не сырьё" in material.json()["detail"]

    inactive = _save(client, plan["id"], [_item(catalog, raw="inactive_raw")])
    assert inactive.status_code == 400, inactive.text
    assert "отключён" in inactive.json()["detail"]

    inactive_country = _save(client, plan["id"], [_item(catalog, country="inactive_country")])
    assert inactive_country.status_code == 400, inactive_country.text
    assert "отключена" in inactive_country.json()["detail"]

    wrong_supplier = _save(client, plan["id"], [_item(catalog, supplier="customer")])
    assert wrong_supplier.status_code == 400, wrong_supplier.text
    assert "не отмечен поставщиком" in wrong_supplier.json()["detail"]

    foreign_position = _save(client, plan["id"], [_item(catalog, sales="raw")])
    assert foreign_position.status_code == 400, foreign_position.text
    assert "нет в плане продаж" in foreign_position.json()["detail"]

    # Отклонённые правки не стёрли прежнюю строку.
    current = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    assert len(current["items"]) == 1


def test_roles_approval_and_revision_request(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    assert _save(client, plan["id"], [_item(catalog)]).status_code == 200

    login("sales")
    assert client.get("/api/v1/purchase-plans").status_code == 403
    login("commercial")
    assert client.get("/api/v1/purchase-plans").status_code == 403
    login("executive")
    assert client.get("/api/v1/purchase-plans").status_code == 200
    assert _save(client, plan["id"], []).status_code == 403
    assert client.post(f"/api/v1/purchase-plans/{plan['id']}/approve").status_code == 409

    login("purchase")
    assert client.post(f"/api/v1/purchase-plans/{plan['id']}/submit").status_code == 200
    login("executive")
    approved = client.post(f"/api/v1/purchase-plans/{plan['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by_name"] == "Исполнительный директор (демо)"

    # Пересмотр запрашивает директор по закупкам, возвращает в работу ГД.
    login("purchase")
    requested = client.post(f"/api/v1/purchase-plans/{plan['id']}/request-revision", json={})
    assert requested.status_code == 200, requested.text
    assert requested.json()["source"]["revision_requested_at"] is not None
    assert requested.json()["source"]["revision_requested_by_name"] == "Директор по закупкам (демо)"

    login("executive")
    reopened = client.post(
        f"/api/v1/purchase-plans/{plan['id']}/reopen", json={"reason": "план продаж изменился"}
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "draft"
    assert reopened.json()["source"]["revision_requested_at"] is None

    login("import")
    assert client.delete(f"/api/v1/purchase-plans/{plan['id']}").status_code == 403
    login("purchase")
    assert client.delete(f"/api/v1/purchase-plans/{plan['id']}").status_code == 204


def test_source_revision_diff_and_acknowledge(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    plan_ids = _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    assert _save(client, plan["id"], [_item(catalog)]).status_code == 200

    _correct_sales(client, login, plan_ids["sales"], catalog["customer"], catalog["fin"], 1, "150")

    # Пока годовой план не согласован заново, показываем снимок и мягкий статус.
    login("purchase")
    revision = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    assert revision["source"]["state"] == "revision"
    assert revision["source"]["changes"] == []
    assert revision["positions"][0]["total"] == "300.000"

    _resubmit_annual(client, login)

    login("purchase")
    changed = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    assert changed["source"]["state"] == "changed"
    assert changed["source"]["title"] == "План продаж пересмотрен после составления плана закупок"
    assert changed["source"]["changes"] == [
        {
            "product_id": str(catalog["fin"].id),
            "code": "FIN-1",
            "name": "Смесь ореховая",
            "unit": "шт",
            "month": 1,
            "was": "100.000",
            "now": "150.000",
            "kind": "changed",
        }
    ]
    position = next(row for row in changed["positions"] if row["code"] == "FIN-1")
    assert position["changed"] is True
    assert position["total"] == "350.000"

    blocked = client.post(f"/api/v1/purchase-plans/{plan['id']}/submit")
    assert blocked.status_code == 409, blocked.text
    assert "примите изменения" in blocked.json()["detail"]

    acknowledged = client.post(f"/api/v1/purchase-plans/{plan['id']}/acknowledge-source")
    assert acknowledged.status_code == 200, acknowledged.text
    body = acknowledged.json()
    assert body["source"]["state"] == "ok"
    assert body["source"]["changes"] == []
    assert len(body["source"]["history"]) == 1
    assert body["source"]["history"][0]["acknowledged_by_name"] == "Директор по закупкам (демо)"
    assert body["source"]["history"][0]["changes"][0]["was"] == "100.000"
    assert body["source"]["history"][0]["changes"][0]["now"] == "150.000"

    assert client.post(f"/api/v1/purchase-plans/{plan['id']}/submit").status_code == 200


def test_previous_year_is_read_only(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    row = db_session.get(PurchasePlan, plan["id"])
    assert row is not None
    row.year = TODAY.year - 1
    db_session.commit()

    denied = _save(client, plan["id"], [])
    assert denied.status_code == 409, denied.text
    assert "Год прошёл" in denied.json()["detail"]


def test_import_manager_also_fills_plan(client: TestClient, login, catalog: dict[str, Any]) -> None:
    _make_annual(client, login, catalog)
    login("import")
    created = client.post("/api/v1/purchase-plans", json={"year": YEAR})
    assert created.status_code == 201, created.text
    plan_id = str(created.json()["id"])
    assert _save(client, plan_id, [_item(catalog)]).status_code == 200
    assert client.post(f"/api/v1/purchase-plans/{plan_id}/submit").status_code == 200
