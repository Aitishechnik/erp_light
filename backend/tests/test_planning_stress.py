"""Стресс-сценарии планирования: переносы, пересогласования, отмены и правки.

Один и тот же план несколько раз проходит полный круг: корректировка →
утверждение → снятие годового согласования → повторное согласование →
расхождение с планом закупок → возврат в работу → правка нормы → утверждение.
Отдельно проверяются закрытие/переоткрытие месяца с разным фактом, черновики
переноса из решения месяца и отказы по ролям/статусам.
"""

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from tests.test_month_results import sales_xlsx, upload_sales
from tests.test_purchase_plans import (
    YEAR,
    _approve_plan,
    _create_plan,
    _item,
    _make_annual,
    _save,
)

MONTH = 1


def _annual(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/v1/annual-sales-plans", params={"year": YEAR})
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def _reapprove_annual(client: TestClient, login) -> None:
    login("commercial")
    submitted = client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit")
    assert submitted.status_code == 200, submitted.text
    login("executive")
    approved = client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve")
    assert approved.status_code == 200, approved.text


def _purchase(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/v1/purchase-plans", params={"year": YEAR})
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()
    return rows[0]


def _correction(
    client: TestClient,
    login,
    plan_id: str,
    catalog: dict[str, Any],
    quantity: str,
    *,
    action: str = "approve",
    month: int = MONTH,
) -> str:
    """Менеджер предлагает корректировку; вернуть её id независимо от исхода."""
    login("sales")
    created = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_id})
    assert created.status_code == 201, created.text
    correction_id = str(created.json()["id"])
    saved = client.put(
        f"/api/v1/sales-plan-corrections/{correction_id}/items",
        json={
            "items": [
                {
                    "client_id": str(catalog["customer"].id),
                    "product_id": str(catalog["fin"].id),
                    "month": month,
                    "quantity": quantity,
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    submitted = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/submit")
    assert submitted.status_code == 200, submitted.text
    login("commercial")
    if action == "approve":
        approved = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve")
        assert approved.status_code == 200, approved.text
    elif action == "reject":
        rejected = client.post(
            f"/api/v1/sales-plan-corrections/{correction_id}/reject",
            json={"reason": "не согласовано с клиентом"},
        )
        assert rejected.status_code == 200, rejected.text
    return correction_id


def _plan_month_item(client: TestClient, login, plan_id: str, month: int) -> str | None:
    login("commercial")
    plan: dict[str, Any] = client.get(f"/api/v1/sales-plans/{plan_id}").json()
    for item in plan["items"]:
        if item["month"] == month:
            return str(item["quantity"])
    return None


def test_correction_loop_reapproves_annual_and_purchase(client: TestClient, login, catalog) -> None:
    """Три круга правок: каждый раз снимаем и заново даём годовое согласование."""
    plan_ids = _make_annual(client, login, catalog)
    purchase = _create_plan(client, login)
    saved = _save(client, purchase["id"], [_item(catalog, quantity="30", norm="1.5")])
    assert saved.status_code == 200, saved.text
    _approve_plan(client, login, purchase["id"])

    login("commercial")
    assert _annual(client)["status"] == "approved"

    # Круг 1: январь 100 → 150. Годовое согласование снимается.
    _correction(client, login, plan_ids["sales"], catalog, "150")
    login("commercial")
    assert _annual(client)["status"] == "revision"
    _reapprove_annual(client, login)
    login("commercial")
    assert _annual(client)["status"] == "approved"
    assert _plan_month_item(client, login, plan_ids["sales"], MONTH) == "150.000"

    # План закупок видит расхождение: утверждённый сначала возвращаем в работу.
    login("purchase")
    body = _purchase(client)
    assert body["source"]["state"] == "changed"
    blocked = client.post(f"/api/v1/purchase-plans/{body['id']}/acknowledge-source")
    assert blocked.status_code == 409
    requested = client.post(
        f"/api/v1/purchase-plans/{body['id']}/request-revision",
        json={"reason": "план продаж пересмотрен"},
    )
    assert requested.status_code == 200, requested.text
    login("executive")
    reopened = client.post(
        f"/api/v1/purchase-plans/{body['id']}/reopen", json={"reason": "пересмотр плана продаж"}
    )
    assert reopened.status_code == 200, reopened.text
    login("purchase")
    accepted = client.post(f"/api/v1/purchase-plans/{body['id']}/acknowledge-source")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["source"]["state"] == "ok"
    assert client.post(f"/api/v1/purchase-plans/{body['id']}/submit").status_code == 200
    login("executive")
    assert client.post(f"/api/v1/purchase-plans/{body['id']}/approve").status_code == 200

    # Круг 2: январь 150 → 80, норма 1,5 → 1,7, план закупок заново утверждён.
    _correction(client, login, plan_ids["sales"], catalog, "80")
    _reapprove_annual(client, login)
    login("purchase")
    body = _purchase(client)
    assert body["source"]["state"] == "changed"
    assert (
        client.post(
            f"/api/v1/purchase-plans/{body['id']}/request-revision", json={"reason": "круг 2"}
        ).status_code
        == 200
    )
    login("executive")
    assert (
        client.post(
            f"/api/v1/purchase-plans/{body['id']}/reopen", json={"reason": "круг 2"}
        ).status_code
        == 200
    )
    login("purchase")
    accepted = client.post(f"/api/v1/purchase-plans/{body['id']}/acknowledge-source")
    assert accepted.status_code == 200, accepted.text
    items = [{**row} for row in body["items"]]
    items[0]["norm"] = "1.7"
    saved = client.put(f"/api/v1/purchase-plans/{body['id']}/items", json={"items": items})
    assert saved.status_code == 200, saved.text
    submitted_plan = client.post(f"/api/v1/purchase-plans/{body['id']}/submit")
    assert submitted_plan.status_code == 200, submitted_plan.text
    login("executive")
    assert client.post(f"/api/v1/purchase-plans/{body['id']}/approve").status_code == 200

    # Круг 3: 80 → 120, снова снимаем и возвращаем годовое согласование.
    _correction(client, login, plan_ids["sales"], catalog, "120")
    _reapprove_annual(client, login)
    login("commercial")
    assert _annual(client)["status"] == "approved"
    login("purchase")
    assert _purchase(client)["source"]["state"] == "changed"
    assert _purchase(client)["status"] == "approved"


def test_correction_can_be_rejected_deleted_and_goes_stale(
    client: TestClient, login, catalog
) -> None:
    """Отклонение и удаление не меняют план; правка плана делает корректировку неактуальной."""
    plan_ids = _make_annual(client, login, catalog)

    rejected = _correction(client, login, plan_ids["sales"], catalog, "130", action="reject")
    login("commercial")
    pending = client.get(f"/api/v1/sales-plan-corrections/{rejected}").json()
    assert pending["status"] == "rejected"
    assert _plan_month_item(client, login, plan_ids["sales"], MONTH) == "100.000"
    assert _annual(client)["status"] == "approved"

    # Пустой черновик удаляется; план не тронут.
    login("sales")
    created = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_ids["sales"]})
    assert created.status_code == 201, created.text
    draft_id = str(created.json()["id"])
    assert client.delete(f"/api/v1/sales-plan-corrections/{draft_id}").status_code == 204
    assert client.get(f"/api/v1/sales-plan-corrections/{draft_id}").status_code == 404

    # Открытая корректировка одна: вторую создать нельзя.
    first = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_ids["sales"]})
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/sales-plan-corrections", json={"plan_id": plan_ids["sales"]})
    assert second.status_code == 409, second.text

    # Пока корректировка открыта, коммерческий правит план напрямую — она устаревает.
    login("commercial")
    changed = client.put(
        f"/api/v1/sales-plans/{plan_ids['sales']}/items",
        json={
            "items": [
                {
                    "client_id": str(catalog["customer"].id),
                    "product_id": str(catalog["fin"].id),
                    "month": MONTH,
                    "quantity": "90",
                }
            ]
        },
    )
    assert changed.status_code == 200, changed.text
    login("sales")
    stale = client.post(f"/api/v1/sales-plan-corrections/{first.json()['id']}/submit")
    assert stale.status_code == 409, stale.text


