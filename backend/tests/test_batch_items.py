"""Позиции партии из файла «Партия» (1С) в карточку поступления.

Из выгрузки берём только номенклатуру и количество; цены, суммы, курс и
себестоимость — отдельная задача. Файл принимается целиком или не принимается:
плохая строка (нет кода, код не найден в справочнике, другая единица,
непонятное количество) отменяет всю загрузку. В форме 1С с 2026-11 номенклатура
опознаётся по колонке «Код»; файл прежней формы без неё — по наименованию.
"""

from io import BytesIO
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models.domain import Product
from tests.helpers import put_batch

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Колонки как в реальной выгрузке «Партия»: лишние 1С отдаёт, но мы их не читаем.
# Колонки новой формы 1С: третья — «Код», по ней и ищем номенклатуру.
HEADER = (
    "№",
    "Количество",
    "Код",
    "Номенклатура",
    "Способ отражения расходов",
    "Серия",
    "Ед.",
    "К.",
    "Цена",
    "Сумма",
    "% НДС",
    "Сумма НДС",
    "Всего",
    "Страна происхождения",
    "Заказ поставщику",
    "Заказ",
    "Склад",
    "Счет передачи (БУ)",
)

# Прежняя форма «Партии»: колонки «Код» нет, третья колонка без заголовка.
OLD_HEADER = (
    "№",
    "Количество",
    "",
    "Номенклатура",
    "Способ отражения расходов",
    "Серия",
    "Ед.",
    "К.",
    "Цена",
    "Сумма",
    "% НДС",
    "Сумма НДС",
    "Всего",
    "Страна происхождения",
    "Заказ поставщику",
    "Заказ",
    "Склад",
    "Счет передачи (БУ)",
)

RECEIPTS_HEADER = ("Дата", "Номер", "Контрагент", "Комментарий")


def part_row(
    number: int,
    name: str,
    quantity: str,
    *,
    code: str = "ТОВ1",
    unit: str = "кг",
    price: str = "6.73",
    total: str = "134600",
) -> tuple[object, ...]:
    """Строка новой формы выгрузки в порядке колонок 1С."""
    return (
        number,
        quantity,
        code,
        name,
        "",
        f"{name} Китай 10кг",
        unit,
        1,
        price,
        total,
        "22%",
        "24272.13",
        total,
        "КИТАЙ",
        "",
        "",
        "Склад СТУПИНО NEW",
        "",
    )


def old_part_row(number: int, name: str, quantity: str, *, unit: str = "кг") -> tuple[object, ...]:
    """Строка прежней формы: колонки «Код» нет, вместо кода — пустая ячейка."""
    row = list(part_row(number, name, quantity, unit=unit))
    row[2] = ""
    return tuple(row)


def xlsx(*rows: tuple[object, ...], header: tuple[str, ...] = HEADER) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(header))
    for values in rows:
        sheet.append(list(values))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def break_service_part_names(content: bytes) -> bytes:
    """1С пишет служебный файл как «xl/SharedStrings.xml» — так файл не открывается."""
    source = BytesIO(content)
    target = BytesIO()
    with ZipFile(source) as archive, ZipFile(target, "w", ZIP_DEFLATED) as fixed:
        for info in archive.infolist():
            name = info.filename
            if name.casefold() == "xl/sharedstrings.xml":
                name = "xl/SharedStrings.xml"
            fixed.writestr(name, archive.read(info.filename))
    return target.getvalue()


def upload_items(
    client: TestClient,
    batch_id: str,
    *rows: tuple[object, ...],
    name: str = "Партия.xlsx",
    header: tuple[str, ...] = HEADER,
) -> Any:
    return client.post(
        f"/api/v1/batches/{batch_id}/import-items",
        files={"file": (name, xlsx(*rows, header=header), XLSX_TYPE)},
    )


def create_draft(client: TestClient, number: str = "ИТ-1", supplier: str = "Фирма") -> str:
    """Черновик поступления так, как его создаёт выгрузка «Импортные поступления»."""
    created = client.post(
        "/api/v1/imports/import_receipts",
        files={
            "file": (
                "ИмпортныеПоступления.xlsx",
                xlsx(
                    ("13.10.2026 0:00:00", number, supplier, "Грецкий орех"),
                    header=RECEIPTS_HEADER,
                ),
                XLSX_TYPE,
            )
        },
    )
    assert created.status_code == 200, created.text
    rows: list[dict[str, Any]] = client.get("/api/v1/batches").json()
    return str(next(row["id"] for row in rows if row["batch_number"] == number))


