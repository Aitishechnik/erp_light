"""Поступления и курсы валют: динамический пересчёт себестоимости."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty
from app.services import currency_service

CBR_XML = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="08.10.2026" name="Foreign Currency Market">
  <Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal>
    <Name>Доллар США</Name><Value>90,5000</Value><VunitRate>90,5</VunitRate></Valute>
  <Valute ID="R01239"><NumCode>978</NumCode><CharCode>EUR</CharCode><Nominal>1</Nominal>
    <Name>Евро</Name><Value>99,2500</Value><VunitRate>99,25</VunitRate></Valute>
  <Valute ID="R01820"><NumCode>392</NumCode><CharCode>JPY</CharCode><Nominal>100</Nominal>
    <Name>Иена</Name><Value>60,0000</Value><VunitRate>0,6</VunitRate></Valute>
</ValCurs>
""".encode()

DAY = "2026-10-08"


@pytest.fixture
def supplier(db_session: Session) -> Counterparty:
    row = Counterparty(
        name="Импорт Трейд",
        name_key="импорт трейд",
        is_import_supplier=True,
        source="1c",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(day: date) -> dict[str, tuple[int, Decimal]]:
        raise currency_service.RateError("ЦБ РФ недоступен в тесте")

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fail)


def _with_cbr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        currency_service, "fetch_cbr_rates", lambda day: currency_service.parse_cbr_xml(CBR_XML)
    )


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "batch_number": "P-100",
        "batch_date": DAY,
        "currency": "USD",
        "total_invoice_value": "1000.00",
        "current_exchange_rate": "90",
        "items": [
            {
                "product_code": "ТОВ1",
                "product_name": "Товар 1",
                "quantity": "10",
                "total_invoice_currency": "1000.00",
            }
        ],
        "expenses": [{"amount_rub": "500.00", "description": "Доставка"}],
    }
    payload.update(overrides)
    return payload


def test_parse_cbr_xml_counts_nominal() -> None:
    rates = currency_service.parse_cbr_xml(CBR_XML)
    assert rates["USD"] == (1, Decimal("90.5000"))
    assert rates["JPY"] == (100, Decimal("0.6000"))


def test_rate_is_cached_and_reused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    calls: list[date] = []

    def fake_fetch(day: date) -> dict[str, tuple[int, Decimal]]:
        calls.append(day)
        return currency_service.parse_cbr_xml(CBR_XML)

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fake_fetch)
    first = client.get("/api/v1/rates/USD", params={"date": DAY})
    assert first.status_code == 200, first.text
    assert Decimal(first.json()["rate"]) == Decimal("90.5")
    second = client.get("/api/v1/rates/USD", params={"date": DAY})
    assert Decimal(second.json()["rate"]) == Decimal("90.5")
    # Второй раз берём из кэша — в сеть не ходим.
    assert len(calls) == 1


def test_rub_rate_is_one(client: TestClient) -> None:
    response = client.get("/api/v1/rates/RUB", params={"date": DAY})
    assert response.status_code == 200
    assert Decimal(response.json()["rate"]) == Decimal("1")


def test_unknown_currency_without_network(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    response = client.get("/api/v1/rates/XYZ", params={"date": DAY})
    assert response.status_code == 404
    assert "введите вручную" in response.json()["detail"]


def test_receipt_takes_rate_from_cbr(
    client: TestClient, login, supplier: Counterparty, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _with_cbr(monkeypatch)
    created = client.post(
        "/api/v1/batches", json=_payload(current_exchange_rate=None, supplier_id=str(supplier.id))
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["supplier_id"] == str(supplier.id)
    assert body["supplier"] == "Импорт Трейд"
    assert Decimal(body["finance"]["exchange_rate"]) == Decimal("90.5")
    # 1000 $ по 90,5 + 500 ₽ доставки = 91 000 ₽; за 10 шт — 9 100 ₽ за штуку.
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("91000.00")
    assert Decimal(body["items"][0]["unit_cost"]) == Decimal("9100.00")


def test_cost_changes_when_rate_changes(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Динамические цены: поменяли курс — себестоимость пересчиталась."""
    login("purchase")
    _no_network(monkeypatch)
    created = client.post("/api/v1/batches", json=_payload()).json()
    assert Decimal(created["items"][0]["unit_cost"]) == Decimal("9050.00")

    updated = client.put(
        f"/api/v1/batches/{created['id']}", json=_payload(current_exchange_rate="95")
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert Decimal(body["finance"]["exchange_rate"]) == Decimal("95")
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("95500.00")
    assert Decimal(body["items"][0]["unit_cost"]) == Decimal("9550.00")


def test_receipt_without_rate_and_without_network_is_rejected(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    response = client.post("/api/v1/batches", json=_payload(current_exchange_rate=None))
    assert response.status_code == 502
    assert "Введите курс вручную" in response.json()["detail"]


def test_calendar_filters_by_period(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    client.post("/api/v1/batches", json=_payload(batch_number="P-1", batch_date="2026-10-05"))
    client.post("/api/v1/batches", json=_payload(batch_number="P-2", batch_date="2026-10-20"))

    october = client.get("/api/v1/batches", params={"from": "2026-10-01", "to": "2026-10-31"})
    assert [row["batch_number"] for row in october.json()] == ["P-1", "P-2"]

    week = client.get("/api/v1/batches", params={"from": "2026-10-10", "to": "2026-10-31"})
    assert [row["batch_number"] for row in week.json()] == ["P-2"]


def test_receipt_can_be_deleted(client: TestClient, login, monkeypatch: pytest.MonkeyPatch) -> None:
    login("purchase")
    _no_network(monkeypatch)
    created = client.post("/api/v1/batches", json=_payload()).json()
    assert client.delete(f"/api/v1/batches/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/batches/{created['id']}").status_code == 404
    assert client.delete(f"/api/v1/batches/{created['id']}").status_code == 404


def test_duplicate_number_is_rejected(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    client.post("/api/v1/batches", json=_payload())
    again = client.post("/api/v1/batches", json=_payload())
    assert again.status_code == 409
    assert "уже существует" in again.json()["detail"]


def test_sales_manager_cannot_create_receipt(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("sales")
    _no_network(monkeypatch)
    assert client.post("/api/v1/batches", json=_payload()).status_code == 403
    assert client.get("/api/v1/batches").status_code == 200


def test_unknown_supplier_is_rejected(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    response = client.post(
        "/api/v1/batches",
        json=_payload(supplier_id="00000000-0000-0000-0000-000000000000"),
    )
    assert response.status_code == 400
    assert "не найден" in response.json()["detail"]
