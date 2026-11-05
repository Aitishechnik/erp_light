"""План закупок сырья на основании финально согласованного годового плана продаж."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.counterparties import Counterparty
from app.models.domain import Batch, BatchItem, Product
from app.models.planning import (
    PurchasePlan,
    PurchasePlanItem,
    SalesPlanApproval,
    SalesPlanItem,
)
from app.services.purchase_need import (
    cover_family,
    cover_group,
    cover_schedule,
    order_year_month,
    split_annual,
)
from app.services.sales_plan_approval_service import current_hash
from tests.test_month_results import sales_xlsx, upload_sales

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


def _make_annual_rows(
    client: TestClient,
    login,
    catalog: dict[str, Any],
    rows: list[tuple[str, str, int, str]],
) -> None:
    """Годовой план из явных строк (менеджер, товар, месяц, количество)."""
    for manager, product, month, quantity in rows:
        _sales_plan(client, login, manager, catalog[product], catalog["customer"], month, quantity)
    login("commercial")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit").status_code == 200
    login("executive")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve").status_code == 200


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
    alternative_of: str | None = None,
    norm: str | None = None,
) -> dict[str, Any]:
    payload = {
        "sales_product_id": str(catalog[sales].id),
        "product_id": str(catalog[raw].id),
        "country_id": str(catalog[country].id),
        "quantity": quantity,
        "price_rub": price,
    }
    if norm is not None:
        payload["norm"] = norm
    if alternative_of is not None:
        payload["alternative_of_id"] = alternative_of
    return payload


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
    # Просроченность зависит от сегодняшней даты: сверяем с ней, а не с «нет».
    today = date.today()
    assert [row["overdue"] for row in item["schedule"]] == [
        (today.year, today.month) > (YEAR - 1, 10),
        (today.year, today.month) > (YEAR - 1, 11),
    ]
    # Пока ничего не пришло и остатка нет, покрытия нет: нужно докупить всё.
    assert [row["covered"] for row in item["schedule"]] == ["0.000", "0.000"]
    assert [row["share"] for row in item["schedule"]] == ["0.0", "0.0"]
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
    """Покрытие считаем только по приходам, привязанным к плану."""
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="30", price="500.00")])
    assert saved.status_code == 200, saved.text
    item_id = saved.json()["items"][0]["id"]

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
        ]
    )
    db_session.commit()

    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    item = body["items"][0]
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


def test_coverage_uses_arrival_in_month_without_need() -> None:
    """Приход в месяц без потребности ждёт ближайшую потребность, а не теряется."""
    schedule = split_annual(
        Decimal("30"), {1: Decimal("100"), 3: Decimal("200")}, 0, 2027, today=date(2026, 10, 21)
    )
    rows = cover_schedule(schedule, {2: Decimal("15")})

    # Январь без прихода, февральский приход закрывает март.
    assert [(row.month, row.covered, row.remaining) for row in rows] == [
        (1, Decimal("0.000"), Decimal("10.000")),
        (3, Decimal("15.000"), Decimal("5.000")),
    ]
    assert rows[-1].carry == Decimal("0")


def test_coverage_uses_arrival_before_first_need() -> None:
    """Январский приход закрывает потребность марта."""
    schedule = split_annual(Decimal("10"), {3: Decimal("100")}, 0, 2027, today=date(2026, 10, 21))
    rows = cover_schedule(schedule, {1: Decimal("6")})

    assert rows[0].month == 3
    assert rows[0].covered == Decimal("6.000")
    assert rows[0].remaining == Decimal("4.000")


def test_coverage_keeps_arrival_after_last_need_in_carry() -> None:
    """Приход после последнего месяца потребности — излишек, а не потеря."""
    schedule = split_annual(
        Decimal("30"), {1: Decimal("100"), 2: Decimal("200")}, 0, 2027, today=date(2026, 10, 21)
    )
    entries, _used, left = cover_family({"main": schedule}, [], {"main": {3: Decimal("12")}})

    assert [row.covered for row in entries["main"]] == [Decimal("0"), Decimal("0")]
    assert left == Decimal("12.000")


def test_leftover_of_one_row_covers_another_row_later() -> None:
    """Излишек января на позиции A закрывает февраль позиции B."""
    first = split_annual(Decimal("10"), {1: Decimal("100")}, 0, 2027, today=date(2026, 10, 21))
    second = split_annual(Decimal("10"), {2: Decimal("100")}, 0, 2027, today=date(2026, 10, 21))

    entries, _used, left = cover_family(
        {"first": first, "second": second}, [], {"first": {1: Decimal("20")}}
    )

    assert entries["first"][0].covered == Decimal("10.000")
    assert entries["first"][0].carry == Decimal("10.000")
    assert entries["second"][0].month == 2
    assert entries["second"][0].covered == Decimal("10.000")
    assert entries["second"][0].remaining == Decimal("0")
    assert left == Decimal("0")


def test_other_row_stock_is_used_before_alternative() -> None:
    """Запас основной строки без потребности месяца тратится раньше альтернативы."""
    late = split_annual(Decimal("10"), {3: Decimal("100")}, 0, 2027, today=date(2026, 10, 21))
    early = split_annual(Decimal("10"), {1: Decimal("100")}, 0, 2027, today=date(2026, 10, 21))

    entries, used, left = cover_family(
        {"late": late, "early": early},
        ["alt"],
        {"late": {1: Decimal("20")}, "alt": {1: Decimal("10")}},
    )

    # Январь закрыт запасом строки «late», альтернатива не тронута.
    assert entries["early"][0].covered == Decimal("10.000")
    assert used["alt"] == {}
    # В марте своя потребность «late» тоже закрыта тем же запасом.
    assert entries["late"][0].covered == Decimal("10.000")
    assert left == Decimal("10.000")


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


def test_receipt_in_gap_month_covers_later_need(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Февральский приход закрывает мартовскую потребность, а не теряется."""
    _make_annual_rows(
        client,
        login,
        catalog,
        [("sales", "fin", 1, "100"), ("sales2", "fin", 3, "100"), ("sales3", "fin2", 1, "50")],
    )
    plan = _create_plan(client, login)
    saved = _save(
        client,
        plan["id"],
        [
            _item(catalog, sales="fin", raw="raw", quantity="30"),
            _item(catalog, sales="fin2", raw="raw2", quantity="10"),
        ],
    )
    assert saved.status_code == 200, saved.text
    fin = next(
        row for row in saved.json()["items"] if row["sales_product_id"] == str(catalog["fin"].id)
    )

    _arrive(db_session, catalog, fin["id"], "20", date(YEAR, 2, 15), product="raw")

    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    row = next(item for item in body["items"] if item["id"] == fin["id"])
    assert row["fact_quantity"] == "20.000"
    assert [
        (entry["month"], entry["covered"], entry["remaining"]) for entry in row["schedule"]
    ] == [(1, "0.000", "15.000"), (3, "15.000", "0.000")]
    assert row["carry_forward"] == "5.000"