def add_products(db_session: Session, *products: Product) -> None:
    for product in products:
        db_session.add(product)
    db_session.commit()


def raw(code: str, name: str, unit: str = "кг") -> Product:
    return Product(code=code, name=name, kind="raw", unit=unit, source="1c")


def test_draft_gets_items_from_file(client: TestClient, db_session: Session) -> None:
    """Черновик наполняется: товар и количество, без сумм и себестоимости."""
    add_products(db_session, raw("ТОВ395561", "Грецкий орех сушеный, вес"))
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        part_row(1, "Грецкий орех сушеный, вес", "20000", code="ТОВ395561"),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["report"]["kind"] == "batch_items"
    assert body["report"]["kind_title"] == "Позиции партии"
    assert body["report"]["status"] == "ok"
    assert body["report"]["rows_total"] == 1
    assert body["report"]["rows_created"] == 1
    assert "загружено строк 1" in body["report"]["message"]

    batch = body["batch"]
    assert batch["source"] == "1c"
    assert batch["currency"] == "USD"
    assert len(batch["items"]) == 1
    item = batch["items"][0]
    assert item["product_code"] == "ТОВ395561"
    assert item["product_name"] == "Грецкий орех сушеный, вес"
    assert item["quantity"] == "20000.000"
    # Финансовая часть не трогается: цена строки нулевая, себестоимость нулевая.
    assert item["unit_price_currency"] == "0.0000"
    assert item["invoice_currency"] == "0.00"
    assert batch["finance"]["invoice_total_currency"] == "0.00"
    assert batch["finance"]["final_cost_rub"] == "0.00"

    # В остатки партия без сумм не попадает.
    assert client.get("/api/v1/stock").json() == []

    # Загрузка попала в журнал с названием типа.
    journal = client.get("/api/v1/imports").json()
    assert journal[0]["kind"] == "batch_items"
    assert journal[0]["kind_title"] == "Позиции партии"
    assert journal[0]["file_name"] == "Партия.xlsx"


def test_file_with_capital_letters_inside_is_read(client: TestClient, db_session: Session) -> None:
    """Служебный файл «xl/SharedStrings.xml» (так пишет 1С) не мешает загрузке."""
    add_products(db_session, raw("ТОВ1", "Арахис в глазури"))
    batch_id = create_draft(client)

    response = client.post(
        f"/api/v1/batches/{batch_id}/import-items",
        files={
            "file": (
                "Партия.xlsx",
                break_service_part_names(xlsx(part_row(1, "Арахис в глазури", "20 000"))),
                XLSX_TYPE,
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["batch"]["items"][0]["quantity"] == "20000.000"


def test_item_is_found_by_code_when_name_changed(client: TestClient, db_session: Session) -> None:
    """Название в 1С переименовали — позиция всё равно находится по коду."""
    add_products(db_session, raw("ТОВ395561", "Грецкий орех сушеный, вес"))
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        part_row(1, "Грецкий орех сушеный (новое название 1С)", "20000", code="ТОВ395561"),
    )
    assert response.status_code == 200, response.text
    item = response.json()["batch"]["items"][0]
    assert item["product_code"] == "ТОВ395561"
    # В карточке остаётся название из нашего справочника.
    assert item["product_name"] == "Грецкий орех сушеный, вес"


def test_code_with_trailing_spaces_and_other_case_is_found(
    client: TestClient, db_session: Session
) -> None:
    """1С отдаёт код с хвостовыми пробелами («ТОВ396657  ») — это тот же код."""
    add_products(db_session, raw("ТОВ396657", "Хурма сушеная, чипсы, вес"))
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        part_row(1, "Хурма сушеная, чипсы, вес", "5000", code="тов396657   "),
    )
    assert response.status_code == 200, response.text
    assert response.json()["batch"]["items"][0]["product_code"] == "ТОВ396657"


def test_empty_code_blocks_file(client: TestClient, db_session: Session) -> None:
    """В новой форме без кода строку не опознать — файл не принимается целиком."""
    add_products(db_session, raw("ТОВ1", "Арахис в глазури"))
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        part_row(1, "Арахис в глазури", "10"),
        part_row(2, "Чернослив, вес", "5", code=""),
    )
    assert response.status_code == 400
    assert "строка 3: пустой код 1С у «Чернослив, вес»" in response.json()["detail"]
    assert client.get(f"/api/v1/batches/{batch_id}").json()["items"] == []


