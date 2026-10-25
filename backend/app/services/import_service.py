"""Загрузка выгрузок 1С (.xlsx).

Восемь типов данных, у каждого свой файл и свой набор колонок:

| Тип | Файл | Колонки |
|---|---|---|
| Локальные поставщики | одна колонка | Наименование |
| Импортные поставщики | одна колонка | Наименование |
| Покупатели | одна колонка | Наименование |
| Материалы | три колонки | Код, Наименование, Базовая единица измерения |
| Сырьё | три колонки | Код, Наименование, Базовая единица измерения |
| Готовая продукция | три колонки | Код, Наименование, Базовая единица измерения |
| Импортные поступления | четыре колонки | Номер, Дата, Контрагент, Комментарий |
| Позиции партии | две колонки | Номенклатура, Количество |

Дубли не создаются: номенклатура опознаётся по коду 1С, контрагенты — по
наименованию без учёта регистра и лишних пробелов, поступления — по номеру.
Повторная загрузка того же файла только обновляет найденные записи.

Два последних типа — не справочники: «Импортные поступления» создают черновики
партий (`receipt_import_service`), «Позиции партии» наполняют уже заведённый
черновик из карточки поступления (`batch_import_service`). Отдельной карточки
на странице «Загрузка данных» у позиций нет — поступление выбирается карточкой.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_IMPORT_MANAGER,
    ROLE_PURCHASE_DIRECTOR,
)
from app.models.counterparties import Counterparty, name_key
from app.models.domain import ImportSession, Product
from app.services.directory_service import DIRECTORY_WRITE_ROLES

KIND_LOCAL_SUPPLIERS = "local_suppliers"
KIND_IMPORT_SUPPLIERS = "import_suppliers"
KIND_CUSTOMERS = "customers"
KIND_MATERIALS = "materials"
KIND_RAW = "raw"
KIND_FINISHED = "finished"
KIND_IMPORT_RECEIPTS = "import_receipts"
KIND_BATCH_ITEMS = "batch_items"
KIND_SALES = "sales"

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_ROWS = 50_000
MAX_PROBLEMS = 5


@dataclass
class Outcome:
    """Итог разбора одного файла до записи в журнал."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def problem(self, message: str) -> None:
        """Запомнить причину; в журнал уходят только первые MAX_PROBLEMS."""
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append(message)


@dataclass(frozen=True)
class ImportKind:
    """Описание типа загрузки."""

    kind: str
    title: str
    entity: str  # products | counterparties | batches | batch_items
    columns: tuple[str, ...]
    product_kind: str | None = None
    role_field: str | None = None
    roles: tuple[str, ...] = DIRECTORY_WRITE_ROLES
    note: str | None = None
    # Колонки, которые читаем, только если они есть в файле.
    optional_columns: tuple[str, ...] = ()
    # listed=False: тип не показывается карточкой на «Загрузке данных» — только в журнале.
    listed: bool = True


KINDS: dict[str, ImportKind] = {
    KIND_LOCAL_SUPPLIERS: ImportKind(
        kind=KIND_LOCAL_SUPPLIERS,
        title="Локальные поставщики",
        entity="counterparties",
        columns=("Наименование",),
        role_field="is_local_supplier",
    ),
    KIND_IMPORT_SUPPLIERS: ImportKind(
        kind=KIND_IMPORT_SUPPLIERS,
        title="Импортные поставщики",
        entity="counterparties",
        columns=("Наименование",),
        role_field="is_import_supplier",
    ),
    KIND_CUSTOMERS: ImportKind(
        kind=KIND_CUSTOMERS,
        title="Покупатели",
        entity="counterparties",
        columns=("Наименование",),
        role_field="is_customer",
    ),
    KIND_MATERIALS: ImportKind(
        kind=KIND_MATERIALS,
        title="Материалы",
        entity="products",
        columns=("Код", "Наименование", "Базовая единица измерения"),
        product_kind="material",
    ),
    KIND_RAW: ImportKind(
        kind=KIND_RAW,
        title="Сырьё",
        entity="products",
        columns=("Код", "Наименование", "Базовая единица измерения"),
        product_kind="raw",
    ),
    KIND_FINISHED: ImportKind(
        kind=KIND_FINISHED,
        title="Готовая продукция",
        entity="products",
        columns=("Код", "Наименование", "Базовая единица измерения"),
        product_kind="finished",
    ),
    KIND_IMPORT_RECEIPTS: ImportKind(
        kind=KIND_IMPORT_RECEIPTS,
        title="Импортные поступления",
        entity="batches",
        columns=("Номер", "Дата", "Контрагент", "Комментарий"),
        roles=(ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER),
        note=(
            "Создаёт черновики поступлений для календаря: номер, дата, поставщик и "
            "комментарий. Позиции и платежи дозаполняются в карточке."
        ),
    ),
    KIND_BATCH_ITEMS: ImportKind(
        kind=KIND_BATCH_ITEMS,
        title="Позиции партии",
        entity="batch_items",
        columns=("Номенклатура", "Количество"),
        optional_columns=("Ед.",),
        roles=(ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER),
        note=(
            "Файл «Партия» из 1С: в поступление попадают товар и количество. "
            "Загружается из карточки поступления, а не с этой страницы."
        ),
        listed=False,
    ),
    KIND_SALES: ImportKind(
        kind=KIND_SALES,
        title="Продажи за месяц",
        entity="sales",
        # Колонки отчёта «Продажи» из 1С: файл не табличный, поэтому это подсказка.
        columns=("Контрагент", "Номенклатура", "Количество", "Сумма продажи"),
        roles=(ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR),
        note=(
            "Отчёт 1С «Продажи» за месяц — это факт продаж. Период берётся из шапки "
            "файла, возвраты идут минусом. Повторная загрузка заменяет месяц целиком, "
            "неопознанные позиции попадают в очередь сопоставления."
        ),
    ),
}


