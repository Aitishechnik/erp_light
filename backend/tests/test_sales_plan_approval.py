"""Годовой план отдела продаж и корректировки утверждённых планов."""

import uuid
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import SalesPlanItem

TODAY = date.today()
YEAR = TODAY.year


def _users(client: TestClient, login) -> dict[str, str]:
    login("commercial")
    rows = client.get("/api/v1/users", params={"role": "sales_manager"}).json()
    return {row["login"]: row["id"] for row in rows}


def _item(product: Product, client_row: Counterparty, quantity: str) -> dict[str, Any]:
    return {
        "client_id": str(client_row.id),
        "product_id": str(product.id),
        "month": TODAY.month,
        "quantity": quantity,
    }


def _make_plan(
    client: TestClient,
    login,
    manager_login: str,
    product: Product,
    client_row: Counterparty,
    quantity: str = "10",
) -> str:
    """Менеджер заполняет и отправляет план, коммерческий директор утверждает."""
    login(manager_login)
    created = client.post("/api/v1/sales-plans", json={"year": YEAR})
    assert created.status_code == 201, created.text
    plan_id = str(created.json()["id"])
    saved = client.put(
        f"/api/v1/sales-plans/{plan_id}/items",
        json={"items": [_item(product, client_row, quantity)]},
    )
    assert saved.status_code == 200, saved.text
    submitted = client.post(f"/api/v1/sales-plans/{plan_id}/submit")
    assert submitted.status_code == 200, submitted.text

    login("commercial")
    approved = client.post(f"/api/v1/sales-plans/{plan_id}/approve")
    assert approved.status_code == 200, approved.text
    return plan_id


def _make_all_plans(
    client: TestClient,
    login,
    products: list[Product],
    client_row: Counterparty,
) -> dict[str, str]:
    _users(client, login)
    return {
        "sales": _make_plan(client, login, "sales", products[0], client_row, "10"),
        "sales2": _make_plan(client, login, "sales2", products[1], client_row, "20"),
        "sales3": _make_plan(client, login, "sales3", products[2], client_row, "30"),
    }


def _approve_annual(client: TestClient, login) -> None:
    login("commercial")
    submitted = client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit")
    assert submitted.status_code == 200, submitted.text
    login("executive")
    approved = client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve")
    assert approved.status_code == 200, approved.text


