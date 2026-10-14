"""API-сквозной сценарий: ручная партия → себестоимость → остатки."""

from decimal import Decimal

from fastapi.testclient import TestClient

BATCH_PAYLOAD = {
    "batch_number": "P-001",
    "batch_date": "2026-10-01",
    "currency": "RUB",
    "supplier": "ООО Ромашка",
    "current_exchange_rate": "1",
    "items": [
        {
            "product_code": "SKU-1",
            "product_name": "Товар 1",
            "product_kind": "goods",
            "quantity": "10",
            "unit_price_currency": "60.00",
            "duty_percent": "0",
            "vat_percent": "0",
        },
        {
            "product_code": "SKU-2",
            "product_name": "Материал 2",
            "product_kind": "material",
            "quantity": "5",
            "unit_price_currency": "80.00",
            "duty_percent": "0",
            "vat_percent": "0",
        },
    ],
    "expenses": [{"amount_currency": "500.00", "currency": "RUB", "description": "Доставка"}],
}


def test_health(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health/db").json() == {"status": "ok"}


def test_create_batch_computes_cost_and_stock(client: TestClient) -> None:
    created = client.post("/api/v1/batches", json=BATCH_PAYLOAD)
    assert created.status_code == 201, created.text

    body = created.json()
    assert Decimal(body["finance"]["invoice_total_currency"]) == Decimal("1000.00")
    assert Decimal(body["finance"]["expenses_rub"]) == Decimal("500.00")
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("1500.00")

    by_code = {item["product_code"]: item for item in body["items"]}
    assert Decimal(by_code["SKU-1"]["unit_cost"]) == Decimal("90.00")
    assert Decimal(by_code["SKU-2"]["unit_cost"]) == Decimal("120.00")

    stock = client.get("/api/v1/stock")
    assert stock.status_code == 200
    rows = {row["product_code"]: row for row in stock.json()}
    assert Decimal(rows["SKU-1"]["quantity_on_hand"]) == Decimal("10.000")
    assert Decimal(rows["SKU-1"]["value_rub"]) == Decimal("900.00")
    assert Decimal(rows["SKU-2"]["value_rub"]) == Decimal("600.00")

    listed = client.get("/api/v1/batches")
    assert listed.status_code == 200
    assert [batch["batch_number"] for batch in listed.json()] == ["P-001"]


def test_products_are_created_from_batch(client: TestClient) -> None:
    client.post("/api/v1/batches", json=BATCH_PAYLOAD)
    goods = client.get("/api/v1/products", params={"kind": "goods"}).json()
    assert [product["code"] for product in goods] == ["SKU-1"]
    materials = client.get("/api/v1/products", params={"kind": "material"}).json()
    assert [product["code"] for product in materials] == ["SKU-2"]


def test_duplicate_batch_number_is_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/batches", json=BATCH_PAYLOAD).status_code == 201
    again = client.post("/api/v1/batches", json=BATCH_PAYLOAD)
    assert again.status_code == 409
    assert "уже существует" in again.json()["detail"]


def test_unknown_batch_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/batches/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_invoice_total_is_sum_of_item_prices(client: TestClient) -> None:
    """Инвойс партии не хранится: он всегда равен сумме «цена × количество»."""
    created = client.post("/api/v1/batches", json=BATCH_PAYLOAD).json()
    assert Decimal(created["finance"]["invoice_total_currency"]) == Decimal("1000.00")
    assert Decimal(created["finance"]["risk_total_currency"]) == Decimal("0.00")
