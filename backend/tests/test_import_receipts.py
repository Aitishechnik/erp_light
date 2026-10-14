"""Черновики импортных поступлений: выгрузка 1С → партии без позиций.

Из файла берём только номер, дату, поставщика и комментарий; суммы, валюта и
служебные колонки 1С игнорируются.
"""

from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty
from app.models.domain import Batch

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Колонки как в реальной выгрузке: лишние 1С отдаёт, но мы их не читаем.
HEADER = ("УУ", "Дата", "Номер", "Вид операции", "Сумма", "Валюта", "Контрагент", "Комментарий")


def row(
    number: str,
    when: str = "13.10.2026 0:00:00",
    supplier: str = "Фирма",
    comment: str = "",
    amount: str = "1000",
) -> tuple[object, ...]:
    """Строка выгрузки в порядке колонок 1С."""
    return ("Да", when, number, "покупка, комиссия", amount, "USD", supplier, comment)


def xlsx(*rows: tuple[object, ...]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for values in rows:
        sheet.append(list(values))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def upload(client: TestClient, *rows: tuple[object, ...], name: str = "ИмпортныеПоступления.xlsx"):
    return client.post(
        "/api/v1/imports/import_receipts",
        files={"file": (name, xlsx(HEADER, *rows), XLSX_TYPE)},
    )


def batches(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/api/v1/batches")
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()
    return rows


def test_import_manager_creates_drafts(client: TestClient, db_session: Session) -> None:
    """Черновик: шапка заполнена, позиций нет, себестоимость нулевая."""
    db_session.add(
        Counterparty(
            name="AZHAZELNUT LLC",
            name_key="azhazelnut llc",
            is_import_supplier=True,
            source="1c",
        )
    )
    db_session.commit()

    result = upload(
        client,
        row(
            "ИТ-00000388",
            "06.10.2026 11:14:21",
            "AZHAZELNUT LLC (Азербайджан)",
            "Фундук 145600 + сбор 32980 + 550 свх +6%",
            amount="189785",
        ),
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["rows_total"] == 1
    assert body["rows_created"] == 1
    assert body["status"] == "ok"

    rows = batches(client)
    assert len(rows) == 1
    draft = rows[0]
    assert draft["batch_number"] == "ИТ-00000388"
    assert draft["batch_date"] == "2026-10-06"
    assert draft["source"] == "1c"
    # Импорт идёт в валюте: у черновика по умолчанию USD, курс не запрашиваем.
    assert draft["currency"] == "USD"
    # Страна в скобках поиску не мешает: поставщик взят из справочника, а не создан.
    assert draft["supplier"] == "AZHAZELNUT LLC"
    assert draft["comment"] == "Фундук 145600 + сбор 32980 + 550 свх +6%"
    # Сумма и валюта из файла в расчёт не идут.
    assert draft["items"] == []
    assert draft["finance"]["final_cost_rub"] == "0.00"

    # В остатки черновик не попадает: позиций нет.
    assert client.get("/api/v1/stock").json() == []


def test_unknown_supplier_is_created_as_import(client: TestClient) -> None:
    result = upload(client, row("ИТ-1", supplier="НОВЫЙ ПОСТАВЩИК (Китай)", comment="Грецкий орех"))
    assert result.json()["rows_created"] == 1
    assert "заведено новых поставщиков: 1" in (result.json()["message"] or "")

    rows = client.get("/api/v1/counterparties?role=import_supplier").json()
    assert len(rows) == 1
    assert rows[0]["name"] == "НОВЫЙ ПОСТАВЩИК (Китай)"
    assert rows[0]["is_import_supplier"] is True
    assert rows[0]["source"] == "1c"

    # Повторная загрузка: поставщик уже найден (страна в скобках не важна), дублей нет.
    again = upload(client, row("ИТ-1", supplier="НОВЫЙ ПОСТАВЩИК (Китай)", comment="Грецкий орех"))
    assert again.json()["rows_created"] == 0
    assert again.json()["rows_updated"] == 1
    assert again.json()["message"] is None
    assert len(client.get("/api/v1/counterparties").json()) == 1


def test_repeat_upload_updates_draft(client: TestClient) -> None:
    first = upload(client, row("ИТ-7", "13.10.2026 0:00:00", comment="старый"))
    assert first.json()["rows_created"] == 1

    second = upload(client, row("ИТ-7", "18.10.2026 12:00:00", comment="новый"))
    assert second.json()["rows_created"] == 0
    assert second.json()["rows_updated"] == 1

    rows = batches(client)
    assert len(rows) == 1  # дубля нет
    assert rows[0]["batch_date"] == "2026-10-18"
    assert rows[0]["comment"] == "новый"
    assert rows[0]["currency"] == "USD"


def test_filled_receipt_is_not_touched(client: TestClient, login) -> None:
    """Номер занят заполненным поступлением — строку пропускаем и говорим об этом."""
    login("purchase")
    created = client.post(
        "/api/v1/batches",
        json={
            "batch_number": "ИТ-5",
            "batch_date": "2026-10-08",
            "currency": "RUB",
            "items": [{"product_code": "ТОВ1", "quantity": "5", "unit_price_currency": "100"}],
        },
    )
    assert created.status_code == 201, created.text

    login("import")
    result = upload(client, row("ИТ-5", "08.10.2026 0:00:00", comment="из 1С"))
    body = result.json()
    assert body["rows_created"] == 0
    assert body["rows_updated"] == 0
    assert body["rows_skipped"] == 1
    assert "уже заполнено" in (body["message"] or "")

    rows = batches(client)
    assert len(rows) == 1
    assert rows[0]["comment"] is None
    assert len(rows[0]["items"]) == 1


def test_draft_is_filled_and_then_skipped_by_reupload(client: TestClient) -> None:
    """Дозаполнили черновик позициями — повторная загрузка его больше не трогает."""
    upload(client, row("ИТ-9", comment="черновик"))
    draft = batches(client)[0]

    filled = client.put(
        f"/api/v1/batches/{draft['id']}",
        json={
            "batch_number": "ИТ-9",
            "batch_date": "2026-10-13",
            "currency": "RUB",
            "comment": "заполнено",
            "items": [{"product_code": "ТОВ1", "quantity": "2", "unit_price_currency": "100"}],
        },
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["items"][0]["product_code"] == "ТОВ1"

    again = upload(client, row("ИТ-9", comment="черновик"))
    assert again.json()["rows_skipped"] == 1
    assert again.json()["rows_updated"] == 0
    assert batches(client)[0]["comment"] == "заполнено"


def test_draft_can_be_saved_without_items_but_manual_receipt_cannot(
    client: TestClient, login
) -> None:
    # Новое поступление руками без позиций — отказ.
    empty = client.post(
        "/api/v1/batches",
        json={"batch_number": "Р-1", "batch_date": "2026-10-08", "currency": "RUB", "items": []},
    )
    assert empty.status_code == 400
    assert "хотя бы одну строку" in empty.json()["detail"]

    # Черновик из 1С (USD) можно поправить без позиций и без курса.
    upload(client, row("ИТ-11", comment="было"))
    draft = batches(client)[0]
    fixed = client.put(
        f"/api/v1/batches/{draft['id']}",
        json={
            "batch_number": "ИТ-11",
            "batch_date": "2026-10-14",
            "currency": "USD",
            "auto_rate": False,
            "comment": "стало",
            "items": [],
        },
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["comment"] == "стало"
    assert fixed.json()["batch_date"] == "2026-10-14"
    assert fixed.json()["currency"] == "USD"
    assert fixed.json()["finance"]["final_cost_rub"] == "0.00"

    # Заполненное поступление очистить нельзя.
    login("purchase")
    created = client.post(
        "/api/v1/batches",
        json={
            "batch_number": "Р-2",
            "batch_date": "2026-10-08",
            "currency": "RUB",
            "items": [{"product_code": "ТОВ2", "quantity": "1", "unit_price_currency": "10"}],
        },
    )
    batch_id = created.json()["id"]
    cleared = client.put(
        f"/api/v1/batches/{batch_id}",
        json={"batch_number": "Р-2", "batch_date": "2026-10-08", "currency": "RUB", "items": []},
    )
    assert cleared.status_code == 400


def test_broken_rows_are_reported(client: TestClient) -> None:
    result = upload(
        client,
        row("ИТ-20", comment="ок"),
        row("", comment="без номера"),
        row("ИТ-21", "не дата", comment="плохая дата"),
        row("ИТ-20", "14.10.2026 0:00:00", comment="дубль в файле"),
    )
    body = result.json()
    assert body["rows_total"] == 4
    assert body["rows_created"] == 1
    assert body["rows_failed"] == 2
    assert body["rows_skipped"] == 1
    assert body["status"] == "partial"
    assert "пустой номер" in body["message"]
    assert "не разобрана дата" in body["message"]


def test_receipts_file_without_needed_columns_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/imports/import_receipts",
        files={
            "file": (
                "Чужой.xlsx",
                xlsx(("Номер", "Дата"), ("ИТ-1", "13.10.2026")),
                XLSX_TYPE,
            )
        },
    )
    assert response.status_code == 400
    assert "Нет колонки «Контрагент»" in response.json()["detail"]


def test_roles_split_directory_and_receipts(client: TestClient, login) -> None:
    # Менеджер по продажам грузит справочники, но не импортные поступления.
    login("sales")
    allowed = client.post(
        "/api/v1/imports/customers",
        files={"file": ("Покупатели.xlsx", xlsx(("Наименование",), ("А",)), XLSX_TYPE)},
    )
    assert allowed.status_code == 200, allowed.text
    assert upload(client, row("ИТ-1")).status_code == 403

    # Импортный менеджер — наоборот: поступления можно, справочники нет.
    login("import")
    assert upload(client, row("ИТ-2")).status_code == 200
    denied = client.post(
        "/api/v1/imports/customers",
        files={"file": ("Покупатели.xlsx", xlsx(("Наименование",), ("Б",)), XLSX_TYPE)},
    )
    assert denied.status_code == 403


def test_journal_remembers_receipts_kind(client: TestClient) -> None:
    upload(client, row("ИТ-30"))
    journal = client.get("/api/v1/imports").json()
    assert journal[0]["kind"] == "import_receipts"
    assert journal[0]["kind_title"] == "Импортные поступления"
    assert journal[0]["rows_created"] == 1


def test_drafts_are_kept_in_database_with_source_1c(
    client: TestClient, db_session: Session
) -> None:
    upload(client, row("ИТ-40"))
    stored = db_session.execute(select(Batch)).scalars().one()
    assert stored.currency == "USD"
    assert stored.source == "1c"
    assert stored.batch_type == "purchase"
    assert stored.supplier == "Фирма"