def test_leftover_of_one_position_covers_another_position(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Излишек января на одной позиции закрывает февраль другой."""
    _make_annual_rows(
        client,
        login,
        catalog,
        [
            ("sales", "fin", 1, "100"),
            ("sales2", "fin2", 2, "100"),
            ("sales3", "fin2", 2, "100"),
        ],
    )
    plan = _create_plan(client, login)
    saved = _save(
        client,
        plan["id"],
        [
            _item(catalog, sales="fin", raw="raw", quantity="10"),
            _item(catalog, sales="fin2", raw="raw", quantity="10"),
        ],
    )
    assert saved.status_code == 200, saved.text
    first = next(
        row for row in saved.json()["items"] if row["sales_product_id"] == str(catalog["fin"].id)
    )

    _arrive(db_session, catalog, first["id"], "20", date(YEAR, 1, 15), product="raw")

    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    first_row = next(item for item in body["items"] if item["id"] == first["id"])
    second_row = next(item for item in body["items"] if item["id"] != first["id"])

    assert [(entry["month"], entry["covered"]) for entry in first_row["schedule"]] == [
        (1, "10.000")
    ]
    assert first_row["schedule"][0]["carry"] == "10.000"
    assert [(entry["month"], entry["covered"]) for entry in second_row["schedule"]] == [
        (2, "10.000")
    ]
    assert second_row["schedule"][0]["remaining"] == "0.000"
    assert first_row["carry_forward"] == "0.000"
    assert second_row["carry_forward"] == "0.000"


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

    foreign_position = _save(client, plan["id"], [_item(catalog, sales="raw")])
    assert foreign_position.status_code == 400, foreign_position.text
    assert "нет в плане продаж" in foreign_position.json()["detail"]

    # Отклонённые правки не стёрли прежнюю строку.
    current = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    assert len(current["items"]) == 1


def test_stale_plan_version_is_rejected(client: TestClient, login, catalog: dict[str, Any]) -> None:
    """Старая форма не должна затирать правки, сохранённые после её открытия."""
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="30")])
    assert saved.status_code == 200, saved.text
    version = saved.json()["updated_at"]
    item = saved.json()["items"][0]

    current = _item(catalog, quantity="40")
    current["id"] = item["id"]
    ok = client.put(
        f"/api/v1/purchase-plans/{plan['id']}/items",
        json={"items": [current], "version": version},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["updated_at"] != version

    stale = _item(catalog, quantity="50")
    stale["id"] = item["id"]
    rejected = client.put(
        f"/api/v1/purchase-plans/{plan['id']}/items",
        json={"items": [stale], "version": version},
    )
    assert rejected.status_code == 409, rejected.text
    assert "обновите страницу" in rejected.json()["detail"]
    # Строка осталась той, что сохранил первый запрос.
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    assert body["items"][0]["quantity"] == "40.000"


def test_identical_rows_are_rejected(client: TestClient, login, catalog: dict[str, Any]) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    duplicated = _save(
        client, plan["id"], [_item(catalog, quantity="30"), _item(catalog, quantity="30")]
    )
    assert duplicated.status_code == 400, duplicated.text
    assert "уже есть" in duplicated.json()["detail"]


def test_same_raw_with_another_price_is_allowed(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    """Контракт разрешает несколько строк одного сырья с разными ценами."""
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(
        client,
        plan["id"],
        [
            _item(catalog, quantity="30", price="500.00"),
            _item(catalog, quantity="20", price="600.00"),
        ],
    )
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["items"]) == 2


def test_plan_has_max_quantity_and_price(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    huge_qty = _save(client, plan["id"], [_item(catalog, quantity="1000000000000000")])
    assert huge_qty.status_code == 422, huge_qty.text
    huge_price = _save(client, plan["id"], [_item(catalog, price="1000000000000000")])
    assert huge_price.status_code == 422, huge_price.text


def test_delivery_days_is_a_snapshot_until_country_changes(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="30")])
    item = saved.json()["items"][0]
    assert item["delivery_days"] == 90

    login("purchase")
    patched = client.patch(
        f"/api/v1/countries/{catalog['thailand'].id}", json={"delivery_days": 10}
    )
    assert patched.status_code == 200, patched.text

    same_country = _save(
        client,
        plan["id"],
        [{**_item(catalog, quantity="40"), "id": item["id"]}],
    )
    assert same_country.status_code == 200, same_country.text
    assert same_country.json()["items"][0]["delivery_days"] == 90

    other_country = _save(
        client,
        plan["id"],
        [{**_item(catalog, country="china", quantity="40"), "id": item["id"]}],
    )
    assert other_country.status_code == 200, other_country.text
    assert other_country.json()["items"][0]["delivery_days"] == 65


def test_acknowledge_source_is_forbidden_for_approved_plan(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    assert _save(client, plan["id"], [_item(catalog, quantity="30")]).status_code == 200
    login("purchase")
    assert client.post(f"/api/v1/purchase-plans/{plan['id']}/submit").status_code == 200
    login("executive")
    assert client.post(f"/api/v1/purchase-plans/{plan['id']}/approve").status_code == 200
    login("purchase")
    rejected = client.post(f"/api/v1/purchase-plans/{plan['id']}/acknowledge-source")
    assert rejected.status_code == 409, rejected.text
    assert "запросите пересмотр" in rejected.json()["detail"]


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
    # Администратор ведёт план наравне с закупщиками.
    assert _save(client, plan["id"], [_item(catalog, quantity="40")]).status_code == 200
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
    # Администратор удаляет черновик; проверяем и штатное удаление закупщиком.
    login("executive")
    assert client.delete(f"/api/v1/purchase-plans/{plan['id']}").status_code == 204
    recreated = _create_plan(client, login)
    login("purchase")
    assert client.delete(f"/api/v1/purchase-plans/{recreated['id']}").status_code == 204


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


def test_removed_position_keeps_snapshot_schedule(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Сервер и интерфейс показывают для исчезнувшей позиции одно и то же."""
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(
        client,
        plan["id"],
        [
            _item(catalog, sales="fin", raw="raw", quantity="30"),
            _item(catalog, sales="fin2", raw="raw2", quantity="10"),
        ],
    )
    assert saved.status_code == 200, saved.text

    db_session.execute(delete(SalesPlanItem).where(SalesPlanItem.product_id == catalog["fin"].id))
    approval = db_session.execute(
        select(SalesPlanApproval).where(SalesPlanApproval.year == YEAR)
    ).scalar_one()
    approval.source_hash = current_hash(db_session, YEAR)
    db_session.commit()

    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    fin = next(row for row in body["items"] if row["sales_product_id"] == str(catalog["fin"].id))
    position = next(row for row in body["positions"] if row["product_id"] == str(catalog["fin"].id))
    assert position["status"] == "removed"
    assert [(row["month"], row["quantity"]) for row in fin["schedule"]] == [
        (1, "10.000"),
        (2, "20.000"),
    ]


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


def _with_alternative(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """План: основная строка и альтернатива из другой страны, без приходов."""
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, sales="fin", raw="raw", quantity="30")])
    assert saved.status_code == 200, saved.text
    main = saved.json()["items"][0]
    main_item = _item(catalog, sales="fin", raw="raw", quantity="30")
    main_item["id"] = main["id"]
    saved = _save(
        client,
        plan["id"],
        [
            main_item,
            _item(
                catalog,
                sales="fin",
                raw="raw2",
                country="china",
                quantity="15",
                alternative_of=main["id"],
            ),
        ],
    )
    assert saved.status_code == 200, saved.text
    items = saved.json()["items"]
    alternative = next(row for row in items if row["alternative_of_id"] == main["id"])
    return plan, main, alternative


