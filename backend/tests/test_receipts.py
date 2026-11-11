"""Поступления и курсы валют: динамический пересчёт себестоимости.

Формула — по контракту [`docs/data-contract-receipts.md`](../../docs/data-contract-receipts.md) §3:
инвойс и Risk закрываются платежами своих категорий, пошлина и НДС считаются в
валюте, общие расходы делятся между строками по полной валютной стоимости.
"""

import logging
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty
from app.services import currency_service
from tests.helpers import create_receipt_draft


def _put(client: TestClient, payload: dict[str, object], *, expect: int = 200):
    """Завести поступление выгрузкой и сразу заполнить карточку (PUT)."""
    draft = create_receipt_draft(client, str(payload["batch_number"]))
    response = client.put(f"/api/v1/batches/{draft['id']}", json=payload)
    assert response.status_code == expect, response.text
    return response


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


def _item(**overrides: object) -> dict[str, object]:
    """Строка партии: 10 шт по 100 $ без пошлины, НДС и Risk."""
    item: dict[str, object] = {
        "product_code": "ТОВ1",
        "product_name": "Товар 1",
        "quantity": "10",
        "unit_price_currency": "100.00",
        "duty_percent": "0",
        "vat_percent": "0",
        "risk_unit_currency": "0",
    }
    item.update(overrides)
    return item


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "batch_number": "P-100",
        "batch_date": DAY,
        "currency": "USD",
        "current_exchange_rate": "90",
        "items": [_item()],
        "expenses": [{"amount_currency": "500.00", "currency": "RUB", "description": "Доставка"}],
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


def test_rate_endpoint_explains_cbr_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Курса нет и ЦБ недоступен — отдаём причину, а не глухое «не найден»."""
    _no_network(monkeypatch)
    response = client.get("/api/v1/rates/USD")
    assert response.status_code == 502
    assert "ЦБ РФ недоступен" in response.json()["detail"]


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


def test_batch_rate_ignores_arrival_date(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Дата поступления в прошлом не задаёт курс остатка — берём актуальный курс ЦБ.

    ЦБ отдаёт на 08.10.2026 курс 90,5, а на сегодня — 83,76. Поступление задним числом
    всё равно оценивается по актуальному курсу: курс на прошлую дату нужен только
    растаможке.
    """
    login("purchase")
    today = date.today()

    def fake_fetch(day: date) -> currency_service.CbrRates:
        rate = Decimal("83.7600") if day == today else Decimal("90.5000")
        return currency_service.CbrRates(rate_date=day, rates={"USD": (1, rate)})

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fake_fetch)
    created = _put(client, _payload(batch_date=DAY, current_exchange_rate=None, auto_rate=True))
    assert created.status_code == 200, created.text
    body = created.json()
    assert Decimal(body["finance"]["exchange_rate"]) == Decimal("83.76")
    assert body["finance"]["rate_date"] == today.isoformat()
    # 1000 $ по актуальному курсу + 500 ₽ доставки — а не по курсу дня поступления.
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("84260.00")