def test_annual_needs_all_managers_and_gd_approval(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_row = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([*products, client_row])
    db_session.commit()

    _users(client, login)
    _make_plan(client, login, "sales", products[0], client_row)
    _make_plan(client, login, "sales2", products[1], client_row)

    login("commercial")
    blocked = client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit")
    assert blocked.status_code == 409, blocked.text
    assert "Менеджер по продажам 3" in blocked.json()["detail"]

    _make_plan(client, login, "sales3", products[2], client_row)

    login("sales")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit").status_code == 403

    login("commercial")
    submitted = client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "on_review"
    assert submitted.json()["all_approved"] is True
    assert submitted.json()["missing_managers"] == []
    assert len(submitted.json()["items"]) == 3
    # Коммерческий директор не может утвердить финальную версию сам.
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve").status_code == 403

    login("executive")
    approved = client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by_name"] == "Исполнительный директор (демо)"

    # Закупки и менеджеры видят утверждённый план; импорт — нет.
    login("purchase")
    assert client.get("/api/v1/annual-sales-plans", params={"year": YEAR}).status_code == 200
    login("sales")
    assert client.get("/api/v1/annual-sales-plans", params={"year": YEAR}).status_code == 200
    login("import")
    assert client.get("/api/v1/annual-sales-plans", params={"year": YEAR}).status_code == 403
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit").status_code == 403


def test_change_invalidates_gd_approval(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_row = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([*products, client_row])
    db_session.commit()
    plan_ids = _make_all_plans(client, login, products, client_row)
    _approve_annual(client, login)

    login("commercial")
    edited = client.put(
        f"/api/v1/sales-plans/{plan_ids['sales']}/items",
        json={"items": [_item(products[0], client_row, "77")]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "on_review"

    annual = client.get("/api/v1/annual-sales-plans", params={"year": YEAR})
    assert annual.status_code == 200, annual.text
    assert annual.json()["status"] == "revision"
    assert annual.json()["is_stale"] is True
    assert annual.json()["status_title"] == "Требует повторного согласования"

    login("executive")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve").status_code == 409

    login("commercial")
    assert client.post(f"/api/v1/sales-plans/{plan_ids['sales']}/approve").status_code == 200
    resubmitted = client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit")
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["status"] == "on_review"

    login("executive")
    reapproved = client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve")
    assert reapproved.status_code == 200, reapproved.text
    assert reapproved.json()["status"] == "approved"


def test_manager_correction_goes_through_commercial_and_gd(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_row = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([*products, client_row])
    db_session.commit()
    plan_ids = _make_all_plans(client, login, products, client_row)
    _approve_annual(client, login)

    login("sales")
    created = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_ids["sales"]})
    assert created.status_code == 201, created.text
    correction_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    saved = client.put(
        f"/api/v1/sales-plan-corrections/{correction_id}/items",
        json={
            "items": [
                {
                    "client_id": str(client_row.id),
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "99",
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["items"][0]["current_quantity"] == "10.000"

    submitted = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "on_review"
    # Менеджер не может утвердить корректировку сам.
    assert client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve").status_code == 403

    login("commercial")
    listed = client.get("/api/v1/sales-plan-corrections", params={"plan_id": plan_ids["sales"]})
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    approved = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    plan = client.get(f"/api/v1/sales-plans/{plan_ids['sales']}")
    assert plan.json()["items"][0]["quantity"] == "99.000"

    annual = client.get("/api/v1/annual-sales-plans", params={"year": YEAR})
    assert annual.json()["status"] == "revision"
    assert annual.json()["is_stale"] is True
    pending = client.get(f"/api/v1/sales-plan-corrections/{correction_id}").json()
    assert pending["annual_needs_reapproval"] is True

    _approve_annual(client, login)
    settled = client.get(f"/api/v1/sales-plan-corrections/{correction_id}").json()
    assert settled["annual_needs_reapproval"] is False

    # Вторая корректировка — коммерческий директор отклоняет.
    login("sales")
    second = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_ids["sales"]})
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    client.put(
        f"/api/v1/sales-plan-corrections/{second_id}/items",
        json={
            "items": [
                {
                    "client_id": str(client_row.id),
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "5",
                }
            ]
        },
    )
    client.post(f"/api/v1/sales-plan-corrections/{second_id}/submit")

    login("commercial")
    rejected = client.post(
        f"/api/v1/sales-plan-corrections/{second_id}/reject",
        json={"reason": "не согласовано"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["review_reason"] == "не согласовано"
    plan = client.get(f"/api/v1/sales-plans/{plan_ids['sales']}")
    assert plan.json()["items"][0]["quantity"] == "99.000"


def test_correction_rejects_stale_base(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_row = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([*products, client_row])
    db_session.commit()
    plan_ids = _make_all_plans(client, login, products, client_row)

    login("sales")
    created = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_ids["sales"]})
    correction_id = created.json()["id"]
    client.put(
        f"/api/v1/sales-plan-corrections/{correction_id}/items",
        json={
            "items": [
                {
                    "client_id": str(client_row.id),
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "50",
                }
            ]
        },
    )

    # Пока корректировка в черновике, план изменили и утвердили заново.
    login("commercial")
    client.put(
        f"/api/v1/sales-plans/{plan_ids['sales']}/items",
        json={"items": [_item(products[0], client_row, "60")]},
    )
    client.post(f"/api/v1/sales-plans/{plan_ids['sales']}/approve")

    login("sales")
    stale = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/submit")
    assert stale.status_code == 409, stale.text
    assert "План изменился" in stale.json()["detail"]


def test_full_copy_correction_adds_and_removes_positions(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_a = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    client_b = Counterparty(name="ООО Вектор", name_key="ооо вектор", is_customer=True)
    db_session.add_all([*products, client_a, client_b])
    db_session.commit()

    plan_ids = _make_all_plans(client, login, products, client_a)
    _approve_annual(client, login)
    plan_id = plan_ids["sales"]

    login("sales2")
    forbidden = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_id})
    assert forbidden.status_code == 403, forbidden.text

    login("sales")
    correction = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_id})
    assert correction.status_code == 201, correction.text
    correction_id = correction.json()["id"]
    # Черновик сразу содержит полную копию строк плана.
    assert [(row["product_id"], row["quantity"]) for row in correction.json()["items"]] == [
        (str(products[0].id), "10.000")
    ]

    saved = client.put(
        f"/api/v1/sales-plan-corrections/{correction_id}/items",
        json={
            "items": [
                {
                    "client_id": str(client_a.id),
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "25",
                },
                {
                    "client_id": str(client_b.id),
                    "product_id": str(products[1].id),
                    "month": TODAY.month,
                    "quantity": "7",
                },
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert client.post(f"/api/v1/sales-plan-corrections/{correction_id}/submit").status_code == 200
    login("commercial")
    assert client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve").status_code == 200

    plan = client.get(f"/api/v1/sales-plans/{plan_id}").json()
    quantities = {(row["client_id"], row["product_id"]): row["quantity"] for row in plan["items"]}
    assert quantities == {
        (str(client_a.id), str(products[0].id)): "25.000",
        (str(client_b.id), str(products[1].id)): "7.000",
    }

    # Вторая корректировка удаляет позицию: 0 в полной копии.
    login("sales")
    second = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_id})
    second_id = second.json()["id"]
    saved = client.put(
        f"/api/v1/sales-plan-corrections/{second_id}/items",
        json={
            "items": [
                {
                    "client_id": str(client_a.id),
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "25",
                },
                {
                    "client_id": str(client_b.id),
                    "product_id": str(products[1].id),
                    "month": TODAY.month,
                    "quantity": "0",
                },
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    client.post(f"/api/v1/sales-plan-corrections/{second_id}/submit")
    login("commercial")
    assert client.post(f"/api/v1/sales-plan-corrections/{second_id}/approve").status_code == 200
    plan = client.get(f"/api/v1/sales-plans/{plan_id}").json()
    assert [(row["client_id"], row["product_id"]) for row in plan["items"]] == [
        (str(client_a.id), str(products[0].id))
    ]


def test_commercial_can_create_and_apply_correction(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_row = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([*products, client_row])
    db_session.commit()
    plan_id = _make_all_plans(client, login, products, client_row)["sales"]
    _approve_annual(client, login)

    login("commercial")
    created = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_id})
    assert created.status_code == 201, created.text
    correction_id = created.json()["id"]
    saved = client.put(
        f"/api/v1/sales-plan-corrections/{correction_id}/items",
        json={
            "items": [
                {
                    "client_id": str(client_row.id),
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "30",
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    # Применить без отправки нельзя.
    assert client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve").status_code == 409
    assert client.post(f"/api/v1/sales-plan-corrections/{correction_id}/submit").status_code == 200
    assert client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve").status_code == 200
    plan = client.get(f"/api/v1/sales-plans/{plan_id}").json()
    assert plan["items"][0]["quantity"] == "30.000"


def test_executive_can_propose_and_approve_correction(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_row = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([*products, client_row])
    db_session.commit()
    plan_id = _make_all_plans(client, login, products, client_row)["sales"]
    _approve_annual(client, login)

    login("executive")
    created = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_id})
    assert created.status_code == 201, created.text
    correction_id = created.json()["id"]
    saved = client.put(
        f"/api/v1/sales-plan-corrections/{correction_id}/items",
        json={
            "items": [
                {
                    "client_id": str(client_row.id),
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "40",
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert client.post(f"/api/v1/sales-plan-corrections/{correction_id}/submit").status_code == 200
    # С 2026-10-26 корректировку утверждает и исполнительный директор.
    approved = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_correction_keeps_frozen_months_untouched(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_row = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([*products, client_row])
    db_session.commit()
    plan_ids = _make_all_plans(client, login, products, client_row)
    _approve_annual(client, login)

    # Январь уже утверждённого плана (заморожен); добавляем строку напрямую,
    # чтобы проверить, что корректировка его не копирует и не меняет.
    db_session.add(
        SalesPlanItem(
            plan_id=uuid.UUID(plan_ids["sales"]),
            client_id=client_row.id,
            product_id=products[1].id,
            month=1,
            quantity="5",
        )
    )
    db_session.commit()

    login("sales")
    created = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_ids["sales"]})
    correction_id = created.json()["id"]
    assert all(row["month"] != 1 for row in created.json()["items"])
    blocked = client.put(
        f"/api/v1/sales-plan-corrections/{correction_id}/items",
        json={
            "items": [
                {
                    "client_id": str(client_row.id),
                    "product_id": str(products[1].id),
                    "month": 1,
                    "quantity": "99",
                },
                {
                    "client_id": str(client_row.id),
                    "product_id": str(products[0].id),
                    "month": TODAY.month,
                    "quantity": "10",
                },
            ]
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert "Замороженные месяцы" in blocked.json()["detail"]


def test_admin_submits_annual_plan(
    client: TestClient,
    login,
    db_session: Session,
) -> None:
    """Исполнительный директор как администратор отправляет годовой план сам."""
    products = [
        Product(code="SKU-A", name="Товар A", kind="finished", unit="шт"),
        Product(code="SKU-B", name="Товар B", kind="finished", unit="шт"),
        Product(code="SKU-C", name="Товар C", kind="finished", unit="шт"),
    ]
    client_row = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([*products, client_row])
    db_session.commit()
    _make_all_plans(client, login, products, client_row)

    login("executive")
    submitted = client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "on_review"
    approved = client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