class ImportDataError(Exception):
    """Файл не подходит: не тот формат, пустой или слишком большой."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class ImportResult:
    """Итог загрузки одного файла."""

    session: ImportSession
    problems: list[str]


def _norm_header(value: Any) -> str:
    return " ".join(str(value).split()).strip().casefold() if value is not None else ""


# Канонические имена частей пакета .xlsx, которые ищет openpyxl. 1С иногда пишет
# их с большой буквы («xl/SharedStrings.xml»), и тогда файл не открывается.
CANONICAL_PARTS = {
    "[content_types].xml": "[Content_Types].xml",
    "xl/sharedstrings.xml": "xl/sharedStrings.xml",
    "xl/workbook.xml": "xl/workbook.xml",
    "xl/styles.xml": "xl/styles.xml",
}


def _repair_part_names(content: bytes) -> bytes:
    """Перепаковать .xlsx с каноническими именами частей пакета.

    Имена частей в OPC регистронезависимы, но openpyxl ищет строго по имени.
    Архив пересобирается только если правда есть что исправлять.
    """
    with zipfile.ZipFile(BytesIO(content)) as source:
        names = source.namelist()
        fixed = {
            name: CANONICAL_PARTS[name.casefold()]
            for name in names
            if name.casefold() in CANONICAL_PARTS and CANONICAL_PARTS[name.casefold()] != name
        }
        if not fixed:
            return content
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
            for name in names:
                target.writestr(fixed.get(name, name), source.read(name))
    return buffer.getvalue()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split()).strip()


def _read_rows(content: bytes, kind: ImportKind) -> list[dict[str, str]]:
    if not content:
        raise ImportDataError("Файл пустой")
    if len(content) > MAX_FILE_SIZE:
        raise ImportDataError("Файл больше 10 МБ — выгрузку нужно разделить")
    try:
        workbook = load_workbook(
            BytesIO(_repair_part_names(content)), read_only=True, data_only=True
        )
    except Exception as exc:  # noqa: BLE001 — любая ошибка чтения xlsx
        raise ImportDataError("Не удалось прочитать файл: нужен .xlsx из 1С") from exc

    try:
        sheet = workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header_raw = next(rows, None)
        if header_raw is None:
            raise ImportDataError("В файле нет строки с заголовками")
        header = [_norm_header(cell) for cell in header_raw]
        index: dict[str, int] = {}
        for column in (*kind.columns, *kind.optional_columns):
            wanted = _norm_header(column)
            optional = column in kind.optional_columns
            if wanted not in header:
                if optional:
                    continue
                raise ImportDataError(
                    f"Нет колонки «{column}». Ожидаются колонки: {', '.join(kind.columns)}"
                )
            index[column] = header.index(wanted)

        parsed: list[dict[str, str]] = []
        for row in rows:
            # Хвост листа 1С часто размечен, но пуст: такие строки пропускаем.
            if row is None or all(cell is None or str(cell).strip() == "" for cell in row):
                continue
            values = {
                column: _cell(row[position]) if position < len(row) else ""
                for column, position in index.items()
            }
            parsed.append(values)
            if len(parsed) > MAX_ROWS:
                raise ImportDataError(f"Строк больше {MAX_ROWS} — выгрузку нужно разделить")
        return parsed
    finally:
        workbook.close()


def read_rows(content: bytes, kind_code: str) -> list[dict[str, str]]:
    """Строки выгрузки по коду типа загрузки — для сервисов, которые пишут сами."""
    kind = KINDS.get(kind_code)
    if kind is None:
        raise ImportDataError(f"Неизвестный тип загрузки: {kind_code}", status_code=404)
    return _read_rows(content, kind)


def _import_products(db: Session, kind: ImportKind, rows: list[dict[str, str]]) -> Outcome:
    existing = {row.code: row for row in db.execute(select(Product)).scalars().all()}
    seen: set[str] = set()
    outcome = Outcome()

    for number, row in enumerate(rows, start=2):
        code = row["Код"]
        name = row["Наименование"]
        unit = row["Базовая единица измерения"] or "шт"
        if not code or not name:
            outcome.failed += 1
            outcome.problem(f"строка {number}: пустой код или наименование")
            continue
        if len(code) > 64 or len(name) > 255 or len(unit) > 16:
            outcome.failed += 1
            outcome.problem(f"строка {number}: слишком длинные значения")
            continue
        if code in seen:
            outcome.skipped += 1
            outcome.problem(f"строка {number}: код {code} уже встречался в файле")
            continue
        seen.add(code)

        product = existing.get(code)
        if product is None:
            product = Product(
                code=code,
                name=name,
                kind=kind.product_kind or "goods",
                unit=unit,
                source="1c",
            )
            db.add(product)
            existing[code] = product
            outcome.created += 1
        else:
            product.name = name
            product.unit = unit
            if kind.product_kind is not None:
                product.kind = kind.product_kind
            product.source = "1c"
            outcome.updated += 1
    return outcome


def _import_counterparties(db: Session, kind: ImportKind, rows: list[dict[str, str]]) -> Outcome:
    if kind.role_field is None:  # pragma: no cover — защита от неверной конфигурации
        raise ImportDataError("У типа загрузки не задан признак роли")

    existing = {row.name_key: row for row in db.execute(select(Counterparty)).scalars().all()}
    seen: set[str] = set()
    outcome = Outcome()

    for number, row in enumerate(rows, start=2):
        name = row["Наименование"]
        if not name:
            outcome.failed += 1
            outcome.problem(f"строка {number}: пустое наименование")
            continue
        if len(name) > 255:
            outcome.failed += 1
            outcome.problem(f"строка {number}: наименование длиннее 255 символов")
            continue
        key = name_key(name)
        if key in seen:
            outcome.skipped += 1
            outcome.problem(f"строка {number}: «{name}» уже встречался в файле")
            continue
        seen.add(key)

        counterparty = existing.get(key)
        if counterparty is None:
            counterparty = Counterparty(name=name, name_key=key, source="1c")
            setattr(counterparty, kind.role_field, True)
            db.add(counterparty)
            existing[key] = counterparty
            outcome.created += 1
        else:
            counterparty.name = name
            setattr(counterparty, kind.role_field, True)
            if counterparty.source != "manual":
                counterparty.source = "1c"
            outcome.updated += 1
    return outcome


def import_file(
    db: Session,
    kind_code: str,
    file_name: str,
    content: bytes,
    *,
    year: int | None = None,
    month: int | None = None,
) -> ImportResult:
    """Загружает файл выгрузки и пишет журнал. Идемпотентно."""
    kind = KINDS.get(kind_code)
    if kind is None:
        raise ImportDataError(f"Неизвестный тип загрузки: {kind_code}", status_code=404)

    if kind.entity == "sales":
        # Продажи — не табличная выгрузка: разбор и сопоставление свои.
        from app.services.sales_import_service import import_sales

        return import_sales(db, file_name, content, year=year, month=month)

    rows = _read_rows(content, kind)
    if kind.entity == "products":
        outcome = _import_products(db, kind, rows)
    elif kind.entity == "batches":
        # Локальный импорт: загрузчик поступлений сам берёт общий итог отсюда.
        from app.services.receipt_import_service import import_receipts

        outcome = import_receipts(db, rows)
    elif kind.entity == "batch_items":
        # Поступление известно только карточке — общая загрузка такие файлы не берёт.
        raise ImportDataError(
            "Позиции партии загружаются из карточки поступления, а не со страницы «Загрузка данных»"
        )
    else:
        outcome = _import_counterparties(db, kind, rows)

    if outcome.failed and not outcome.created and not outcome.updated:
        status = "failed"
    elif outcome.failed:
        status = "partial"
    else:
        status = "ok"

    session = ImportSession(
        kind=kind.kind,
        file_name=file_name,
        content_hash=hashlib.sha256(content).hexdigest(),
        status=status,
        rows_total=len(rows),
        rows_created=outcome.created,
        rows_updated=outcome.updated,
        rows_skipped=outcome.skipped,
        rows_failed=outcome.failed,
        message="; ".join(outcome.problems + outcome.notes) or None,
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError as exc:
        # Две одновременные загрузки одного номера: проигравшая получает отказ,
        # а не 500. Повторная загрузка после этого обновит/пропустит строку.
        db.rollback()
        raise ImportDataError(
            "Эту выгрузку уже сохраняет другой пользователь — повторите загрузку",
            status_code=409,
        ) from exc
    db.refresh(session)
    return ImportResult(session=session, problems=outcome.problems)


def list_sessions(db: Session, *, limit: int = 20) -> list[ImportSession]:
    statement = select(ImportSession).order_by(ImportSession.created_at.desc()).limit(limit)
    return list(db.execute(statement).scalars().all())