def _arrive(
    db_session: Session,
    catalog: dict[str, Any],
    plan_item_id: str,
    quantity: str,
    day: date,
    product: str = "raw2",
) -> None:
    batch = Batch(
        batch_number=f"ИТ-{plan_item_id[:8]}", batch_date=day, currency="RUB", source="1c"
    )
    db_session.add(batch)
    db_session.flush()
    db_session.add(
        BatchItem(
            batch_id=batch.id,
            product_id=catalog[product].id,
            quantity=Decimal(quantity),
            purchase_plan_item_id=plan_item_id,
        )
    )
    db_session.commit()


def test_alternative_covers_main_shortfall(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Приход альтернативы закрывает потребность основной строки по месяцам."""
    plan, main, alternative = _with_alternative(client, login, catalog, db_session)
    assert alternative["schedule"] == []
    assert alternative["quantity"] == "15.000"

    _arrive(db_session, catalog, alternative["id"], "12", date(YEAR, 1, 15))
    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    items = {row["id"]: row for row in body["items"]}
    main_row = items[main["id"]]
    alt_row = items[alternative["id"]]

    # Январь закрыт целиком, в феврале альтернативы хватило на 2 из 20.
    assert [(row["month"], row["covered"]) for row in main_row["schedule"]] == [
        (1, "10.000"),
        (2, "2.000"),
    ]
    assert main_row["schedule"][1]["remaining"] == "18.000"
    # Своей потребности у альтернативы нет, видно только её расход.
    assert alt_row["fact_quantity"] == "12.000"
    assert alt_row["used_quantity"] == "12.000"
    assert [(row["month"], row["quantity"]) for row in alt_row["used_months"]] == [
        (1, "10.000"),
        (2, "2.000"),
    ]


def test_main_arrivals_are_spent_before_alternative(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Если основного хватает, альтернатива остаётся в запасе."""
    plan, main, alternative = _with_alternative(client, login, catalog, db_session)
    _arrive(db_session, catalog, main["id"], "30", date(YEAR, 1, 15), product="raw")
    _arrive(db_session, catalog, alternative["id"], "15", date(YEAR, 1, 15))
    login("purchase")

    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    items = {row["id"]: row for row in body["items"]}
    main_row = items[main["id"]]
    alt_row = items[alternative["id"]]
    assert [row["covered"] for row in main_row["schedule"]] == ["10.000", "20.000"]
    assert [row["share"] for row in main_row["schedule"]] == ["100.0", "100.0"]
    assert alt_row["used_quantity"] == "0"
    assert alt_row["used_months"] == []
    assert main_row["carry_forward"] == "15.000"  # альтернатива ждёт следующего месяца


def test_alternative_must_be_for_the_same_position(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, sales="fin", raw="raw")])
    main_id = saved.json()["items"][0]["id"]
    main_item = _item(catalog, sales="fin", raw="raw")
    main_item["id"] = main_id
    wrong = _save(
        client,
        plan["id"],
        [
            main_item,
            _item(catalog, sales="fin2", raw="raw2", alternative_of=main_id),
        ],
    )
    assert wrong.status_code == 400, wrong.text
    assert "той же позиции" in wrong.json()["detail"]

    # Альтернатива не может ссылаться на альтернативу.
    saved = _save(
        client,
        plan["id"],
        [
            main_item,
            _item(catalog, sales="fin", raw="raw2", alternative_of=main_id),
        ],
    )
    assert saved.status_code == 200, saved.text
    alt_id = next(row["id"] for row in saved.json()["items"] if row["alternative_of_id"] == main_id)
    nested = _save(
        client,
        plan["id"],
        [
            main_item,
            {**_item(catalog, sales="fin", raw="raw2", alternative_of=main_id), "id": alt_id},
            _item(catalog, sales="fin", raw="raw", alternative_of=alt_id),
        ],
    )
    assert nested.status_code == 400, nested.text
    assert "не может быть основной" in nested.json()["detail"]


