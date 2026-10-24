"""Общие помощники тестов: поступление создаётся выгрузкой 1С, а не POST.

Эндпоинта создания поступления больше нет, поэтому тесты повторяют жизненный
путь: файл «Импортные поступления» заводит черновик, затем карточка
заполняется через ``PUT /batches/{id}``.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import Workbook

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Колонки выгрузки «Импортные поступления» — как в реальном файле 1С.
RECEIPT_HEADER = (
    "УУ",
    "Дата",
    "Номер",
    "Вид операции",
    "Сумма",
    "Валюта",
    "Контрагент",
    "Комментарий",
)


def receipt_xlsx(
    number: str, *, when: str = "13.10.2026 0:00:00", supplier: str = "Фирма"
) -> bytes:
    """Минимальная выгрузка «Импортные поступления» с одной шапкой."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(RECEIPT_HEADER))
    sheet.append(["Да", when, number, "покупка, комиссия", "1000", "USD", supplier, ""])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def create_receipt_draft(client: TestClient, number: str) -> dict[str, Any]:
    """Создать черновик поступления так, как его создаёт выгрузка 1С."""
    upload = client.post(
        "/api/v1/imports/import_receipts",
        files={"file": ("ИмпортныеПоступления.xlsx", receipt_xlsx(number), XLSX_TYPE)},
    )
    assert upload.status_code == 200, upload.text
    rows = client.get("/api/v1/batches").json()
    return next(row for row in rows if row["batch_number"] == number)


def put_batch(client: TestClient, payload: dict[str, Any], *, expect: int = 200) -> Any:
    """Заполнить черновик карточкой; ``expect`` — для сценариев с ошибкой."""
    draft = create_receipt_draft(client, str(payload["batch_number"]))
    response = client.put(f"/api/v1/batches/{draft['id']}", json=payload)
    assert response.status_code == expect, response.text
    return response.json() if expect == 200 else response
