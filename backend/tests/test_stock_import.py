"""Загрузка отчёта «Товары на складах»: строки с кодом, серии и чужие позиции."""

from datetime import date
from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Product, StockBalance

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADER = (
    ("", "Товары на складах"),
    ("", "Период: 28 октября 2026 г."),
    (
        "",
        "Показатели: Количество (в базовых единицах)(Начальный остаток, Приход, Расход, "
        "Конечный остаток);",
    ),
    ("", "Группировки строк: Номенклатура (Элементы); Серия номенклатуры (Элементы);"),
    ("",),
    ("", "Номенклатура, Базовая единица измерения", "Код", "Количество (в базовых единицах)"),
    ("", "Серия номенклатуры", "", "Начальный остаток", "Приход", "Расход", "Конечный остаток"),
)


def xlsx(*rows: tuple[object, ...]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in (*HEADER, *rows):
        sheet.append(list(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def upload(client: TestClient, content: bytes, name: str = "Остатки281026.xlsx"):
    return client.post("/api/v1/imports/stock", files={"file": (name, content, XLSX_TYPE)})


def test_report_rows_with_code_only(
    client: TestClient, catalog: dict[str, Any], db_session: Session
) -> None:
    """Серии и документы движения идут без кода и в остатки не попадают."""
    content = xlsx(
        ("", "Арахис, вес, кг", "RAW-1", 8, 25, 3, 30),
        ("", " 10511010/110926/5156156, БРАЗИЛИЯ", "", 20, 0, 0, 20),
        ("", "", "", 10, 0, 0, 10),
        ("", "Кокос, вес, кг", "RAW-2", 0, 0, 5, 5),
        ("", "Приправа, вес, кг", "ТОВ397610", 3.5, 0, 0, 3.5),
    )
    response = upload(client, content)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "stock"
    assert body["kind_title"] == "Остатки на складе"
    # Три строки с кодом: две позиции справочника и одна чужая.
    assert body["rows_total"] == 3
    assert body["rows_created"] == 2
    assert body["rows_skipped"] == 1
    assert "ТОВ397610" in body["message"]

    rows = {row.product_id: row for row in db_session.execute(select(StockBalance)).scalars().all()}
    peanut = rows[catalog["raw"].id]
    assert peanut.balance_date == date(2026, 10, 28)
    assert peanut.opening == 8
    assert peanut.income == 25
    assert peanut.outcome == 3
    assert peanut.closing == 30
    assert rows[catalog["raw2"].id].closing == 5
    # Позиция вне справочника не создаётся.
    assert (
        db_session.execute(select(Product).where(Product.code == "ТОВ397610")).scalar_one_or_none()
        is None
    )


def test_repeat_upload_updates_numbers(
    client: TestClient, catalog: dict[str, Any], db_session: Session
) -> None:
    upload(client, xlsx(("", "Арахис, вес, кг", "RAW-1", 8, 25, 3, 30)))
    second = upload(client, xlsx(("", "Арахис, вес, кг", "RAW-1", 30, 0, 7, 23)))
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["rows_created"] == 0
    assert body["rows_updated"] == 1

    rows = db_session.execute(select(StockBalance)).scalars().all()
    assert len(rows) == 1
    assert rows[0].opening == 30
    assert rows[0].outcome == 7
    assert rows[0].closing == 23


def test_file_without_codes_is_rejected(client: TestClient) -> None:
    content = xlsx(("", "Серия без кода", "", 1, 2, 3, 4))
    response = upload(client, content)
    assert response.status_code == 400, response.text
    assert "нет строк с кодом" in response.json()["detail"]


def test_foreign_file_is_rejected(client: TestClient) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Клиент", "Товар", "Количество"])
    sheet.append(["ООО Ромашка", "Смесь", 10])
    buffer = BytesIO()
    workbook.save(buffer)
    response = upload(client, buffer.getvalue())
    assert response.status_code == 400, response.text
    assert "Товары на складах" in response.json()["detail"]