def test_alternative_units_must_match(
    client: TestClient,
    login,
    catalog: dict[str, Any],
    db_session: Session,
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, sales="fin", raw="raw", quantity="30")])
    main = saved.json()["items"][0]
    main_item = _item(catalog, sales="fin", raw="raw", quantity="30")
    main_item["id"] = main["id"]

    pieces = Product(code="RAW-PCS", name="Кокос, шт", kind="raw", unit="шт")
    db_session.add(pieces)
    db_session.commit()
    catalog["raw_pcs"] = pieces

    wrong = _save(
        client,
        plan["id"],
        [
            main_item,
            _item(
                catalog,
                sales="fin",
                raw="raw_pcs",
                country="china",
                quantity="15",
                alternative_of=main["id"],
            ),
        ],
    )
    assert wrong.status_code == 400, wrong.text
    assert "разные единицы" in wrong.json()["detail"]


def test_linked_alternative_cannot_be_removed(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """У альтернативы с поступлением привязка не должна пропадать молча."""
    plan, main, alternative = _with_alternative(client, login, catalog, db_session)
    _arrive(db_session, catalog, alternative["id"], "12", date(YEAR, 1, 15))
    login("purchase")

    main_item = _item(catalog, sales="fin", raw="raw", quantity="30")
    main_item["id"] = main["id"]
    removed = _save(client, plan["id"], [main_item])
    assert removed.status_code == 409, removed.text
    assert "нельзя убрать" in removed.json()["detail"]

    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    alt_row = next(row for row in body["items"] if row["id"] == alternative["id"])
    assert alt_row["fact_quantity"] == "12.000"


def test_alternative_cycle_is_rejected(client: TestClient, login, catalog: dict[str, Any]) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(
        client,
        plan["id"],
        [
            _item(catalog, sales="fin", raw="raw", quantity="30"),
            _item(catalog, sales="fin", raw="raw2", country="china", quantity="20"),
        ],
    )
    assert saved.status_code == 200, saved.text
    first, second = saved.json()["items"]

    cycle = _save(
        client,
        plan["id"],
        [
            {
                **_item(catalog, sales="fin", raw="raw", quantity="30"),
                "id": first["id"],
                "alternative_of_id": second["id"],
            },
            {
                **_item(catalog, sales="fin", raw="raw2", country="china", quantity="20"),
                "id": second["id"],
                "alternative_of_id": first["id"],
            },
        ],
    )
    assert cycle.status_code == 400, cycle.text
    assert "не может быть основной" in cycle.json()["detail"]


def test_alternative_cannot_reference_itself(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, sales="fin", raw="raw", quantity="30")])
    item = saved.json()["items"][0]
    self_ref = _save(
        client,
        plan["id"],
        [
            {
                **_item(catalog, sales="fin", raw="raw", quantity="30"),
                "id": item["id"],
                "alternative_of_id": item["id"],
            }
        ],
    )
    assert self_ref.status_code == 400, self_ref.text
    assert "саму себя" in self_ref.json()["detail"]