def test_old_form_without_code_loads_by_name(client: TestClient, db_session: Session) -> None:
    """Файл прежней формы (без колонки «Код») грузится по наименованию, как раньше."""
    add_products(db_session, raw("ТОВ395561", "Грецкий орех сушеный, вес"))
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        old_part_row(1, "Грецкий орех сушеный, вес", "20000"),
        header=OLD_HEADER,
    )
    assert response.status_code == 200, response.text
    item = response.json()["batch"]["items"][0]
    assert item["product_code"] == "ТОВ395561"
    assert item["quantity"] == "20000.000"


def test_unknown_nomenclature_blocks_whole_file(client: TestClient, db_session: Session) -> None:
    add_products(db_session, raw("ТОВ1", "Арахис в глазури"))
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        part_row(1, "Арахис в глазури", "10"),
        part_row(2, "Неизвестный товар", "5", code="ТОВ404"),
    )
    assert response.status_code == 400
    assert "код «ТОВ404» («Неизвестный товар») не найден" in response.json()["detail"]

    # Ничего не записалось: партия осталась черновиком.
    batch = client.get(f"/api/v1/batches/{batch_id}").json()
    assert batch["items"] == []

    # Ошибка осталась в журнале.
    journal = client.get("/api/v1/imports").json()
    assert journal[0]["kind"] == "batch_items"
    assert journal[0]["status"] == "failed"
    assert journal[0]["rows_failed"] == 1


def test_same_name_with_different_codes_is_not_ambiguous(
    client: TestClient, db_session: Session
) -> None:
    """Одноимённые позиции больше не мешают: в новой форме они различаются кодом."""
    add_products(
        db_session,
        raw("ТОВ1", "Чернослив, вес"),
        raw("ТОВ2", "Чернослив, вес"),
    )
    batch_id = create_draft(client)

    response = upload_items(client, batch_id, part_row(1, "Чернослив, вес", "10", code="ТОВ2"))
    assert response.status_code == 200, response.text
    items = response.json()["batch"]["items"]
    assert [item["product_code"] for item in items] == ["ТОВ2"]


def test_old_form_ambiguous_name_blocks_file(client: TestClient, db_session: Session) -> None:
    """Прежняя форма без кода: одноимённые позиции по-прежнему требуют уточнения."""
    add_products(
        db_session,
        raw("ТОВ1", "Чернослив, вес"),
        raw("ТОВ2", "Чернослив, вес", unit="кг"),
    )
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        old_part_row(1, "Чернослив, вес", "10"),
        header=OLD_HEADER,
    )
    assert response.status_code == 400
    assert (
        "по названию «Чернослив, вес» в справочнике несколько позиций (ТОВ1, ТОВ2)"
        in (response.json()["detail"])
    )
    assert client.get(f"/api/v1/batches/{batch_id}").json()["items"] == []


def test_other_unit_blocks_file(client: TestClient, db_session: Session) -> None:
    add_products(db_session, raw("ТОВ1", "Арахис в глазури", unit="шт"))
    batch_id = create_draft(client)

    response = upload_items(client, batch_id, part_row(1, "Арахис в глазури", "10", unit="кг"))
    assert response.status_code == 400
    assert "единица в файле «кг», а в справочнике «шт»" in response.json()["detail"]


def test_bad_quantity_blocks_file(client: TestClient, db_session: Session) -> None:
    add_products(db_session, raw("ТОВ1", "Арахис в глазури"))
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        part_row(1, "Арахис в глазури", "не число"),
        part_row(2, "Арахис в глазури", "0"),
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "не разобрано количество «не число»" in detail
    assert "количество должно быть больше нуля" in detail


def test_empty_file_is_rejected(client: TestClient) -> None:
    batch_id = create_draft(client)
    response = upload_items(client, batch_id)
    assert response.status_code == 400
    assert "нет строк с товаром" in response.json()["detail"]