def test_month_reopen_recalculates_signals_and_carryover(
    client: TestClient, login, catalog, db_session: Session
) -> None:
    """Закрыли с перевыполнением, открыли, закрыли с недобором — история сохраняется."""
    _make_annual(client, login, catalog)
    purchase = _create_plan(client, login)
    _save(client, purchase["id"], [_item(catalog, quantity="30", norm="1.5")])
    _approve_plan(client, login, purchase["id"])

    login("commercial")
    uploaded = upload_sales(
        client,
        sales_xlsx(
            [
                (
                    "ООО Ромашка",
                    [("Смесь ореховая", "150", "15000"), ("Финики", "50", "5000")],
                )
            ],
            period=f"Январь {YEAR}",
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    closed = client.post(f"/api/v1/month-results/{YEAR}/{MONTH}/close")
    assert closed.status_code == 200, closed.text

    over = list(
        db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "purchase_plan.revision_needed")
        )
        .scalars()
        .all()
    )
    assert len(over) == 1
    payload = over[0].payload
    assert payload is not None
    assert Decimal(payload["lines"][0]["delta_kg"]) == Decimal("75")

    # Открываем месяц, грузим другой факт и закрываем заново.
    login("commercial")
    reopened = client.post(
        f"/api/v1/month-results/{YEAR}/{MONTH}/reopen", json={"reason": "ошибка выгрузки"}
    )
    assert reopened.status_code == 200, reopened.text
    assert (
        client.post(f"/api/v1/month-results/{YEAR}/{MONTH}/reopen", json={"reason": ""}).status_code
        == 422
    )
    uploaded = upload_sales(
        client,
        sales_xlsx(
            [
                (
                    "ООО Ромашка",
                    [("Смесь ореховая", "60", "6000"), ("Финики", "50", "5000")],
                )
            ],
            period=f"Январь {YEAR}",
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post(f"/api/v1/month-results/{YEAR}/{MONTH}/close").status_code == 200

    carry = list(
        db_session.execute(select(AuditEvent).where(AuditEvent.action == "purchase_plan.carryover"))
        .scalars()
        .all()
    )
    assert len(carry) == 1
    assert "ниже плана" in carry[0].summary

    # История закрытий хранит обе версии.
    login("commercial")
    history = client.get(f"/api/v1/month-results/{YEAR}/{MONTH}/history").json()
    assert len(history) == 2
    assert history[0]["version"] == 1
    assert history[1]["version"] == 2

    # План закупок показывает остаток по последнему закрытому месяцу.
    login("purchase")
    body = _purchase(client)
    item = body["items"][0]
    assert item["carryover_month"] == MONTH
    assert Decimal(item["carryover"]) == Decimal("60.000")


def test_transfer_drafts_from_month_decision(client: TestClient, login, catalog) -> None:
    """Решение «перенести в план продаж» создаёт черновик, утверждение снимает годовое."""
    plan_ids = _make_annual(client, login, catalog)

    login("commercial")
    uploaded = upload_sales(
        client,
        sales_xlsx(
            [
                (
                    "ООО Ромашка",
                    [("Смесь ореховая", "70", "7000"), ("Финики", "50", "5000")],
                )
            ],
            period=f"Январь {YEAR}",
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    decision = client.put(
        f"/api/v1/month-results/{YEAR}/{MONTH}/decision",
        json={
            "decision": "transfer_sales",
            "target_year": YEAR,
            "target_month": 2,
            "comment": "перенос недобора",
        },
    )
    assert decision.status_code == 200, decision.text
    assert client.post(f"/api/v1/month-results/{YEAR}/{MONTH}/close").status_code == 200

    drafts = client.post(f"/api/v1/month-results/{YEAR}/{MONTH}/transfer-draft")
    assert drafts.status_code == 200, drafts.text
    created = drafts.json()["created"]
    assert created, "недобор должен дать черновик"
    correction_id = created[0]["correction_id"]

    login("commercial")
    submitted = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/submit")
    assert submitted.status_code == 200, submitted.text
    approved = client.post(f"/api/v1/sales-plan-corrections/{correction_id}/approve")
    assert approved.status_code == 200, approved.text
    assert _annual(client)["status"] == "revision"

    _reapprove_annual(client, login)
    login("commercial")
    assert _annual(client)["status"] == "approved"
    # Перенос ушёл в февраль плана менеджера.
    plan = client.get(f"/api/v1/sales-plans/{plan_ids['sales']}").json()
    february = [row for row in plan["items"] if row["month"] == 2]
    assert any(Decimal(row["quantity"]) == Decimal("30.000") for row in february)


def test_planning_limits_and_roles(client: TestClient, login, catalog) -> None:
    """Отказы: нет годового плана, чужое утверждение, заморозка, дубли, версия."""
    login("purchase")
    blocked = client.post("/api/v1/purchase-plans", json={"year": YEAR})
    assert blocked.status_code == 409

    _make_annual(client, login, catalog)
    login("sales")
    empty = client.post("/api/v1/sales-plans", json={"year": YEAR})
    assert empty.status_code == 409  # второй план на год и менеджера
    # Роль: генеральный не утверждает план менеджера — сначала план на проверке.
    login("sales")
    extra = client.post("/api/v1/sales-plans", json={"year": YEAR - 1})
    assert extra.status_code == 201, extra.text
    assert (
        client.put(
            f"/api/v1/sales-plans/{extra.json()['id']}/items",
            json={
                "items": [
                    {
                        "client_id": str(catalog["customer"].id),
                        "product_id": str(catalog["fin"].id),
                        "month": 12,
                        "quantity": "10",
                    }
                ]
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/sales-plans/{extra.json()['id']}/submit").status_code == 200
    login("sales")
    assert client.post(f"/api/v1/sales-plans/{extra.json()['id']}/approve").status_code == 403

    # Заморозка: январь текущего года уже прошёл.
    login("sales")
    frozen = client.put(
        f"/api/v1/sales-plans/{extra.json()['id']}/items",
        json={
            "items": [
                {
                    "client_id": str(catalog["customer"].id),
                    "product_id": str(catalog["fin"].id),
                    "month": 1,
                    "quantity": "10",
                }
            ]
        },
    )
    assert frozen.status_code == 409, frozen.text

    # План закупок: дубль строки и устаревшая версия.
    purchase = _create_plan(client, login)
    first = _item(catalog, quantity="30")
    saved = _save(client, purchase["id"], [first])
    assert saved.status_code == 200, saved.text
    duplicate = _save(client, purchase["id"], [first, {**first}])
    assert duplicate.status_code == 400, duplicate.text
    stale = client.put(
        f"/api/v1/purchase-plans/{purchase['id']}/items",
        json={"items": [first], "version": "2000-01-01T00:00:00Z"},
    )
    assert stale.status_code == 409, stale.text


def test_purchase_plan_reject_resubmit_and_invalid_transitions(
    client: TestClient, login, catalog
) -> None:
    """Возврат на доработку, повторная отправка и запрет переходов не из того статуса."""
    _make_annual(client, login, catalog)
    purchase = _create_plan(client, login)
    _save(client, purchase["id"], [_item(catalog, quantity="30")])

    # Утвердить черновик нельзя, отклонить — тоже.
    login("executive")
    assert client.post(f"/api/v1/purchase-plans/{purchase['id']}/approve").status_code == 409
    assert (
        client.post(
            f"/api/v1/purchase-plans/{purchase['id']}/reject", json={"reason": "рано"}
        ).status_code
        == 409
    )
    login("purchase")
    assert client.post(f"/api/v1/purchase-plans/{purchase['id']}/submit").status_code == 200
    # Повторно отправить план на проверке нельзя.
    assert client.post(f"/api/v1/purchase-plans/{purchase['id']}/submit").status_code == 409
    login("executive")
    rejected = client.post(
        f"/api/v1/purchase-plans/{purchase['id']}/reject", json={"reason": "уточните цену"}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "draft"
    login("purchase")
    plan = client.get(f"/api/v1/purchase-plans/{purchase['id']}").json()
    assert plan["status"] == "draft"
    assert "уточните цену" in (plan["notes"] or "")
    assert client.post(f"/api/v1/purchase-plans/{purchase['id']}/submit").status_code == 200
    login("executive")
    assert client.post(f"/api/v1/purchase-plans/{purchase['id']}/approve").status_code == 200

    # Утверждённый план удалить нельзя; удаление — только черновик.
    login("purchase")
    assert client.delete(f"/api/v1/purchase-plans/{purchase['id']}").status_code == 409


def test_sales_plan_reject_and_roles(client: TestClient, login, catalog) -> None:
    """План менеджера: возврат с причиной, повторная отправка, чужие роли."""
    login("sales")
    created = client.post("/api/v1/sales-plans", json={"year": YEAR})
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    # Пустой план отправить нельзя.
    assert client.post(f"/api/v1/sales-plans/{plan_id}/submit").status_code == 400
    assert (
        client.put(
            f"/api/v1/sales-plans/{plan_id}/items",
            json={
                "items": [
                    {
                        "client_id": str(catalog["customer"].id),
                        "product_id": str(catalog["fin"].id),
                        "month": 1,
                        "quantity": "100",
                    }
                ]
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/sales-plans/{plan_id}/submit").status_code == 200
    login("commercial")
    rejected = client.post(f"/api/v1/sales-plans/{plan_id}/reject", json={"reason": "мало объёма"})
    assert rejected.status_code == 200, rejected.text
    assert "мало объёма" in (rejected.json()["notes"] or "")
    # Отклонённый план остаётся редактируемым и отправляется заново.
    login("sales")
    assert (
        client.put(
            f"/api/v1/sales-plans/{plan_id}/items",
            json={
                "items": [
                    {
                        "client_id": str(catalog["customer"].id),
                        "product_id": str(catalog["fin"].id),
                        "month": 1,
                        "quantity": "120",
                    }
                ]
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/sales-plans/{plan_id}/submit").status_code == 200
    login("commercial")
    assert client.post(f"/api/v1/sales-plans/{plan_id}/approve").status_code == 200
    # Менеджер не утверждает план и не отправляет годовой.
    login("sales")
    assert client.post(f"/api/v1/sales-plans/{plan_id}/approve").status_code == 403
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit").status_code == 403


def test_annual_reopen_reject_and_final_approval(client: TestClient, login, catalog) -> None:
    """Годовой план: вернуть в работу, отправить заново, отклонить и согласовать."""
    _make_annual(client, login, catalog)

    login("executive")
    reopened = client.post(
        f"/api/v1/annual-sales-plans/{YEAR}/reopen", json={"reason": "пересмотр состава"}
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "revision"

    login("commercial")
    submitted = client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit")
    assert submitted.status_code == 200, submitted.text
    login("executive")
    rejected = client.post(
        f"/api/v1/annual-sales-plans/{YEAR}/reject", json={"reason": "уточнить объёмы"}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "revision"

    login("commercial")
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/submit").status_code == 200
    login("executive")
    approved = client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    # Повторно утвердить уже согласованный план нельзя.
    assert client.post(f"/api/v1/annual-sales-plans/{YEAR}/approve").status_code == 409
