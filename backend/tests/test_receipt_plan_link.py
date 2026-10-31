"""Связь позиций поступления со строками плана закупок и факт по строкам.

Контракты: [`docs/data-contract-receipts.md`](../../docs/data-contract-receipts.md) §2.1 и
[`docs/data-contract-planning.md`](../../docs/data-contract-planning.md) §4.5.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.helpers import put_batch
from tests.test_batch_items import part_row, upload_items
from tests.test_purchase_plans import YEAR, _create_plan, _item, _make_annual, _save


def _approved_plan(client: TestClient, login, catalog: dict[str, Any]) -> dict[str, Any]:
    """Годовой план + утверждённый план закупок с одной строкой RAW-1 (30 кг)."""
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="30", price="500.00")])
    assert saved.status_code == 200, saved.text
    line = saved.json()["items"][0]

    login("purchase")
    assert client.post(f"/api/v1/purchase-plans/{plan['id']}/submit").status_code == 200
    login("executive")
    approved = client.post(f"/api/v1/purchase-plans/{plan['id']}/approve")
    assert approved.status_code == 200, approved.text
    login("purchase")
    return {"plan": plan, "line": line}


def _receipt(
    number: str,
    *,
    product_code: str = "RAW-1",
    quantity: str = "12",
    plan_item_id: str | None = None,
    when: str | None = None,
) -> dict[str, Any]:
    return {
        "batch_number": number,
        "batch_date": when or f"{YEAR}-03-01",
        "currency": "RUB",
        "current_exchange_rate": "1",
        "supplier": "ООО Импорт",
        "items": [
            {
                "product_code": product_code,
                "quantity": quantity,
                "unit_price_currency": "10",
                "purchase_plan_item_id": plan_item_id,
            }
        ],
        "expenses": [],
        "payments": [],
    }


def _plan(client: TestClient, plan_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/purchase-plans/{plan_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_receipt_item_links_to_plan_line_and_counts_in_fact(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    data = _approved_plan(client, login, catalog)
    line = data["line"]

    body = put_batch(client, _receipt("ИТ-1", plan_item_id=str(line["id"])))
    item = body["items"][0]
    assert item["purchase_plan_item_id"] == str(line["id"])
    assert item["purchase_plan_label"] == f"{YEAR} · Таиланд"

    plan = _plan(client, data["plan"]["id"])
    fact = plan["items"][0]
    assert fact["id"] == line["id"]
    assert Decimal(fact["fact_quantity"]) == Decimal("12.000")
    assert Decimal(fact["fact_share"]) == Decimal("40.0")  # 12 из 30
    # Поступление от 1 марта попадает в март.
    assert fact["fact_months"] == [{"month": 3, "quantity": "12.000"}]


def test_unlinked_receipts_are_not_counted(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    data = _approved_plan(client, login, catalog)
    put_batch(client, _receipt("ИТ-1", plan_item_id=str(data["line"]["id"])))
    without_plan = put_batch(client, _receipt("ИТ-2", quantity="100"))
    assert without_plan["items"][0]["purchase_plan_item_id"] is None
    assert without_plan["items"][0]["purchase_plan_label"] is None

    # Факт — только по явной ссылке, а не по совпадению сырья.
    fact = _plan(client, data["plan"]["id"])["items"][0]
    assert Decimal(fact["fact_quantity"]) == Decimal("12.000")


def test_link_requires_the_same_raw_material(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    data = _approved_plan(client, login, catalog)
    response = put_batch(
        client,
        _receipt("ИТ-1", product_code="RAW-2", plan_item_id=str(data["line"]["id"])),
        expect=400,
    )
    assert "другое сырьё" in response.json()["detail"]


def test_import_of_items_drops_the_link(client: TestClient, login, catalog: dict[str, Any]) -> None:
    data = _approved_plan(client, login, catalog)
    body = put_batch(client, _receipt("ИТ-1", plan_item_id=str(data["line"]["id"])))
    assert body["items"][0]["purchase_plan_item_id"]

    response = upload_items(client, body["id"], part_row(1, "Арахис", "20"))
    assert response.status_code == 200, response.text
    # Строки поступления пересозданы — привязку нужно поставить заново.
    assert response.json()["batch"]["items"][0]["purchase_plan_item_id"] is None


def test_link_can_be_changed_after_customs(
    client: TestClient, login, catalog: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _approved_plan(client, login, catalog)
    body = put_batch(client, _receipt("ИТ-1", plan_item_id=str(data["line"]["id"])))

    customs = client.post(
        f"/api/v1/batches/{body['id']}/customs",
        json={"customs_date": f"{YEAR}-03-10", "rate": "1"},
    )
    assert customs.status_code == 200, customs.text
    assert customs.json()["items"][0]["purchase_plan_item_id"] == str(data["line"]["id"])

    # Ссылка не влияет на себестоимость — её можно снять и после растаможки.
    payload = _receipt("ИТ-1", plan_item_id=None)
    payload["items"][0]["id"] = body["items"][0]["id"]
    changed = client.put(f"/api/v1/batches/{body['id']}", json=payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["items"][0]["purchase_plan_item_id"] is None
    fact = _plan(client, data["plan"]["id"])["items"][0]
    assert Decimal(fact["fact_quantity"]) == Decimal("0")
    assert Decimal(fact["fact_share"]) == Decimal("0")


def test_plan_edit_keeps_line_ids_and_blocks_structural_changes(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    saved = _save(client, plan["id"], [_item(catalog, quantity="30")])
    item = saved.json()["items"][0]
    put_batch(client, _receipt("ИТ-1", plan_item_id=str(item["id"])))

    # Сохранение с тем же id обновляет строку на месте — ссылка цела.
    updated = _save(client, plan["id"], [{**_item(catalog, quantity="40"), "id": item["id"]}])
    assert updated.status_code == 200, updated.text
    again = updated.json()["items"][0]
    assert again["id"] == item["id"]
    assert Decimal(again["fact_quantity"]) == Decimal("12.000")

    # Убрать связанную строку или сменить у неё сырьё нельзя.
    removed = _save(client, plan["id"], [])
    assert removed.status_code == 409
    assert "нельзя убрать" in removed.json()["detail"]
    rewritten = _save(
        client,
        plan["id"],
        [{**_item(catalog, raw="raw2"), "id": item["id"]}],
    )
    assert rewritten.status_code == 409
    assert "менять нельзя" in rewritten.json()["detail"]

    # Сам план с поступлениями удалить тоже нельзя.
    assert client.delete(f"/api/v1/purchase-plans/{plan['id']}").status_code == 409


def test_new_plan_line_gets_a_new_id(client: TestClient, login, catalog: dict[str, Any]) -> None:
    _make_annual(client, login, catalog)
    plan = _create_plan(client, login)
    first = _save(client, plan["id"], [_item(catalog, quantity="30")]).json()["items"][0]
    second = _save(client, plan["id"], [_item(catalog, quantity="30")]).json()["items"][0]
    assert second["id"] != first["id"]


def test_fact_is_split_by_month_and_overbuy_is_not_blocked(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    """Факт раскладывается по месяцам прихода; больше плана — не ошибка."""
    data = _approved_plan(client, login, catalog)
    line_id = str(data["line"]["id"])
    put_batch(
        client,
        _receipt("ИТ-1", quantity="40", plan_item_id=line_id, when=f"{YEAR}-03-10"),
    )
    put_batch(
        client,
        _receipt("ИТ-2", quantity="50", plan_item_id=line_id, when=f"{YEAR}-04-05"),
    )

    item = _plan(client, data["plan"]["id"])["items"][0]
    assert item["fact_months"] == [
        {"month": 3, "quantity": "40.000"},
        {"month": 4, "quantity": "50.000"},
    ]
    assert Decimal(item["fact_quantity"]) == Decimal("90.000")
    # 90 при плане 30 — перезакуп, сервер его не блокирует.
    assert Decimal(item["fact_share"]) == Decimal("300.0")


def test_receipt_outside_plan_year_goes_to_boundary_month(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    """Декабрь прошлого года — в январь плана, январь следующего — в декабрь."""
    data = _approved_plan(client, login, catalog)
    line_id = str(data["line"]["id"])
    put_batch(
        client,
        _receipt("ИТ-1", quantity="5", plan_item_id=line_id, when=f"{YEAR - 1}-12-20"),
    )
    put_batch(
        client,
        _receipt("ИТ-2", quantity="7", plan_item_id=line_id, when=f"{YEAR + 1}-01-15"),
    )

    item = _plan(client, data["plan"]["id"])["items"][0]
    assert item["fact_months"] == [
        {"month": 1, "quantity": "5.000"},
        {"month": 12, "quantity": "7.000"},
    ]
    assert Decimal(item["fact_quantity"]) == Decimal("12.000")
