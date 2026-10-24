"""Растаможка партии: пошлина и НДС фиксируются в рублях на дату очистки.

Контракт — [`docs/data-contract-receipts.md`](../../docs/data-contract-receipts.md) §4:
курс берётся на дату растаможки (она не совпадает с датой прихода товара) и больше не
меняется; проценты в строках заменяются рублями; растаможенная партия не даёт править
строки — только отменить растаможку.
"""

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from openpyxl import Workbook

from app.services import currency_service
from tests.helpers import create_receipt_draft

DAY = "2026-10-08"
CUSTOMS_DAY = "2026-10-20"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(day: date) -> currency_service.CbrRates:
        raise currency_service.RateError("ЦБ РФ недоступен в тесте")

    monkeypatch.setattr(currency_service, "fetch_cbr_rates", fail)


def _item(**overrides: object) -> dict[str, object]:
    """Строка: 10 шт по 100 $, пошлина 5 %, НДС 22 %, Risk 1 $/шт."""
    item: dict[str, object] = {
        "product_code": "ТОВ1",
        "product_name": "Товар 1",
        "quantity": "10",
        "unit_price_currency": "100.00",
        "duty_percent": "5",
        "vat_percent": "22",
        "risk_unit_currency": "1",
    }
    item.update(overrides)
    return item


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "batch_number": "P-200",
        "batch_date": DAY,
        "currency": "USD",
        "current_exchange_rate": "90",
        "items": [_item()],
        "expenses": [],
    }
    payload.update(overrides)
    return payload


def _create(client: TestClient, **overrides: object) -> dict[str, Any]:
    """Поступление как в жизни: черновик из 1С, затем заполнение карточки."""
    payload = _payload(**overrides)
    draft = create_receipt_draft(client, str(payload["batch_number"]))
    response = client.put(f"/api/v1/batches/{draft['id']}", json=payload)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _customs(client: TestClient, batch_id: object, **body: object) -> Response:
    payload: dict[str, object] = {"customs_date": CUSTOMS_DAY, "rate": "80"}
    payload.update(body)
    return client.post(f"/api/v1/batches/{batch_id}/customs", json=payload)