def test_alternative_target_cannot_move_to_another_position(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, sales="fin", raw="raw", quantity="30")])
    main = saved.json()["items"][0]
    with_alt = _save(
        client,
        plan["id"],
        [
            {**_item(catalog, sales="fin", raw="raw", quantity="30"), "id": main["id"]},
            _item(
                catalog,
                sales="fin",
                raw="raw2",
                country="china",
                quantity="15",
                alternative_of=main["id"],
            ),
        ],
    )
    assert with_alt.status_code == 200, with_alt.text
    alt = next(row for row in with_alt.json()["items"] if row["alternative_of_id"] == main["id"])

    moved = _save(
        client,
        plan["id"],
        [
            {**_item(catalog, sales="fin2", raw="raw", quantity="30"), "id": main["id"]},
            {
                **_item(
                    catalog,
                    sales="fin",
                    raw="raw2",
                    country="china",
                    quantity="15",
                    alternative_of=main["id"],
                ),
                "id": alt["id"],
            },
        ],
    )
    assert moved.status_code == 400, moved.text
    assert "той же позиции" in moved.json()["detail"]


def test_removing_main_promotes_alternative(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    plan, main, alternative = _with_alternative(client, login, catalog, db_session)
    # Прислать альтернативу без основной строки нельзя: её сначала надо повысить.
    kept_alt = _save(
        client,
        plan["id"],
        [_item(catalog, sales="fin", raw="raw2", alternative_of=main["id"])],
    )
    assert kept_alt.status_code == 400, kept_alt.text
    assert "Основная строка" in kept_alt.json()["detail"]

    # Убираем основную строку целиком (альтернативы не присылаем) — одна из них
    # становится основной и сохраняет позицию.
    assert _save(client, plan["id"], []).status_code == 200
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    assert len(body["items"]) == 1
    promoted = body["items"][0]
    assert promoted["id"] == alternative["id"]
    assert promoted["alternative_of_id"] is None
    assert promoted["quantity"] == "30.000"
    assert promoted["product_id"] == str(catalog["raw2"].id)


def _approve_plan(client: TestClient, login, plan_id: str) -> None:
    login("purchase")
    assert client.post(f"/api/v1/purchase-plans/{plan_id}/submit").status_code == 200
    login("executive")
    approved = client.post(f"/api/v1/purchase-plans/{plan_id}/approve")
    assert approved.status_code == 200, approved.text


def test_norm_gives_need_and_gap(client: TestClient, login, catalog: dict[str, Any]) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="400", norm="1.5")])
    assert saved.status_code == 200, saved.text
    item = saved.json()["items"][0]

    assert Decimal(item["norm"]) == Decimal("1.5000")
    assert Decimal(item["need_quantity"]) == Decimal("450.000")
    assert Decimal(item["plan_gap"]) == Decimal("-50.000")
    assert [(row["month"], Decimal(row["quantity"])) for row in item["need_months"]] == [
        (1, Decimal("150")),
        (2, Decimal("300")),
    ]
    # Потребность месяца берётся из продаж, а не из пропорции годового количества.
    assert [(row["month"], Decimal(row["quantity"])) for row in item["schedule"]] == [
        (1, Decimal("150")),
        (2, Decimal("300")),
    ]


