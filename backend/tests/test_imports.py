"""Загрузка выгрузок 1С: типы, защита от дублей, обновление изменившегося, журнал."""

import uuid
from datetime import date
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models.domain import Batch, BatchItem

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

NOMENCLATURE_HEADER = (
    "Код",
    "Наименование",
    "Полное наименование",
    "Базовая единица измерения",
    "Вид номенклатуры",
)


def xlsx(*rows: tuple[object, ...]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(list(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def upload(client: TestClient, kind: str, name: str, content: bytes):
    return client.post(f"/api/v1/imports/{kind}", files={"file": (name, content, XLSX_TYPE)})


def test_kinds_are_listed(client: TestClient) -> None:
    kinds = client.get("/api/v1/imports/kinds").json()
    assert [row["kind"] for row in kinds] == [
        "local_suppliers",
        "import_suppliers",
        "customers",
        "nomenclature",
        "import_receipts",
        "sales",
        "stock",
    ]
    nomenclature = next(row for row in kinds if row["kind"] == "nomenclature")
    assert nomenclature["title"] == "Номенклатура"
    assert nomenclature["columns"] == [
        "Код",
        "Полное наименование",
        "Базовая единица измерения",
        "Вид номенклатуры",
    ]
    receipts = next(row for row in kinds if row["kind"] == "import_receipts")
    assert receipts["title"] == "Импортные поступления"
    assert receipts["columns"] == ["Номер", "Дата", "Контрагент", "Комментарий"]
    assert receipts["roles"] == ["purchase_director", "import_manager"]
    sales = next(row for row in kinds if row["kind"] == "sales")
    assert sales["title"] == "Продажи за месяц"
    assert sales["roles"] == ["commercial_director", "executive_director"]
    stock = next(row for row in kinds if row["kind"] == "stock")
    assert stock["title"] == "Остатки на складе"
    assert stock["roles"] == ["purchase_director", "import_manager"]
    assert stock["columns"] == [
        "Номенклатура",
        "Код",
        "Начальный остаток",
        "Приход",
        "Расход",
        "Конечный остаток",
    ]


def test_customers_are_loaded_without_duplicates(client: TestClient, login) -> None:
    login("sales")
    content = xlsx(
        ("Наименование",),
        ("Азбука Вкуса",),
        ("БИЛЛА",),
        ("  билла ",),  # дубль внутри файла: регистр и пробелы не важны
        ("Комус",),
    )
    first = upload(client, "customers", "Покупатели.xlsx", content)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["rows_total"] == 4
    assert body["rows_created"] == 3
    assert body["rows_skipped"] == 1
    assert body["rows_failed"] == 0
    assert body["status"] == "ok"

    # Повторная загрузка того же файла ничего не создаёт.
    second = upload(client, "customers", "Покупатели.xlsx", content)
    assert second.json()["rows_created"] == 0
    assert second.json()["rows_updated"] == 3

    customers = client.get("/api/v1/counterparties?role=customer").json()
    assert [row["name"] for row in customers] == ["Азбука Вкуса", "БИЛЛА", "Комус"]
    assert all(row["source"] == "1c" for row in customers)


def test_same_company_as_supplier_and_customer_is_one_record(client: TestClient, login) -> None:
    login("sales")
    assert (
        upload(
            client,
            "local_suppliers",
            "Локальные поставщики.xlsx",
            xlsx(("Наименование",), ("Комус",)),
        ).json()["rows_created"]
        == 1
    )
    result = upload(client, "customers", "Покупатели.xlsx", xlsx(("Наименование",), ("Комус",)))
    assert result.json()["rows_created"] == 0
    assert result.json()["rows_updated"] == 1

    rows = client.get("/api/v1/counterparties").json()
    assert len(rows) == 1
    assert rows[0]["is_local_supplier"] is True
    assert rows[0]["is_customer"] is True


def test_nomenclature_split_into_kinds_by_column(client: TestClient, login) -> None:
    """Один файл: вид берётся из колонки, а не из имени файла."""
    login("purchase")
    content = xlsx(
        NOMENCLATURE_HEADER,
        (
            "ТОВ1",
            "Короткое имя",
            "PAMU Арахис в кокосовой глазури 1кг",
            "шт",
            "Готовая продукция (43)",
        ),
        ("ТОВ2", "Антрацин 33", "", "кг", "Сырье (10.01)"),
        (
            "ТОВ3",
            "Гофрокороб",
            "Гофрокороб 250*160*100",
            "шт",
            "Тара и тарные материалы (10.04)",
        ),
        ("ТОВ1", "Дубль кода", "Дубль", "шт", "Готовая продукция (43)"),
    )
    result = upload(client, "nomenclature", "Номенклатура.xlsx", content)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["rows_total"] == 4
    assert body["rows_created"] == 3
    assert body["rows_skipped"] == 1
    assert body["rows_failed"] == 0

    finished = client.get("/api/v1/products", params={"kind": "finished"}).json()
    assert [row["name"] for row in finished] == ["PAMU Арахис в кокосовой глазури 1кг"]
    raw = client.get("/api/v1/products", params={"kind": "raw"}).json()
    # Полного наименования нет — имя взяли из обычного, строку не пропустили.
    assert raw[0]["name"] == "Антрацин 33"
    assert raw[0]["unit"] == "кг"
    material = client.get("/api/v1/products", params={"kind": "material"}).json()
    assert material[0]["name"] == "Гофрокороб 250*160*100"
    assert all(row["source"] == "1c" for row in finished + raw + material)


def test_repeat_load_updates_changed_fields(client: TestClient, login) -> None:
    """Тот же код не дублируется, а изменившиеся поля перезаписываются."""
    login("purchase")
    first = xlsx(NOMENCLATURE_HEADER, ("ТОВ1", "Старое", "Старое имя", "кг", "Сырье (10.01)"))
    assert upload(client, "nomenclature", "Номенклатура.xlsx", first).json()["rows_created"] == 1

    second = xlsx(
        NOMENCLATURE_HEADER,
        ("ТОВ1", "Новое", "Новое имя", "шт", "Тара и тарные материалы (10.04)"),
    )
    changed = upload(client, "nomenclature", "Номенклатура.xlsx", second).json()
    assert changed["rows_created"] == 0
    assert changed["rows_updated"] == 1
    assert "Изменено 1 поз." in changed["message"]
    assert "вид 1" in changed["message"]

    rows = client.get("/api/v1/products").json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Новое имя"
    assert rows[0]["unit"] == "шт"
    assert rows[0]["kind"] == "material"

    # Тот же файл ещё раз — записей не прибавилось и менять нечего.
    again = upload(client, "nomenclature", "Номенклатура.xlsx", second).json()
    assert again["rows_created"] == 0
    assert again["rows_updated"] == 1
    assert "не изменились" in again["message"]
    assert len(client.get("/api/v1/products").json()) == 1


def test_missing_unit_is_filled_with_piece(client: TestClient, login) -> None:
    login("purchase")
    content = xlsx(NOMENCLATURE_HEADER, ("ТОВ9", "Финики", "", "", "Готовая продукция (43)"))
    body = upload(client, "nomenclature", "Номенклатура.xlsx", content).json()
    assert body["rows_created"] == 1
    assert "не заполнена единица" in body["message"]
    product = client.get("/api/v1/products").json()[0]
    assert product["unit"] == "шт"


def test_unknown_kind_value_is_reported(client: TestClient, login) -> None:
    login("purchase")
    content = xlsx(
        NOMENCLATURE_HEADER,
        ("ТОВ1", "Запайщик", "Запайщик конвейерный", "шт", "Оборудование"),
        ("ТОВ2", "Сахар", "Сахар песок", "кг", "Сырье (10.01)"),
    )
    body = upload(client, "nomenclature", "Номенклатура.xlsx", content).json()
    assert body["rows_failed"] == 1
    assert body["rows_created"] == 1
    assert body["status"] == "partial"
    assert "неизвестный вид номенклатуры" in body["message"]


def test_absent_positions_are_deleted(client: TestClient, login) -> None:
    """Файл — полный справочник: позиции, которых в нём нет, удаляются."""
    login("purchase")
    both = xlsx(
        NOMENCLATURE_HEADER,
        ("ТОВ1", "Остаётся", "Остаётся", "шт", "Готовая продукция (43)"),
        ("ТОВ2", "Мусор", "Мусор", "шт", "Готовая продукция (43)"),
    )
    assert upload(client, "nomenclature", "Номенклатура.xlsx", both).json()["rows_created"] == 2

    only_first = xlsx(
        NOMENCLATURE_HEADER,
        ("ТОВ1", "Остаётся", "Остаётся", "шт", "Готовая продукция (43)"),
    )
    body = upload(client, "nomenclature", "Номенклатура.xlsx", only_first).json()
    assert body["rows_created"] == 0
    assert body["rows_updated"] == 1
    assert "Удалено 1 поз." in body["message"]

    products = client.get("/api/v1/products").json()
    assert [row["code"] for row in products] == ["ТОВ1"]


def test_linked_positions_are_not_deleted(client: TestClient, login, db_session: Session) -> None:
    """Позицию, на которую ссылается партия, не удаляем — иначе поедет себестоимость."""
    login("purchase")
    content = xlsx(NOMENCLATURE_HEADER, ("ТОВ1", "В партии", "В партии", "кг", "Сырье (10.01)"))
    upload(client, "nomenclature", "Номенклатура.xlsx", content)
    product_id = client.get("/api/v1/products").json()[0]["id"]

    batch = Batch(batch_number="B-1", batch_date=date(2026, 10, 1))
    db_session.add(batch)
    db_session.flush()
    db_session.add(BatchItem(batch_id=batch.id, product_id=uuid.UUID(product_id)))
    db_session.commit()

    replacement = xlsx(NOMENCLATURE_HEADER, ("ТОВ2", "Новая", "Новая", "кг", "Сырье (10.01)"))
    body = upload(client, "nomenclature", "Номенклатура.xlsx", replacement).json()
    assert "Оставлено 1" in body["message"]

    products = client.get("/api/v1/products").json()
    assert [row["code"] for row in products] == ["ТОВ1", "ТОВ2"]


def test_broken_rows_are_reported(client: TestClient, login) -> None:
    login("sales")
    content = xlsx(
        NOMENCLATURE_HEADER,
        ("ТОВ1", "Нормальная позиция", "Нормальная позиция", "шт", "Готовая продукция (43)"),
        ("", "Без кода", "Без кода", "шт", "Готовая продукция (43)"),
        ("ТОВ2", "", "", "шт", "Готовая продукция (43)"),
    )
    result = upload(client, "nomenclature", "Номенклатура.xlsx", content)
    body = result.json()
    assert body["rows_failed"] == 2
    assert body["rows_created"] == 1
    assert body["status"] == "partial"
    assert "пустой код" in body["message"]


def test_wrong_columns_are_rejected(client: TestClient, login) -> None:
    login("sales")
    response = upload(
        client, "nomenclature", "Чужой.xlsx", xlsx(("Артикул", "Название"), ("1", "Тест"))
    )
    assert response.status_code == 400
    assert "Нет колонки" in response.json()["detail"]


def test_not_xlsx_is_rejected(client: TestClient, login) -> None:
    login("sales")
    response = upload(client, "customers", "мусор.xlsx", "это не таблица".encode())
    assert response.status_code == 400
    assert "Не удалось прочитать" in response.json()["detail"]


def test_unknown_kind_is_rejected(client: TestClient, login) -> None:
    login("sales")
    response = upload(client, "unknown", "файл.xlsx", xlsx(("Наименование",), ("Тест",)))
    assert response.status_code == 404


def test_import_requires_write_role(client: TestClient, login) -> None:
    login("import")
    response = upload(client, "customers", "Покупатели.xlsx", xlsx(("Наименование",), ("Тест",)))
    assert response.status_code == 403


def test_journal_keeps_both_uploads(client: TestClient, login) -> None:
    login("sales")
    upload(client, "customers", "Покупатели.xlsx", xlsx(("Наименование",), ("А",)))
    upload(
        client,
        "nomenclature",
        "Номенклатура.xlsx",
        xlsx(NOMENCLATURE_HEADER, ("ТОВ1", "Б", "Б", "шт", "Готовая продукция (43)")),
    )

    journal = client.get("/api/v1/imports").json()
    assert [row["kind"] for row in journal] == ["nomenclature", "customers"]
    assert journal[0]["kind_title"] == "Номенклатура"
    assert journal[1]["kind_title"] == "Покупатели"