def _draft(client: TestClient) -> dict[str, Any]:
    """Черновик из выгрузки 1С: поступление без позиций."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        ["УУ", "Дата", "Номер", "Вид операции", "Сумма", "Валюта", "Контрагент", "Комментарий"]
    )
    sheet.append(["Да", "13.10.2026", "ИТ-ЧЕРНОВИК", "покупка", "1000", "USD", "Фирма", ""])
    buffer = BytesIO()
    workbook.save(buffer)
    response = client.post(
        "/api/v1/imports/import_receipts",
        files={
            "file": ("ИмпортныеПоступления.xlsx", buffer.getvalue(), XLSX_TYPE),
        },
    )
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = client.get("/api/v1/batches").json()
    return next(row for row in rows if row["batch_number"] == "ИТ-ЧЕРНОВИК")


def test_customs_fixes_duty_and_vat_in_rubles(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Растаможка по курсу 80: пошлина 4 000 ₽, НДС 18 480 ₽ — и это навсегда."""
    login("purchase")
    _no_network(monkeypatch)
    batch = _create(client)
    assert batch["customs_date"] is None

    response = _customs(client, batch["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["customs_date"] == CUSTOMS_DAY
    assert Decimal(body["customs_rate"]) == Decimal("80")
    assert Decimal(body["items"][0]["duty_fixed_rub"]) == Decimal("4000.00")
    assert Decimal(body["items"][0]["vat_fixed_rub"]) == Decimal("18480.00")
    # Валютные надбавки остались: 50 $ пошлины и 231 $ НДС.
    assert (Decimal(body["finance"]["duty_rub"]), Decimal(body["finance"]["vat_rub"])) == (
        Decimal("4000.00"),
        Decimal("18480.00"),
    )
    # Курс партии 90: 1000 × 90 + 4 000 + 18 480 + 10 × 90 = 113 380 ₽.
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("113380.00")

    # Курс партии вырос до 95 — товар и Risk дороже, таможня та же.
    updated = client.put(
        f"/api/v1/batches/{batch['id']}",
        json=_payload(current_exchange_rate="95"),
    )
    assert updated.status_code == 200, updated.text
    after = updated.json()
    assert Decimal(after["finance"]["duty_rub"]) == Decimal("4000.00")
    assert Decimal(after["finance"]["vat_rub"]) == Decimal("18480.00")
    # 1000 × 95 + 4 000 + 18 480 + 10 × 95 = 118 430 ₽.
    assert Decimal(after["finance"]["final_cost_rub"]) == Decimal("118430.00")


def test_customs_manual_totals_are_distributed_exactly(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Правка итога в окне подтверждения: строки в сумме дают ровно введённое число."""
    login("purchase")
    _no_network(monkeypatch)
    batch = _create(
        client,
        items=[
            _item(product_code="ТОВ1"),
            _item(product_code="ТОВ2", product_name="Товар 2", duty_percent="10"),
        ],
    )
    response = _customs(client, batch["id"], duty_rub="100.00", vat_rub="0")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    # Веса — валютная пошлина строк: 50 $ и 100 $ → 33,33 ₽ и 66,67 ₽.
    assert [Decimal(row["duty_fixed_rub"]) for row in items] == [
        Decimal("33.33"),
        Decimal("66.67"),
    ]
    assert [Decimal(row["vat_fixed_rub"]) for row in items] == [
        Decimal("0.00"),
        Decimal("0.00"),
    ]
    assert Decimal(response.json()["finance"]["duty_rub"]) == Decimal("100.00")


def test_customs_locks_items_but_not_expenses(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Строки растаможенной партии неизменны, общие расходы — правятся."""
    login("purchase")
    _no_network(monkeypatch)
    batch = _create(client)
    assert _customs(client, batch["id"]).status_code == 200

    locked = client.put(
        f"/api/v1/batches/{batch['id']}",
        json=_payload(items=[_item(quantity="12")]),
    )
    assert locked.status_code == 400, locked.text
    assert "строки изменить нельзя" in locked.json()["detail"]

    # Валюта — база фикса: её смена тоже запрещена.
    currency = client.put(
        f"/api/v1/batches/{batch['id']}",
        json=_payload(currency="EUR"),
    )
    assert currency.status_code == 400, currency.text
    assert "валюту изменить нельзя" in currency.json()["detail"]

    expenses = client.put(
        f"/api/v1/batches/{batch['id']}",
        json=_payload(
            expenses=[{"amount_currency": "500.00", "currency": "RUB", "description": "Доставка"}]
        ),
    )
    assert expenses.status_code == 200, expenses.text
    body = expenses.json()
    # Фикс таможни цел, расходы вошли в себестоимость.
    assert Decimal(body["finance"]["duty_rub"]) == Decimal("4000.00")
    assert Decimal(body["finance"]["final_cost_rub"]) == Decimal("113880.00")


def test_customs_can_be_cancelled_by_purchase_director(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отмена растаможки: только директор по закупкам, проценты возвращаются в строки."""
    login("purchase")
    _no_network(monkeypatch)
    batch = _create(client)
    assert _customs(client, batch["id"]).status_code == 200

    login("import")
    forbidden = client.delete(f"/api/v1/batches/{batch['id']}/customs")
    assert forbidden.status_code == 403

    login("purchase")
    cancelled = client.delete(f"/api/v1/batches/{batch['id']}/customs")
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["customs_date"] is None
    assert body["customs_rate"] is None
    assert body["items"][0]["duty_fixed_rub"] is None
    assert body["items"][0]["vat_fixed_rub"] is None
    # Снова проценты: пошлина 50 $ × 90 = 4 500 ₽ (курс партии, а не 80).
    assert Decimal(body["finance"]["duty_rub"]) == Decimal("4500.00")

    # И строки снова можно править.
    edited = client.put(
        f"/api/v1/batches/{batch['id']}",
        json=_payload(items=[_item(quantity="12")]),
    )
    assert edited.status_code == 200, edited.text


def test_customs_cannot_be_applied_twice(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Повторная растаможка и отмена нерастаможенной партии — понятные отказы."""
    login("purchase")
    _no_network(monkeypatch)
    batch = _create(client)
    nothing_to_cancel = client.delete(f"/api/v1/batches/{batch['id']}/customs")
    assert nothing_to_cancel.status_code == 400
    assert "не растаможена" in nothing_to_cancel.json()["detail"]

    assert _customs(client, batch["id"]).status_code == 200
    again = _customs(client, batch["id"])
    assert again.status_code == 400
    assert "уже растаможена" in again.json()["detail"]


def test_customs_needs_items_and_existing_batch(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Черновик из 1С растаможить нечем; чужой идентификатор — 404."""
    login("purchase")
    _no_network(monkeypatch)
    draft = _draft(client)
    empty = _customs(client, draft["id"])
    assert empty.status_code == 400
    assert "нет позиций" in empty.json()["detail"]

    missing = _customs(client, "00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


def test_import_items_are_locked_after_customs(
    client: TestClient, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Позиции из файла «Партия» не заменяют строки растаможенной партии."""
    login("purchase")
    _no_network(monkeypatch)
    batch = _create(client)
    assert _customs(client, batch["id"]).status_code == 200
    response = client.post(
        f"/api/v1/batches/{batch['id']}/import-items",
        files={"file": ("Партия.xlsx", b"not-a-book", XLSX_TYPE)},
    )
    assert response.status_code == 400, response.text
    assert "строки изменить нельзя" in response.json()["detail"]
