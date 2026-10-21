"""План закупок сырья: ручные строки, согласование и заморозка месяцев."""

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.services.purchase_plan_service import order_month

TODAY = date.today()


@pytest.fixture
def raw_products(db_session: Session) -> dict[str, Product]:
    first = Product(code="RAW-1", name="Орех грецкий, вес", kind="raw", unit="кг")
    second = Product(code="RAW-2", name="Курага, вес", kind="raw", unit="кг")
    material = Product(code="MAT-1", name="Банка 500 г", kind="material", unit="шт")
    inactive = Product(code="RAW-3", name="Старое сырьё", kind="raw", unit="кг", is_active=False)
    db_session.add_all([first, second, material, inactive])
    db_session.commit()
    return {"first": first, "second": second, "material": material, "inactive": inactive}


@pytest.fixture
def suppliers(db_session: Session) -> dict[str, Counterparty]:
    importer = Counterparty(name="ООО Импорт", name_key="ооо импорт", is_import_supplier=True)
    local = Counterparty(name="ООО Локальный", name_key="ооо локальный", is_local_supplier=True)
    customer = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([importer, local, customer])
    db_session.commit()
    return {"import": importer, "local": local, "customer": customer}


def _create_plan(client: TestClient, year: int) -> dict[str, Any]:
    response = client.post("/api/v1/purchase-plans", json={"year": year})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _item(
    product: Product,
    month: int,
    quantity: str = "100",
    price: str | None = "250.50",
    supplier: Counterparty | None = None,
    delivery_days: int = 30,
) -> dict[str, Any]:
    return {
        "product_id": str(product.id),
        "month": month,
        "quantity": quantity,
        "price_rub": price,
        "supplier_id": str(supplier.id) if supplier else None,
        "delivery_days": delivery_days,
    }


def _save(client: TestClient, plan_id: str, items: list[dict[str, Any]]) -> Any:
    return client.put(f"/api/v1/purchase-plans/{plan_id}/items", json={"items": items})


