"""Загрузка выгрузок 1С: шесть типов, защита от дублей, журнал."""

from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

PRODUCT_HEADER = ("Код", "Наименование", "Базовая единица измерения")


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
        "materials",
        "raw",
        "finished",
    ]
    materials = next(row for row in kinds if row["kind"] == "materials")
    assert materials["columns"] == list(PRODUCT_HEADER)


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


def test_materials_are_loaded_as_products(client: TestClient, login) -> None:
    login("purchase")
    content = xlsx(
        PRODUCT_HEADER,
        ("ТОВ394895", "Антиоксидант Антрацин 33", "л"),
        ("ТОВ396736", 'Ароматизатор "Жидкий дым"', "л"),
        ("ТОВ394895", "Дубль кода", "л"),
    )
    result = upload(client, "materials", "Материалы.xlsx", content)
    assert result.status_code == 200, result.text
    assert result.json()["rows_created"] == 2
    assert result.json()["rows_skipped"] == 1

    products = client.get("/api/v1/products", params={"kind": "material"}).json()
    assert [row["code"] for row in products] == ["ТОВ394895", "ТОВ396736"]
    assert products[0]["unit"] == "л"
    assert products[0]["source"] == "1c"

    # Тот же код в другом файле — обновление, а не дубль.
    again = upload(
        client, "raw", "Сырьё.xlsx", xlsx(PRODUCT_HEADER, ("ТОВ394895", "Антрацин", "кг"))
    )
    assert again.json()["rows_created"] == 0
    assert again.json()["rows_updated"] == 1
    materials = client.get("/api/v1/products", params={"kind": "material"}).json()
    assert [row["code"] for row in materials] == ["ТОВ396736"]
    raw = client.get("/api/v1/products", params={"kind": "raw"}).json()
    assert raw[0]["name"] == "Антрацин"
    assert raw[0]["unit"] == "кг"


def test_broken_rows_are_reported(client: TestClient, login) -> None:
    login("sales")
    content = xlsx(
        PRODUCT_HEADER,
        ("ТОВ1", "Нормальная позиция", "шт"),
        ("", "Без кода", "шт"),
        ("ТОВ2", "", "шт"),
    )
    result = upload(client, "finished", "Готовая продукция.xlsx", content)
    body = result.json()
    assert body["rows_failed"] == 2
    assert body["rows_created"] == 1
    assert body["status"] == "partial"
    assert "пустой код" in body["message"]


def test_wrong_columns_are_rejected(client: TestClient, login) -> None:
    login("sales")
    response = upload(
        client, "materials", "Чужой.xlsx", xlsx(("Артикул", "Название"), ("1", "Тест"))
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
    upload(client, "finished", "Готовая продукция.xlsx", xlsx(PRODUCT_HEADER, ("ТОВ1", "Б", "шт")))

    journal = client.get("/api/v1/imports").json()
    assert [row["kind"] for row in journal] == ["finished", "customers"]
    assert journal[0]["kind_title"] == "Готовая продукция"
    assert journal[1]["kind_title"] == "Покупатели"