def test_missing_columns_are_reported(client: TestClient) -> None:
    batch_id = create_draft(client)
    response = client.post(
        f"/api/v1/batches/{batch_id}/import-items",
        files={
            "file": (
                "Чужая.xlsx",
                xlsx((1, "Арахис"), header=("№", "Номенклатура")),
                XLSX_TYPE,
            )
        },
    )
    assert response.status_code == 400
    assert "Нет колонки «Количество»" in response.json()["detail"]


def test_unit_column_is_optional(client: TestClient, db_session: Session) -> None:
    """Без колонки «Ед.» файл тоже принимается — она нужна только для сверки."""
    add_products(db_session, raw("ТОВ1", "Арахис в глазури"))
    batch_id = create_draft(client)

    response = upload_items(
        client,
        batch_id,
        (1, "10", "Арахис в глазури"),
        header=("№", "Количество", "Номенклатура"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["batch"]["items"][0]["quantity"] == "10.000"


def test_repeat_upload_replaces_items(client: TestClient, db_session: Session) -> None:
    add_products(
        db_session,
        raw("ТОВ1", "Арахис в глазури"),
        raw("ТОВ2", "Чернослив, вес"),
        raw("ТОВ3", "Изюм темный, вес"),
    )
    batch_id = create_draft(client)

    first = upload_items(client, batch_id, part_row(1, "Арахис в глазури", "10"))
    assert first.status_code == 200, first.text

    second = upload_items(
        client,
        batch_id,
        part_row(1, "Арахис в глазури", "10", code="ТОВ1"),
        part_row(2, "Чернослив, вес", "7", code="ТОВ2"),
        part_row(3, "Изюм темный, вес", "3", code="ТОВ3"),
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["report"]["rows_created"] == 3
    assert body["report"]["rows_updated"] == 1
    assert [item["product_code"] for item in body["batch"]["items"]] == ["ТОВ1", "ТОВ2", "ТОВ3"]


def test_payments_block_replacement(client: TestClient) -> None:
    """У партии с платежами позиции не меняем: платежи считались от другого инвойса."""
    payload = {
        "batch_number": "Р-1",
        "batch_date": "2026-10-08",
        "currency": "RUB",
        "items": [{"product_code": "ТОВ1", "quantity": "5", "unit_price_currency": "100"}],
        "payments": [
            {
                "payment_date": "2026-10-08",
                "amount_currency": "100",
                "exchange_rate": "1",
            }
        ],
    }
    created = put_batch(client, payload)
    batch_id = created["id"]

    response = upload_items(client, batch_id, part_row(1, "Арахис в глазури", "10"))
    assert response.status_code == 400
    assert "уже есть платежи" in response.json()["detail"]
    assert len(client.get(f"/api/v1/batches/{batch_id}").json()["items"]) == 1


def test_unknown_batch_is_404(client: TestClient) -> None:
    response = upload_items(
        client, "00000000-0000-0000-0000-000000000000", part_row(1, "Что-то", "1")
    )
    assert response.status_code == 404


def test_only_purchase_roles_may_load_items(client: TestClient, login, db_session: Session) -> None:
    add_products(db_session, raw("ТОВ1", "Арахис в глазури"))
    batch_id = create_draft(client)

    login("sales")
    assert upload_items(client, batch_id, part_row(1, "Арахис в глазури", "1")).status_code == 403

    login("purchase")
    assert upload_items(client, batch_id, part_row(1, "Арахис в глазури", "1")).status_code == 200

    # Администратор грузит позиции партии наравне с закупщиками.
    login("executive")
    assert upload_items(client, batch_id, part_row(1, "Арахис в глазури", "2")).status_code == 200


def test_page_does_not_offer_batch_items(client: TestClient) -> None:
    """На «Загрузке данных» отдельной карточки нет, а общая загрузка такие файлы не берёт."""
    kinds = client.get("/api/v1/imports/kinds").json()
    assert "batch_items" not in [kind["kind"] for kind in kinds]

    response = client.post(
        "/api/v1/imports/batch_items",
        files={"file": ("Партия.xlsx", xlsx(part_row(1, "Арахис", "1")), XLSX_TYPE)},
    )
    assert response.status_code == 400
    assert "из карточки поступления" in response.json()["detail"]
