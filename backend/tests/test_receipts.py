"""Поступления и курсы валют: динамический пересчёт себестоимости."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty
from app.services import currency_service


def cbr_xml(usd: str = "90,5000") -> bytes:
    return f"""<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="08.10.2026" name="Foreign Currency Market">
  <Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal>
    <Name>Доллар США</Name><Value>{usd}</Value><VunitRate>{usd}</VunitRate></Valute>
  <Valute ID="R01820"><NumCode>392</NumCode><CharCode>JPY</CharCode><Nominal>100</Nominal>
    <Name>Иена</Name><Value>60,0000</Value><VunitRate>0,6</VunitRate></Valute>
</ValCurs>
""".encode()


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
    def fail(day: date) -> currency_service.CbrRates:
        raise currency_service.RateError("ЦБ РФ недоступен в тесте")

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fail)


def _cbr_answer(day: date) -> currency_service.CbrRates:
    return currency_service.CbrRates(
        rate_date=date.fromisoformat(DAY), rates=currency_service.parse_cbr_xml(CBR_XML)
    )


def _with_cbr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(currency_service, "fetch_cbr_rates", _cbr_answer)


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

    def fake_fetch(day: date) -> currency_service.CbrRates:
        calls.append(day)
        return _cbr_answer(day)

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


def _payment(amount: str, rate: str, day: str = DAY) -> dict[str, str]:
    return {"payment_date": day, "amount_currency": amount, "exchange_rate": rate}


def test_currency_payment_closes_invoice_and_fixes_rate(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Оплаченное считается по курсу платежа, остаток — по текущему курсу."""
    login("purchase")
    _with_cbr(monkeypatch)
    created = client.post(
        "/api/v1/batches",
        json=_payload(current_exchange_rate=None, payments=[_payment("600", "80")]),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    finance = body["finance"]
    # 600 $ оплачено по 80 = 48 000 ₽; остаток 400 $ по курсу ЦБ 90,5 = 36 200 ₽.
    assert Decimal(finance["total_paid_currency"]) == Decimal("600.00")
    assert Decimal(finance["total_paid_rub"]) == Decimal("48000.00")
    assert Decimal(finance["remaining_payment_currency"]) == Decimal("400.00")
    # 48 000 + 500 ₽ доставки + 36 200 = 84 700 ₽
    assert Decimal(finance["final_cost_rub"]) == Decimal("84700.00")
    assert Decimal(body["payments"][0]["amount_rub"]) == Decimal("48000.00")
    assert body["finance"]["rate_date"] == DAY


def test_fixed_payment_is_not_revalued_when_rate_grows(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Курс вырос — переоценивается только незакрытая часть, платёж зафиксирован."""
    login("purchase")
    _with_cbr(monkeypatch)
    created = client.post(
        "/api/v1/batches",
        json=_payload(current_exchange_rate=None, payments=[_payment("600", "80")]),
    ).json()

    # Старим кэш курса на два часа — сервис сходит за новым курсом.
    db_session.execute(text("update currency_rates set fetched_at = now() - interval '2 hours'"))
    db_session.commit()
    monkeypatch.setattr(
        currency_service,
        "fetch_cbr_rates",
        lambda day: currency_service.CbrRates(
            rate_date=date.fromisoformat(DAY),
            rates=currency_service.parse_cbr_xml(cbr_xml("100,0000")),
        ),
    )

    updated = client.get(f"/api/v1/batches/{created['id']}")
    assert updated.status_code == 200, updated.text
    finance = updated.json()["finance"]
    assert Decimal(finance["total_paid_rub"]) == Decimal("48000.00")  # платёж не изменился
    assert Decimal(finance["exchange_rate"]) == Decimal("100")
    # 48 000 (платёж) + 500 ₽ доставки + 400 × 100 = 88 500 ₽
    assert Decimal(finance["final_cost_rub"]) == Decimal("88500.00")


def test_fresh_rate_is_taken_from_cache(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    calls: list[date] = []

    def fake_fetch(day: date) -> currency_service.CbrRates:
        calls.append(day)
        return currency_service.CbrRates(
            rate_date=date.fromisoformat(DAY), rates=currency_service.parse_cbr_xml(CBR_XML)
        )

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fake_fetch)
    client.post("/api/v1/batches", json=_payload(current_exchange_rate=None, batch_number="P-1"))
    client.post("/api/v1/batches", json=_payload(current_exchange_rate=None, batch_number="P-2"))
    # Второй запрос берёт свежий курс из кэша, в сеть не ходит.
    assert len(calls) == 1


def test_payments_are_split_between_items_proportionally(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    payload = _payload(
        current_exchange_rate="90",
        payments=[_payment("1000", "80")],
        items=[
            {
                "product_code": "ТОВ1",
                "product_name": "Первый",
                "quantity": "10",
                "total_invoice_currency": "600.00",
            },
            {
                "product_code": "ТОВ2",
                "product_name": "Второй",
                "quantity": "10",
                "total_invoice_currency": "400.00",
            },
        ],
        total_invoice_value="1000.00",
    )
    created = client.post("/api/v1/batches", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    # Инвойс закрыт платежом 1000 $ по 80 → 80 000 ₽ + 500 ₽ доставки = 80 500 ₽.
    assert Decimal(body["finance"]["remaining_payment_currency"]) == Decimal("0.00")
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("80500.00")
    costs = {item["product_code"]: item for item in body["items"]}
    # 80 500 ₽ делим пропорционально: 60% и 40%, по 10 шт в строке.
    assert Decimal(costs["ТОВ1"]["item_total_rub"]) == Decimal("48300.00")
    assert Decimal(costs["ТОВ1"]["unit_cost"]) == Decimal("4830.00")
    assert Decimal(costs["ТОВ2"]["item_total_rub"]) == Decimal("32200.00")
    assert Decimal(costs["ТОВ2"]["unit_cost"]) == Decimal("3220.00")


def test_payments_can_be_edited(client: TestClient, login, monkeypatch: pytest.MonkeyPatch) -> None:
    login("purchase")
    _no_network(monkeypatch)
    created = client.post(
        "/api/v1/batches",
        json=_payload(current_exchange_rate="90", payments=[_payment("500", "80")]),
    ).json()
    assert Decimal(created["finance"]["total_paid_currency"]) == Decimal("500.00")

    updated = client.put(
        f"/api/v1/batches/{created['id']}",
        json=_payload(
            current_exchange_rate="90",
            payments=[_payment("500", "80"), _payment("500", "85")],
        ),
    )
    assert updated.status_code == 200, updated.text
    finance = updated.json()["finance"]
    assert Decimal(finance["total_paid_currency"]) == Decimal("1000.00")
    assert Decimal(finance["total_paid_rub"]) == Decimal("82500.00")
    assert Decimal(finance["remaining_payment_currency"]) == Decimal("0.00")
    assert Decimal(finance["final_cost_rub"]) == Decimal("83000.00")
    assert len(updated.json()["payments"]) == 2


def test_hourly_refresh_touches_only_used_currencies(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    login("purchase")
    _with_cbr(monkeypatch)
    client.post("/api/v1/batches", json=_payload(current_exchange_rate=None))
    db_session.execute(text("update currency_rates set fetched_at = now() - interval '3 hours'"))
    db_session.commit()

    fetched: list[str] = []

    def fake_fetch(day: date) -> currency_service.CbrRates:
        fetched.append("call")
        return currency_service.CbrRates(
            rate_date=date.fromisoformat(DAY), rates=currency_service.parse_cbr_xml(CBR_XML)
        )

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fake_fetch)
    refreshed = currency_service.refresh_used_rates(db_session)
    assert refreshed == 1  # только USD из поступлений
    assert fetched  # курс действительно перезапрошен


FUTURE = "2099-01-01"


def _cbr_with(monkeypatch: pytest.MonkeyPatch, usd: str) -> None:
    monkeypatch.setattr(
        currency_service,
        "fetch_cbr_rates",
        lambda day: currency_service.CbrRates(
            rate_date=date.fromisoformat(DAY), rates=currency_service.parse_cbr_xml(cbr_xml(usd))
        ),
    )


def test_future_payment_is_plan_only(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Платёж с будущей датой виден как план и в себестоимость не входит."""
    login("purchase")
    _with_cbr(monkeypatch)
    created = client.post(
        "/api/v1/batches",
        json=_payload(current_exchange_rate=None, payments=[_payment("600", "80", FUTURE)]),
    )
    assert created.status_code == 201, created.text
    finance = created.json()["finance"]
    assert Decimal(finance["total_paid_currency"]) == Decimal("0.00")
    assert Decimal(finance["planned_payments_currency"]) == Decimal("600.00")
    assert Decimal(finance["planned_payments_rub"]) == Decimal("48000.00")
    assert Decimal(finance["remaining_payment_currency"]) == Decimal("1000.00")
    # Ничего не оплачено: 1000 $ × 90,5 + 500 ₽ доставки = 91 000 ₽.
    assert Decimal(finance["final_cost_rub"]) == Decimal("91000.00")


def test_payment_counts_on_its_day(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Платёж с сегодняшней датой уже вступил в силу."""
    from datetime import date as date_cls

    login("purchase")
    _with_cbr(monkeypatch)
    today = date_cls.today().isoformat()
    created = client.post(
        "/api/v1/batches",
        json=_payload(current_exchange_rate="90", payments=[_payment("600", "80", today)]),
    ).json()
    assert Decimal(created["finance"]["total_paid_currency"]) == Decimal("600.00")
    assert Decimal(created["finance"]["planned_payments_currency"]) == Decimal("0.00")


def test_future_expense_is_plan_only(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Рублёвый платёж с будущей датой тоже пока план."""
    login("purchase")
    _no_network(monkeypatch)
    created = client.post(
        "/api/v1/batches",
        json=_payload(
            current_exchange_rate="90",
            expenses=[{"expense_date": FUTURE, "amount_rub": "500", "description": "Пошлина"}],
        ),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert Decimal(body["finance"]["additional_expenses_rub"]) == Decimal("0.00")
    assert Decimal(body["finance"]["planned_expenses_rub"]) == Decimal("500.00")
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("90000.00")
    assert body["expenses"][0]["is_planned"] is True
    assert body["expenses"][0]["expense_date"] == FUTURE


def test_payments_over_invoice_are_rejected(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Лимит: платежи не могут быть больше стоимости товаров партии."""
    login("purchase")
    _no_network(monkeypatch)
    response = client.post(
        "/api/v1/batches",
        json=_payload(
            current_exchange_rate="90",
            total_invoice_value="1000.00",
            payments=[_payment("900", "80"), _payment("200", "85")],
        ),
    )
    assert response.status_code == 400
    assert "больше стоимости товаров" in response.json()["detail"]


def test_payment_equal_to_invoice_is_allowed(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    response = client.post(
        "/api/v1/batches",
        json=_payload(
            current_exchange_rate="90",
            total_invoice_value="1000.00",
            payments=[_payment("1000", "80")],
        ),
    )
    assert response.status_code == 201, response.text
    assert Decimal(response.json()["finance"]["remaining_payment_currency"]) == Decimal("0.00")


def test_effective_rate_is_weighted_average(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пример: 5000 $ по 110, 1000 $ по 115, остаток 4000 $ по курсу ЦБ 85 → 100,50."""
    login("purchase")
    _cbr_with(monkeypatch, "85,0000")
    payload = _payload(
        current_exchange_rate=None,
        total_invoice_value="10000.00",
        items=[
            {
                "product_code": "ТОВ1",
                "product_name": "Товар",
                "quantity": "100",
                "total_invoice_currency": "10000.00",
            }
        ],
        expenses=[],
        payments=[_payment("5000", "110"), _payment("1000", "115")],
    )
    created = client.post("/api/v1/batches", json=payload)
    assert created.status_code == 201, created.text
    finance = created.json()["finance"]
    assert Decimal(finance["total_paid_rub"]) == Decimal("665000.00")
    assert Decimal(finance["remaining_payment_currency"]) == Decimal("4000.00")
    assert Decimal(finance["final_cost_rub"]) == Decimal("1005000.00")
    assert Decimal(finance["effective_rate"]) == Decimal("100.500000")
    assert Decimal(finance["exchange_rate"]) == Decimal("85")