def test_purchase_director_fills_and_executive_approves(
    client: TestClient, login, raw_products: dict[str, Product], suppliers: dict[str, Counterparty]
) -> None:
    login("purchase")
    plan = _create_plan(client, TODAY.year)
    assert plan["status"] == "draft"
    assert plan["status_title"] == "Черновик"
    assert plan["created_by_name"] == "Директор по закупкам (демо)"

    saved = _save(
        client,
        plan["id"],
        [_item(raw_products["first"], TODAY.month, "100.5", "250.50", suppliers["import"], 65)],
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    row = body["items"][0]
    assert row["product_code"] == "RAW-1"
    assert row["unit"] == "кг"
    assert row["quantity"] == "100.500"
    assert row["price_rub"] == "250.50"
    assert row["supplier_name"] == "ООО Импорт"
    assert row["order_month"] == max(1, TODAY.month - 3)
    assert TODAY.month in body["editable_months"]

    submitted = client.post(f"/api/v1/purchase-plans/{plan['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "on_review"
    assert submitted.json()["status_title"] == "На проверке"

    login("executive")
    approved = client.post(f"/api/v1/purchase-plans/{plan['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["status_title"] == "Утверждён"
    assert approved.json()["approved_by_name"] == "Исполнительный директор (демо)"

    login("purchase")
    denied = _save(client, plan["id"], [_item(raw_products["second"], TODAY.month)])
    assert denied.status_code == 409, denied.text

    login("executive")
    reopened = client.post(
        f"/api/v1/purchase-plans/{plan['id']}/reopen", json={"reason": "уточнить цены"}
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "draft"
    assert "Возврат в работу: уточнить цены" in (reopened.json()["notes"] or "")

    login("purchase")
    assert (
        _save(client, plan["id"], [_item(raw_products["second"], TODAY.month)]).status_code == 200
    )


def test_import_manager_edits_but_others_only_view(
    client: TestClient, login, raw_products: dict[str, Product], suppliers: dict[str, Counterparty]
) -> None:
    login("import")
    plan = _create_plan(client, TODAY.year)
    saved = _save(client, plan["id"], [_item(raw_products["first"], TODAY.month)])
    assert saved.status_code == 200, saved.text

    login("sales")
    assert client.get("/api/v1/purchase-plans").status_code == 403
    assert _save(client, plan["id"], []).status_code == 403

    login("commercial")
    assert client.get("/api/v1/purchase-plans").status_code == 403

    login("executive")
    assert client.get("/api/v1/purchase-plans").status_code == 200
    assert _save(client, plan["id"], []).status_code == 403
    assert client.post(f"/api/v1/purchase-plans/{plan['id']}/approve").status_code == 409

    # Удалять может только директор по закупкам; импорт-менеджеру — 403.
    assert client.delete(f"/api/v1/purchase-plans/{plan['id']}").status_code == 403
    login("purchase")
    assert client.delete(f"/api/v1/purchase-plans/{plan['id']}").status_code == 204


def test_only_raw_active_products_and_suppliers(
    client: TestClient, login, raw_products: dict[str, Product], suppliers: dict[str, Counterparty]
) -> None:
    login("purchase")
    plan = _create_plan(client, TODAY.year)
    good = _save(client, plan["id"], [_item(raw_products["first"], TODAY.month)])
    assert good.status_code == 200, good.text

    material = _save(client, plan["id"], [_item(raw_products["material"], TODAY.month)])
    assert material.status_code == 400, material.text
    assert "не сырьё" in material.json()["detail"]

    inactive = _save(client, plan["id"], [_item(raw_products["inactive"], TODAY.month)])
    assert inactive.status_code == 400, inactive.text
    assert "отключён" in inactive.json()["detail"]

    wrong_supplier = _save(
        client,
        plan["id"],
        [_item(raw_products["first"], TODAY.month, supplier=suppliers["customer"])],
    )
    assert wrong_supplier.status_code == 400, wrong_supplier.text
    assert "не отмечен поставщиком" in wrong_supplier.json()["detail"]

    # Отклонённая правка не стёрла прежнюю строку.
    assert len(client.get(f"/api/v1/purchase-plans/{plan['id']}").json()["items"]) == 1


def test_same_product_and_month_allows_several_suppliers(
    client: TestClient, login, raw_products: dict[str, Product], suppliers: dict[str, Counterparty]
) -> None:
    login("purchase")
    plan = _create_plan(client, TODAY.year)
    saved = _save(
        client,
        plan["id"],
        [
            _item(raw_products["first"], TODAY.month, "60", "240", suppliers["import"], 0),
            _item(raw_products["first"], TODAY.month, "40", "260", suppliers["local"], 65),
        ],
    )
    assert saved.status_code == 200, saved.text
    rows = saved.json()["items"]
    assert len(rows) == 2
    assert {row["supplier_name"] for row in rows} == {"ООО Импорт", "ООО Локальный"}
    # Месяц заказа у строк свой: срок 0 и срок 65 дней.
    assert {row["order_month"] for row in rows} == {TODAY.month, max(1, TODAY.month - 3)}


def test_freeze_blocks_past_months(
    client: TestClient, login, raw_products: dict[str, Product]
) -> None:
    login("purchase")

    previous = _create_plan(client, TODAY.year - 1)
    denied = _save(client, previous["id"], [_item(raw_products["first"], 1)])
    assert denied.status_code == 409, denied.text
    assert "Замороженные месяцы" in denied.json()["detail"]

    if TODAY.month > 1:
        current = _create_plan(client, TODAY.year)
        frozen = _save(client, current["id"], [_item(raw_products["first"], TODAY.month - 1)])
        assert frozen.status_code == 409, frozen.text

    future = _create_plan(client, TODAY.year + 1)
    saved = _save(client, future["id"], [_item(raw_products["first"], 1)])
    assert saved.status_code == 200, saved.text
    assert 1 in saved.json()["editable_months"]


def test_one_plan_per_year_and_submit_rules(
    client: TestClient, login, raw_products: dict[str, Product]
) -> None:
    login("purchase")
    plan = _create_plan(client, TODAY.year)
    duplicate = client.post("/api/v1/purchase-plans", json={"year": TODAY.year})
    assert duplicate.status_code == 409, duplicate.text
    assert "уже есть" in duplicate.json()["detail"]

    empty = client.post(f"/api/v1/purchase-plans/{plan['id']}/submit")
    assert empty.status_code == 400, empty.text
    assert "пустой" in empty.json()["detail"]

    no_price = _save(client, plan["id"], [_item(raw_products["first"], TODAY.month, price=None)])
    assert no_price.status_code == 200, no_price.text
    priceless = client.post(f"/api/v1/purchase-plans/{plan['id']}/submit")
    assert priceless.status_code == 400, priceless.text
    assert "Укажите цену" in priceless.json()["detail"]

    priced = _save(client, plan["id"], [_item(raw_products["first"], TODAY.month)])
    assert priced.status_code == 200, priced.text
    assert client.post(f"/api/v1/purchase-plans/{plan['id']}/submit").status_code == 200


def test_delete_only_draft(client: TestClient, login, raw_products: dict[str, Product]) -> None:
    login("purchase")
    plan = _create_plan(client, TODAY.year)
    _save(client, plan["id"], [_item(raw_products["first"], TODAY.month)])
    client.post(f"/api/v1/purchase-plans/{plan['id']}/submit")

    login("executive")
    client.post(f"/api/v1/purchase-plans/{plan['id']}/approve")
    login("purchase")
    denied = client.delete(f"/api/v1/purchase-plans/{plan['id']}")
    assert denied.status_code == 409, denied.text


@pytest.mark.parametrize(
    ("month", "delivery_days", "expected"),
    [
        (1, 0, 1),
        (5, 0, 5),
        (5, 30, 4),
        (5, 31, 3),
        (5, 60, 3),
        (5, 61, 2),
        (5, 90, 2),
        (5, 91, 1),
        (5, 365, 1),
    ],
)
def test_order_month_formula(month: int, delivery_days: int, expected: int) -> None:
    assert order_month(month, delivery_days) == expected