def test_line_without_norm_keeps_legacy_split(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="300")])
    assert saved.status_code == 200, saved.text
    item = saved.json()["items"][0]

    assert item["norm"] is None
    assert Decimal(item["need_quantity"]) == 0
    assert item["need_months"] == []
    assert Decimal(item["plan_gap"]) == 0
    # Старое поведение: годовое количество делится пропорционально продажам.
    assert [(row["month"], Decimal(row["quantity"])) for row in item["schedule"]] == [
        (1, Decimal("100")),
        (2, Decimal("200")),
    ]


def test_alternative_has_its_own_norm_for_reference(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    main = _item(catalog, quantity="300", norm="1.5")
    saved = _save(client, plan["id"], [main])
    assert saved.status_code == 200, saved.text
    main_id = saved.json()["items"][0]["id"]

    alt = _item(catalog, raw="raw2", quantity="100", norm="2", alternative_of=main_id)
    both = _save(client, plan["id"], [{**main, "id": main_id}, alt])
    assert both.status_code == 200, both.text
    items = {Decimal(row["norm"]): row for row in both.json()["items"]}
    assert Decimal(items[Decimal("1.5")]["need_quantity"]) == Decimal("450.000")
    assert Decimal(items[Decimal("2.0")]["need_quantity"]) == Decimal("600.000")
    # У альтернативы потребность справочная: её количество — план закупки.
    assert items[Decimal("2.0")]["schedule"] == []


def _signal_events(db_session: Session) -> list[AuditEvent]:
    return list(
        db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "purchase_plan.revision_needed")
        )
        .scalars()
        .all()
    )