def test_receipt_takes_rate_from_cbr(
    client: TestClient, login, supplier: Counterparty, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _with_cbr(monkeypatch)
    created = _put(client, _payload(current_exchange_rate=None, supplier_id=str(supplier.id)))
    assert created.status_code == 200, created.text
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
    created = _put(client, _payload()).json()
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
    response = _put(client, _payload(current_exchange_rate=None), expect=502)
    assert "Введите курс вручную" in response.json()["detail"]


def test_calendar_filters_by_period(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    _put(client, _payload(batch_number="P-1", batch_date="2026-10-05"))
    _put(client, _payload(batch_number="P-2", batch_date="2026-10-20"))

    october = client.get("/api/v1/batches", params={"from": "2026-10-01", "to": "2026-10-31"})
    assert [row["batch_number"] for row in october.json()] == ["P-1", "P-2"]

    week = client.get("/api/v1/batches", params={"from": "2026-10-10", "to": "2026-10-31"})
    assert [row["batch_number"] for row in week.json()] == ["P-2"]


def test_receipt_can_be_deleted(client: TestClient, login, monkeypatch: pytest.MonkeyPatch) -> None:
    login("purchase")
    _no_network(monkeypatch)
    created = _put(client, _payload()).json()
    assert client.delete(f"/api/v1/batches/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/batches/{created['id']}").status_code == 404
    assert client.delete(f"/api/v1/batches/{created['id']}").status_code == 404


def test_duplicate_number_is_rejected(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    _put(client, _payload())
    second = _put(client, _payload(batch_number="P-200")).json()
    # Номер — идентификатор поступления: занять чужой нельзя и при правке карточки.
    again = client.put(f"/api/v1/batches/{second['id']}", json=_payload(batch_number="P-100"))
    assert again.status_code == 409
    assert "уже существует" in again.json()["detail"]


def test_sales_manager_cannot_edit_receipt(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    draft = create_receipt_draft(client, "P-300")
    login("sales")
    response = client.put(f"/api/v1/batches/{draft['id']}", json=_payload(batch_number="P-300"))
    assert response.status_code == 403
    assert client.get("/api/v1/batches").status_code == 200


def test_unknown_supplier_is_rejected(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    response = _put(
        client,
        _payload(supplier_id="00000000-0000-0000-0000-000000000000"),
        expect=400,
    )
    assert "не найден" in response.json()["detail"]


def _payment(amount: str, rate: str, day: str = DAY, category: str = "invoice") -> dict[str, str]:
    return {
        "payment_date": day,
        "amount_currency": amount,
        "exchange_rate": rate,
        "category": category,
    }


def test_currency_payment_closes_invoice_and_fixes_rate(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Оплаченное считается по курсу платежа, остаток — по текущему курсу."""
    login("purchase")
    _with_cbr(monkeypatch)
    created = _put(client, _payload(current_exchange_rate=None, payments=[_payment("600", "80")]))
    assert created.status_code == 200, created.text
    body = created.json()
    finance = body["finance"]
    # 600 $ оплачено по 80 = 48 000 ₽; остаток 400 $ по курсу ЦБ 90,5 = 36 200 ₽.
    assert Decimal(finance["invoice_paid_currency"]) == Decimal("600.00")
    assert Decimal(finance["invoice_paid_rub"]) == Decimal("48000.00")
    assert Decimal(finance["invoice_remaining_currency"]) == Decimal("400.00")
    # 48 000 + 500 ₽ доставки + 36 200 = 84 700 ₽
    assert Decimal(finance["final_cost_rub"]) == Decimal("84700.00")
    assert Decimal(body["payments"][0]["amount_rub"]) == Decimal("48000.00")
    assert body["payments"][0]["category"] == "invoice"
    assert body["finance"]["rate_date"] == DAY


def test_fixed_payment_is_not_revalued_when_rate_grows(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Курс вырос — переоценивается только незакрытая часть, платёж зафиксирован."""
    login("purchase")
    _with_cbr(monkeypatch)
    created = _put(
        client, _payload(current_exchange_rate=None, payments=[_payment("600", "80")])
    ).json()

    # Старим кэш курса на два часа — фоновая задача сходит за новым курсом.
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
    currency_service.refresh_used_rates(db_session)

    updated = client.get(f"/api/v1/batches/{created['id']}")
    assert updated.status_code == 200, updated.text
    finance = updated.json()["finance"]
    assert Decimal(finance["invoice_paid_rub"]) == Decimal("48000.00")  # платёж не изменился
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
    _put(client, _payload(current_exchange_rate=None, batch_number="P-1"))
    _put(client, _payload(current_exchange_rate=None, batch_number="P-2"))
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
            _item(product_code="ТОВ1", product_name="Первый", unit_price_currency="60.00"),
            _item(product_code="ТОВ2", product_name="Второй", unit_price_currency="40.00"),
        ],
    )
    created = _put(client, payload)
    assert created.status_code == 200, created.text
    body = created.json()
    # Инвойс закрыт платежом 1000 $ по 80 → 80 000 ₽ + 500 ₽ доставки = 80 500 ₽.
    assert Decimal(body["finance"]["invoice_remaining_currency"]) == Decimal("0.00")
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
    created = _put(
        client, _payload(current_exchange_rate="90", payments=[_payment("500", "80")])
    ).json()
    assert Decimal(created["finance"]["invoice_paid_currency"]) == Decimal("500.00")

    updated = client.put(
        f"/api/v1/batches/{created['id']}",
        json=_payload(
            current_exchange_rate="90",
            payments=[_payment("500", "80"), _payment("500", "85")],
        ),
    )
    assert updated.status_code == 200, updated.text
    finance = updated.json()["finance"]
    assert Decimal(finance["invoice_paid_currency"]) == Decimal("1000.00")
    assert Decimal(finance["invoice_paid_rub"]) == Decimal("82500.00")
    assert Decimal(finance["invoice_remaining_currency"]) == Decimal("0.00")
    assert Decimal(finance["final_cost_rub"]) == Decimal("83000.00")
    assert len(updated.json()["payments"]) == 2


def test_calendar_does_not_go_to_cbr(
    client: TestClient,
    login,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """Календарь читает курсы из базы: ЦБ бывает недоступен, а экран должен открываться."""
    login("purchase")
    _with_cbr(monkeypatch)
    _put(client, _payload(current_exchange_rate=None, batch_number="P-1"))
    _put(client, _payload(current_exchange_rate=None, batch_number="P-2"))
    _put(client, _payload(current_exchange_rate=None, batch_number="P-3"))

    # Кэш постарел: раньше каждая из трёх партий шла в ЦБ при открытии месяца.
    db_session.execute(text("update currency_rates set fetched_at = now() - interval '2 hours'"))
    db_session.commit()

    def fail(day: date) -> currency_service.CbrRates:
        raise AssertionError("календарь не должен ходить в ЦБ")

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fail)
    response = client.get("/api/v1/batches")
    assert response.status_code == 200, response.text
    rates = {Decimal(row["finance"]["exchange_rate"]) for row in response.json()}
    assert rates == {Decimal("90.5")}


def test_calendar_warns_when_rate_is_missing(
    client: TestClient,
    login,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Курса в кэше нет — календарь всё равно открывается, а причина попадает в лог."""
    login("purchase")
    _no_network(monkeypatch)
    _put(client, _payload(current_exchange_rate="90"))  # курс задан руками, в кэше ЦБ пусто
    with caplog.at_level(logging.WARNING, logger="erp_lite"):
        assert client.get("/api/v1/batches").status_code == 200
    assert "Нет сохранённого курса ЦБ для USD" in caplog.text


def test_hourly_refresh_reports_cbr_failure(
    client: TestClient,
    login,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """Отказ ЦБ не прячем: фоновая задача пишет причину в лог."""
    login("purchase")
    _no_network(monkeypatch)
    _put(client, _payload(current_exchange_rate="90"))
    with pytest.raises(currency_service.RateError):
        currency_service.refresh_used_rates(db_session)


def test_refresh_does_not_call_cbr_when_cache_is_fresh(
    client: TestClient,
    login,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """Перезапуск сервера со свежим кэшем не ходит в ЦБ."""
    login("purchase")
    _with_cbr(monkeypatch)
    client.get("/api/v1/rates/USD", params={"date": DAY})
    _put(client, _payload(current_exchange_rate="90"))

    def fail(day: date) -> currency_service.CbrRates:
        raise AssertionError("свежий кэш не требует запроса в ЦБ")

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fail)
    assert currency_service.refresh_used_rates(db_session) == {"USD": DAY}


def test_hourly_refresh_touches_only_used_currencies(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    login("purchase")
    _with_cbr(monkeypatch)
    _put(client, _payload(current_exchange_rate=None))
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
    assert len(refreshed) == 1  # только USD из поступлений
    assert fetched == ["call"]  # один запрос в ЦБ на все валюты, а не по одному


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
    created = _put(
        client, _payload(current_exchange_rate=None, payments=[_payment("600", "80", FUTURE)])
    )
    assert created.status_code == 200, created.text
    finance = created.json()["finance"]
    assert Decimal(finance["invoice_paid_currency"]) == Decimal("0.00")
    assert Decimal(finance["planned_invoice_currency"]) == Decimal("600.00")
    assert Decimal(finance["planned_invoice_rub"]) == Decimal("48000.00")
    assert Decimal(finance["invoice_remaining_currency"]) == Decimal("1000.00")
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
    created = _put(
        client, _payload(current_exchange_rate="90", payments=[_payment("600", "80", today)])
    ).json()
    assert Decimal(created["finance"]["invoice_paid_currency"]) == Decimal("600.00")
    assert Decimal(created["finance"]["planned_invoice_currency"]) == Decimal("0.00")


def test_usd_expense_is_converted_at_cbr_rate(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Общий расход в usd пересчитывается по курсу ЦБ на текущий день."""
    login("purchase")
    _with_cbr(monkeypatch)
    created = _put(
        client,
        _payload(
            expenses=[{"amount_currency": "100", "currency": "USD", "description": "Доставка"}]
        ),
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["expenses"][0]["currency"] == "USD"
    assert Decimal(body["expenses"][0]["amount_currency"]) == Decimal("100.00")
    assert Decimal(body["expenses"][0]["amount_rub"]) == Decimal("9050.00")
    assert Decimal(body["finance"]["expenses_rub"]) == Decimal("9050.00")
    # Инвойс без оплат оценивается по курсу ЦБ 90,5: 90 500 ₽ + 9 050 ₽ = 99 550 ₽.
    assert Decimal(body["finance"]["exchange_rate"]) == Decimal("90.5")
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("99550.00")


def test_rub_expense_is_taken_as_is(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    body = _put(client, _payload()).json()
    assert body["expenses"][0]["currency"] == "RUB"
    assert Decimal(body["expenses"][0]["amount_rub"]) == Decimal("500.00")
    assert Decimal(body["finance"]["expenses_rub"]) == Decimal("500.00")


def test_expense_currency_is_limited_to_rub_and_usd(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    _put(
        client,
        _payload(
            expenses=[{"amount_currency": "100", "currency": "EUR", "description": "Доставка"}]
        ),
        expect=422,
    )


def test_duty_vat_and_risk_are_shown_in_the_card(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Новые поля карточки: цена за единицу, пошлина, НДС, Risk и их рубли."""
    login("purchase")
    _no_network(monkeypatch)
    created = _put(
        client,
        _payload(
            current_exchange_rate="90",
            items=[
                {
                    "product_code": "ТОВ1",
                    "product_name": "Товар 1",
                    "quantity": "100",
                    "unit_price_currency": "10",
                    "duty_percent": "5",
                    "vat_percent": "22",
                    "risk_unit_currency": "1",
                }
            ],
            expenses=[{"amount_currency": "50000", "currency": "RUB", "description": "Доставка"}],
        ),
    )
    assert created.status_code == 200, created.text
    body = created.json()
    finance = body["finance"]
    assert Decimal(finance["invoice_total_currency"]) == Decimal("1000.00")
    assert Decimal(finance["risk_total_currency"]) == Decimal("100.00")
    assert Decimal(finance["duty_rub"]) == Decimal("4500.00")
    assert Decimal(finance["vat_rub"]) == Decimal("20790.00")

    item = body["items"][0]
    assert Decimal(item["unit_price_currency"]) == Decimal("10.0000")
    assert Decimal(item["duty_percent"]) == Decimal("5.0000")
    assert Decimal(item["vat_percent"]) == Decimal("22.0000")
    assert Decimal(item["risk_unit_currency"]) == Decimal("1.0000")
    assert Decimal(item["invoice_currency"]) == Decimal("1000.00")
    assert Decimal(item["risk_currency"]) == Decimal("100.00")
    assert Decimal(item["expenses_rub"]) == Decimal("50000.00")
    # Согласованный пример: (10 + 0,5 + 2,31) × 90 + 1 × 90 = 1242,90 ₽/шт.
    assert Decimal(item["unit_cost"]) == Decimal("1742.90")
    assert Decimal(item["item_total_rub"]) == Decimal("174290.00")
    assert Decimal(finance["final_cost_rub"]) == Decimal("174290.00")


def test_risk_is_paid_by_its_own_payments(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Платежи категории risk закрывают Risk по своим курсам, остаток — по ЦБ."""
    login("purchase")
    _no_network(monkeypatch)
    created = _put(
        client,
        _payload(
            current_exchange_rate="90",
            items=[_item(quantity="10", unit_price_currency="100", risk_unit_currency="5")],
            expenses=[],
            payments=[_payment("40", "80", category="risk")],
        ),
    )
    assert created.status_code == 200, created.text
    finance = created.json()["finance"]
    assert Decimal(finance["invoice_rate"]) == Decimal("90.000000")
    assert Decimal(finance["risk_paid_currency"]) == Decimal("40.00")
    assert Decimal(finance["risk_paid_rub"]) == Decimal("3200.00")
    assert Decimal(finance["risk_remaining_currency"]) == Decimal("10.00")
    # (40 × 80 + 10 × 90) ÷ 50 = 82 ₽ за 1 $ Risk.
    assert Decimal(finance["risk_rate"]) == Decimal("82.000000")
    # (100 × 90 + 5 × 82) × 10 шт = 94 100 ₽.
    assert Decimal(finance["final_cost_rub"]) == Decimal("94100.00")


def test_risk_payments_are_limited_by_risk_total(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Лимит считается по каждой категории: Risk нельзя закрыть больше, чем он есть."""
    login("purchase")
    _no_network(monkeypatch)
    response = _put(
        client,
        _payload(
            current_exchange_rate="90",
            items=[_item(quantity="10", unit_price_currency="100", risk_unit_currency="5")],
            expenses=[],
            payments=[_payment("60", "80", category="risk")],
        ),
        expect=400,
    )
    assert "Risk" in response.json()["detail"]


def test_risk_payment_without_risk_is_rejected(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нет Risk в партии — платёж категории risk отклоняется."""
    login("purchase")
    _no_network(monkeypatch)
    response = _put(
        client,
        _payload(current_exchange_rate="90", payments=[_payment("10", "80", category="risk")]),
        expect=400,
    )
    assert "Risk" in response.json()["detail"]


def test_payments_over_invoice_are_rejected(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Лимит: платежи не могут быть больше стоимости товаров партии."""
    login("purchase")
    _no_network(monkeypatch)
    response = _put(
        client,
        _payload(
            current_exchange_rate="90",
            payments=[_payment("900", "80"), _payment("200", "85")],
        ),
        expect=400,
    )
    assert "больше суммы партии" in response.json()["detail"]


def test_payment_equal_to_invoice_is_allowed(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    login("purchase")
    _no_network(monkeypatch)
    response = _put(client, _payload(current_exchange_rate="90", payments=[_payment("1000", "80")]))
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["finance"]["invoice_remaining_currency"]) == Decimal("0.00")


def test_average_rate_is_weighted_average(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пример: 5000 $ по 110, 1000 $ по 115, остаток 4000 $ по курсу ЦБ 85 → 100,50."""
    login("purchase")
    _cbr_with(monkeypatch, "85,0000")
    payload = _payload(
        current_exchange_rate=None,
        items=[_item(quantity="100", unit_price_currency="100")],
        expenses=[],
        payments=[_payment("5000", "110"), _payment("1000", "115")],
    )
    created = _put(client, payload)
    assert created.status_code == 200, created.text
    finance = created.json()["finance"]
    assert Decimal(finance["invoice_paid_rub"]) == Decimal("665000.00")
    assert Decimal(finance["invoice_remaining_currency"]) == Decimal("4000.00")
    assert Decimal(finance["final_cost_rub"]) == Decimal("1005000.00")
    assert Decimal(finance["average_rate"]) == Decimal("100.500000")
    assert Decimal(finance["exchange_rate"]) == Decimal("85")


def test_average_rate_counts_risk_payments(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Инвойс 124 000 $ по 88 и Risk 60 000 $ по 91 → средний курс 88,978261.

    Раньше в списке поступлений показывался только курс инвойса (88), из-за чего
    риск-платежи в средний курс не попадали.
    """
    login("purchase")
    _no_network(monkeypatch)
    created = _put(
        client,
        _payload(
            current_exchange_rate="90",
            items=[
                _item(
                    quantity="20000",
                    unit_price_currency="6.2",
                    risk_unit_currency="3",
                    duty_percent="0",
                )
            ],
            expenses=[],
            payments=[
                _payment("124000", "88"),
                _payment("60000", "91", category="risk"),
            ],
        ),
    )
    assert created.status_code == 200, created.text
    finance = created.json()["finance"]
    assert Decimal(finance["invoice_rate"]) == Decimal("88.000000")
    assert Decimal(finance["risk_rate"]) == Decimal("91.000000")
    assert Decimal(finance["average_rate"]) == Decimal("88.978261")
    assert Decimal(finance["invoice_total_currency"]) == Decimal("124000.00")
    assert Decimal(finance["risk_total_currency"]) == Decimal("60000.00")
