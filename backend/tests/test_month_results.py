"""Итоги месяца: загрузка продаж из 1С, сопоставление и сравнение с планом."""

from decimal import Decimal
from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import SalesPlan, SalesPlanItem

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADER = (
    "",
    "Контрагент",
    "Сумма продажи в руб.",
    "Сумма продажи без скидок в руб.",
    "Количество (в базовых единицах)",
    "Сумма скидки в руб.",
    "% скидки",
    "Цена",
)


def sales_xlsx(
    groups: list[tuple[str, list[tuple[str, str, str]]]], *, period: str = "Октябрь 2026"
) -> bytes:
    """Отчёт 1С «Продажи»: шапка, жирные строки контрагентов, позиции с отступом."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["", "Продажи"])
    sheet.append(["", f"Период: {period} г."])
    sheet.append(["", "Показатели: Сумма продажи в руб.; Количество (в базовых единицах)"])
    sheet.append(["", "Группировки строк: Контрагент (Элементы); Номенклатура (Элементы);"])
    sheet.append(["", "Дополнительные поля: Базовая единица измерения"])
    sheet.append(["", "Сортировка: Контрагент.Наименование (По возрастанию)"])
    sheet.append([])
    sheet.append(list(HEADER))
    sheet.append(["", "Номенклатура, Базовая единица измерения"])

    total = Decimal("0")
    for client, items in groups:
        client_row = sheet.max_row + 1
        sheet.append(["", client, "", "", "", "", "", ""])
        sheet.cell(row=client_row, column=2).font = Font(bold=True)
        for name, quantity, amount in items:
            row = sheet.max_row + 1
            sheet.append(["", name, amount, amount, quantity, "", "", ""])
            sheet.cell(row=row, column=2).alignment = Alignment(indent=1)
            total += Decimal(amount)
    sheet.append(["", "Итог", str(total)])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def upload_sales(client: TestClient, content: bytes):
    return client.post(
        "/api/v1/imports/sales", files={"file": ("Продажи_Окт.xlsx", content, XLSX_TYPE)}
    )


def month(client: TestClient, year: int = 2026, month_number: int = 10):
    response = client.get(f"/api/v1/month-results?year={year}&month={month_number}")
    assert response.status_code == 200, response.text
    return response.json()


def _user(db: Session, login: str) -> User:
    return db.execute(select(User).where(User.login == login)).scalars().one()


def _plan(
    db: Session,
    manager: User,
    items: list[tuple[Counterparty, Product, str]],
    *,
    year: int = 2026,
    month_number: int = 10,
) -> SalesPlan:
    plan = SalesPlan(
        year=year,
        manager_id=manager.id,
        created_by_id=manager.id,
        status="approved",
    )
    plan.items = [
        SalesPlanItem(
            client_id=client.id,
            product_id=product.id,
            month=month_number,
            quantity=Decimal(quantity),
        )
        for client, product, quantity in items
    ]
    db.add(plan)
    db.commit()
    return plan


def test_sales_file_replaces_month(client: TestClient, login, catalog: dict[str, Any]) -> None:
    login("commercial")
    first = upload_sales(
        client,
        sales_xlsx(
            [
                (
                    "ООО Ромашка",
                    [
                        ("Смесь ореховая", "10", "1000"),
                        ("Финики", "5", "500"),
                    ],
                )
            ]
        ),
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["rows_total"] == 2
    assert body["rows_created"] == 2
    assert body["status"] == "ok"

    rows = month(client)["rows"]
    assert len(rows) == 2
    assert {row["group"] for row in rows} == {"extra"}
    assert sum(Decimal(row["fact_amount"]) for row in rows) == Decimal("1500")

    # Повторная загрузка месяца заменяет его целиком, а не суммирует.
    second = upload_sales(client, sales_xlsx([("ООО Ромашка", [("Смесь ореховая", "7", "700")])]))
    assert second.status_code == 200, second.text
    assert second.json()["rows_created"] == 1
    rows = month(client)["rows"]
    assert len(rows) == 1
    assert rows[0]["fact_quantity"] == "7.000"


def test_returns_are_negative(client: TestClient, login, catalog: dict[str, Any]) -> None:
    login("commercial")
    response = upload_sales(
        client,
        sales_xlsx([("ООО Ромашка", [("Смесь ореховая", "-3", "-300"), ("Финики", "4", "400")])]),
    )
    assert response.status_code == 200, response.text
    rows = {row["product_name"]: row for row in month(client)["rows"]}
    assert rows["Смесь ореховая"]["fact_quantity"] == "-3.000"
    assert rows["Смесь ореховая"]["fact_amount"] == "-300.00"


def test_unknown_client_rejects_file(client: TestClient, login, catalog: dict[str, Any]) -> None:
    login("commercial")
    response = upload_sales(
        client, sales_xlsx([("Новый магазин", [("Смесь ореховая", "1", "10")])])
    )
    assert response.status_code == 400
    assert "Новый магазин" in response.json()["detail"]
    assert month(client)["rows"] == []


def test_unmatched_product_goes_to_queue_and_alias(
    client: TestClient, login, catalog: dict[str, Any]
) -> None:
    login("commercial")
    response = upload_sales(
        client,
        sales_xlsx(
            [("ООО Ромашка", [("Смесь ореховая", "1", "10"), ("Загадочный товар", "2", "20")])]
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows_failed"] == 1
    assert body["status"] == "partial"

    summary = month(client)
    assert len(summary["rows"]) == 1
    assert len(summary["unmatched"]) == 1
    unmatched = summary["unmatched"][0]
    assert unmatched["source_name"] == "Загадочный товар"
    assert unmatched["client_name"] == "ООО Ромашка"

    matched = client.post(
        "/api/v1/month-results/2026/10/match",
        json={"unmatched_id": unmatched["id"], "product_id": str(catalog["fin2"].id)},
    )
    assert matched.status_code == 200, matched.text
    assert matched.json() == {"matched": 1, "remaining": 0}

    summary = month(client)
    assert summary["unmatched"] == []
    assert {row["product_name"] for row in summary["rows"]} == {"Смесь ореховая", "Финики"}

    # Алиас запомнен: та же строка в следующем файле сопоставляется сама.
    again = upload_sales(
        client,
        sales_xlsx(
            [("ООО Ромашка", [("Смесь ореховая", "1", "10"), ("Загадочный товар", "2", "20")])]
        ),
    )
    assert again.status_code == 200, again.text
    assert again.json()["rows_failed"] == 0
    assert month(client)["unmatched"] == []


def test_ambiguous_name_is_not_guessed(client: TestClient, login, db_session: Session) -> None:
    first = Product(code="DUP-1", name="Финики сушеные, вес", kind="finished", unit="кг")
    second = Product(code="DUP-2", name="Финики сушеные, вес, кг", kind="finished", unit="кг")
    customer = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    db_session.add_all([first, second, customer])
    db_session.commit()

    login("commercial")
    upload_sales(client, sales_xlsx([("ООО Ромашка", [("Финики сушеные, вес", "1", "10")])]))
    summary = month(client)
    assert summary["rows"] == []
    assert len(summary["unmatched"]) == 1


def test_plan_against_fact(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    manager = _user(db_session, "sales")
    customer = catalog["customer"]
    customer.manager_id = manager.id
    db_session.commit()
    _plan(
        db_session,
        manager,
        [
            (customer, catalog["fin"], "100"),
            (customer, catalog["fin2"], "5"),
        ],
    )

    login("commercial")
    upload_sales(
        client,
        sales_xlsx([("ООО Ромашка", [("Смесь ореховая", "80", "8000"), ("Арахис", "20", "2000")])]),
    )
    summary = month(client)
    rows = {row["product_name"]: row for row in summary["rows"]}

    planned = rows["Смесь ореховая"]
    assert planned["group"] == "plan"
    assert planned["plan_quantity"] == "100.000"
    assert planned["fact_quantity"] == "80.000"
    assert planned["deviation"] == "-20.000"
    assert planned["manager_name"] == "Менеджер по продажам (демо)"
    assert planned["manager_mismatch"] is False

    short = rows["Финики"]
    assert short["group"] == "short"
    assert short["fact_quantity"] == "0.000"

    extra = rows["Арахис"]
    assert extra["group"] == "extra"
    assert extra["plan_quantity"] == "0.000"
    assert extra["manager_name"] == "Менеджер по продажам (демо)"

    assert summary["deviation_lines"] == 3
    assert summary["extra_lines"] == 1
    assert summary["short_lines"] == 1
    assert summary["plan_approved"] is True


def test_manager_mismatch_is_visible(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    planner = _user(db_session, "sales")
    keeper = _user(db_session, "sales2")
    customer = catalog["customer"]
    customer.manager_id = keeper.id
    db_session.commit()
    _plan(db_session, planner, [(customer, catalog["fin"], "10")])

    login("commercial")
    upload_sales(client, sales_xlsx([("ООО Ромашка", [("Смесь ореховая", "10", "1000")])]))
    row = month(client)["rows"][0]
    # Плановая строка принадлежит тому, кто планировал, но видно расхождение.
    assert row["manager_name"] == "Менеджер по продажам (демо)"
    assert row["manager_mismatch"] is True


def test_sales_manager_sees_only_own_rows(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    first = _user(db_session, "sales")
    second = _user(db_session, "sales2")
    other = Counterparty(name="ООО Вектор", name_key="ооо вектор", is_customer=True)
    db_session.add(other)
    db_session.commit()
    catalog["customer"].manager_id = first.id
    other.manager_id = second.id
    db_session.commit()

    login("commercial")
    upload_sales(
        client,
        sales_xlsx(
            [
                ("ООО Ромашка", [("Смесь ореховая", "1", "10")]),
                ("ООО Вектор", [("Смесь ореховая", "2", "20")]),
            ]
        ),
    )
    assert {row["client_name"] for row in month(client)["rows"]} == {"ООО Ромашка", "ООО Вектор"}

    login("sales2")
    rows = month(client)["rows"]
    assert [row["client_name"] for row in rows] == ["ООО Вектор"]


def test_roles_of_month_results(client: TestClient, login, catalog: dict[str, Any]) -> None:
    login("import")
    assert client.get("/api/v1/month-results?year=2026&month=10").status_code == 403
    denied = upload_sales(client, sales_xlsx([("ООО Ромашка", [("Смесь ореховая", "1", "10")])]))
    assert denied.status_code == 403

    login("purchase")
    assert client.get("/api/v1/month-results?year=2026&month=10").status_code == 200

    login("executive")
    assert client.get("/api/v1/month-results?year=2026&month=10").status_code == 200


def test_counterparty_manager_is_assigned(
    client: TestClient, login, catalog: dict[str, Any], db_session: Session
) -> None:
    manager = _user(db_session, "sales")
    importer = _user(db_session, "import")
    login("commercial")
    bad = client.patch(
        f"/api/v1/counterparties/{catalog['customer'].id}",
        json={"manager_id": str(importer.id)},
    )
    assert bad.status_code == 400

    ok = client.patch(
        f"/api/v1/counterparties/{catalog['customer'].id}",
        json={"manager_id": str(manager.id)},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["manager_id"] == str(manager.id)
    assert body["manager_name"] == "Менеджер по продажам (демо)"

    cleared = client.patch(
        f"/api/v1/counterparties/{catalog['customer'].id}", json={"manager_id": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["manager_id"] is None


def test_managers_list_for_any_role(client: TestClient, login) -> None:
    login("sales")
    response = client.get("/api/v1/users/managers")
    assert response.status_code == 200, response.text
    logins = [row["login"] for row in response.json()]
    assert logins == ["sales", "sales2", "sales3"]