def _carry_events(db_session: Session) -> list[AuditEvent]:
    return list(
        db_session.execute(select(AuditEvent).where(AuditEvent.action == "purchase_plan.carryover"))
        .scalars()
        .all()
    )


def _plan_with_norm(client: TestClient, login, catalog: dict[str, Any]) -> dict[str, Any]:
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="30", norm="1.5")])
    assert saved.status_code == 200, saved.text
    _approve_plan(client, login, plan["id"])
    return plan


def test_close_signals_purchase_on_overperformance(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _make_annual(client, login, catalog)
    _plan_with_norm(client, login, catalog)

    login("commercial")
    uploaded = upload_sales(
        client,
        sales_xlsx(
            [("ООО Ромашка", [("Смесь ореховая", "150", "15000")])],
            period=f"Январь {YEAR}",
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["rows_created"] == 1

    closed = client.post(f"/api/v1/month-results/{YEAR}/1/close")
    assert closed.status_code == 200, closed.text

    events = _signal_events(db_session)
    assert len(events) == 1
    event = events[0]
    assert event.is_message is True
    assert "purchase_director" in event.audience
    assert "import_manager" in event.audience
    assert event.month == 1
    assert "Продажи за январь" in event.summary
    assert "добавка 75 кг" in event.summary

    payload = event.payload or {}
    assert payload["month"] == 1
    line = payload["lines"][0]
    assert Decimal(line["plan_units"]) == Decimal("100")
    assert Decimal(line["fact_units"]) == Decimal("150")
    assert Decimal(line["units_delta"]) == Decimal("50")
    assert Decimal(line["was_kg"]) == Decimal("150")
    assert Decimal(line["now_kg"]) == Decimal("225")
    assert Decimal(line["delta_kg"]) == Decimal("75")
    assert line["alternative"] is False

    purchase_plan = db_session.execute(select(PurchasePlan)).scalars().one()
    assert purchase_plan.revision_requested_at is not None

    # История изменений приходит вместе с планом: было → стало по строке.
    login("purchase")
    plan_body = client.get(f"/api/v1/purchase-plans/{purchase_plan.id}").json()
    assert len(plan_body["signals"]) == 1
    signal = plan_body["signals"][0]
    assert signal["month"] == 1
    assert signal["actor_name"] == "Коммерческий директор (демо)"
    history_line = signal["lines"][0]
    assert Decimal(history_line["was_kg"]) == Decimal("150")
    assert Decimal(history_line["now_kg"]) == Decimal("225")
    assert Decimal(history_line["delta_kg"]) == Decimal("75")


def test_no_signal_when_fact_meets_plan(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _make_annual(client, login, catalog)
    _plan_with_norm(client, login, catalog)

    login("commercial")
    uploaded = upload_sales(
        client,
        sales_xlsx(
            [("ООО Ромашка", [("Смесь ореховая", "100", "10000")])],
            period=f"Январь {YEAR}",
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post(f"/api/v1/month-results/{YEAR}/1/close").status_code == 200

    assert _signal_events(db_session) == []
    assert _carry_events(db_session) == []


def test_underperformance_keeps_stock_and_tells_purchase(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Недобор не увеличивает план: сырьё уже куплено и закрывает следующие месяцы."""
    _make_annual(client, login, catalog)
    plan = _plan_with_norm(client, login, catalog)

    login("commercial")
    uploaded = upload_sales(
        client,
        sales_xlsx(
            [("ООО Ромашка", [("Смесь ореховая", "80", "8000")])],
            period=f"Январь {YEAR}",
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post(f"/api/v1/month-results/{YEAR}/1/close").status_code == 200

    # Перевыполнения нет: запрос пересмотра не ставится, план не растёт.
    assert _signal_events(db_session) == []
    purchase_plan = db_session.execute(select(PurchasePlan)).scalars().one()
    assert purchase_plan.revision_requested_at is None

    events = _carry_events(db_session)
    assert len(events) == 1
    event = events[0]
    assert event.is_message is True
    assert "purchase_director" in event.audience
    assert "import_manager" in event.audience
    assert "Продажи за январь" in event.summary
    assert "ниже плана" in event.summary
    # 20 единиц недобора × норма 1,5 = 30 кг остатка.
    assert "остаток 30 кг" in event.summary

    payload = event.payload or {}
    line = payload["lines"][0]
    assert Decimal(line["plan_units"]) == Decimal("100")
    assert Decimal(line["fact_units"]) == Decimal("80")
    assert Decimal(line["delta_kg"]) == Decimal("-30")

    # В плане виден остаток, а потребность месяца считается по факту продаж.
    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    item = body["items"][0]
    assert item["carryover"] == "30.000"
    assert item["carryover_month"] == 1
    assert Decimal(item["need_quantity"]) == Decimal("420.000")
    assert [row["quantity"] for row in item["schedule"]] == ["120.000", "300.000"]


def test_underperformance_leftover_covers_next_months(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    """Недобор января остаётся на складе и закрывает февральскую потребность."""
    _make_annual(client, login, catalog)
    plan = _plan_with_norm(client, login, catalog)
    item = db_session.execute(select(PurchasePlanItem)).scalars().one()

    batch = Batch(
        batch_number="ИТ-2027-0500",
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
            quantity=Decimal("450"),
            purchase_plan_item_id=item.id,
        )
    )
    db_session.commit()

    login("commercial")
    uploaded = upload_sales(
        client,
        sales_xlsx(
            [("ООО Ромашка", [("Смесь ореховая", "80", "8000")])],
            period=f"Январь {YEAR}",
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post(f"/api/v1/month-results/{YEAR}/1/close").status_code == 200

    login("purchase")
    body = client.get(f"/api/v1/purchase-plans/{plan['id']}").json()
    item_body = body["items"][0]
    schedule = item_body["schedule"]
    # Январь: куплено 450, продано 80 единиц (120 кг) — на складе 330 кг.
    assert [row["quantity"] for row in schedule] == ["120.000", "300.000"]
    assert [row["covered"] for row in schedule] == ["120.000", "300.000"]
    assert [row["remaining"] for row in schedule] == ["0.000", "0.000"]
    assert [row["carry"] for row in schedule] == ["330.000", "30.000"]
    assert item_body["carry_forward"] == "30.000"
    assert item_body["carryover"] == "30.000"


def test_correction_does_not_touch_purchase_plan(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    plan_ids = _make_annual(client, login, catalog)
    _plan_with_norm(client, login, catalog)

    # Перенос недобора меняет план продаж, но закупки не трогает: товар уже учтён.
    _correct_sales(client, login, plan_ids["sales"], catalog["customer"], catalog["fin"], 1, "150")

    assert _signal_events(db_session) == []
    purchase_plan = db_session.execute(select(PurchasePlan)).scalars().one()
    assert purchase_plan.revision_requested_at is None


def test_empty_sales_report_closes_month(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    _make_annual(client, login, catalog)
    _plan_with_norm(client, login, catalog)

    login("commercial")
    uploaded = upload_sales(client, sales_xlsx([], period=f"Февраль {YEAR}"))
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["rows_created"] == 0
    assert uploaded.json()["rows_total"] == 0

    closed = client.post(f"/api/v1/month-results/{YEAR}/2/close")
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "closed"
    assert body["fact_amount"] == "0.00"

    assert _signal_events(db_session) == []
