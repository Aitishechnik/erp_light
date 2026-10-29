"""Загрузка выгрузок 1С (.xlsx).

Типы данных, у каждого свой файл и свой набор колонок:

| Тип | Файл | Колонки |
|---|---|---|
| Локальные поставщики | одна колонка | Наименование |
| Импортные поставщики | одна колонка | Наименование |
| Покупатели | одна колонка | Наименование |
| Номенклатура | четыре колонки | Код, Полное наименование, Единица, Вид номенклатуры |
| Импортные поступления | четыре колонки | Номер, Дата, Контрагент, Комментарий |
| Позиции партии | две колонки | Номенклатура, Количество |
| Продажи за месяц | отчёт «Продажи» | Контрагент, Номенклатура, Количество, Сумма продажи |
| Остатки на складе | отчёт «Товары на складах» | Код, Начальный остаток, Приход, Расход, итог |

Дубли не создаются: номенклатура опознаётся по коду 1С, контрагенты — по
наименованию без учёта регистра и лишних пробелов, поступления — по номеру.
Повторная загрузка того же файла не создаёт дублей: найденные записи
сравниваются с файлом, и изменившиеся поля (наименование, единица, вид)
перезаписываются. В журнал попадает, сколько позиций изменилось и чем.

Номенклатура — один файл на сырьё, материалы и готовую продукцию: вид берётся
из колонки «Вид номенклатуры» (сырьё, готовая продукция, тарные материалы —
это материалы), а не из имени файла. Строки без «Полного наименования» тоже
загружаются — имя берётся из колонки «Наименование».

Два последних типа — не справочники: «Импортные поступления» создают черновики
партий (`receipt_import_service`), «Позиции партии» наполняют уже заведённый
черновик из карточки поступления (`batch_import_service`). Отдельной карточки
на странице «Загрузка данных» у позиций нет — поступление выбирается карточкой.

«Продажи» и «Остатки» — отчёты, а не таблицы: у них своя шапка, поэтому разбор
живёт в `sales_import_service` и `stock_import_service`.
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
KIND_NOMENCLATURE = "nomenclature"
KIND_IMPORT_RECEIPTS = "import_receipts"
KIND_BATCH_ITEMS = "batch_items"
KIND_SALES = "sales"
KIND_STOCK = "stock"

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
    # Вид продукции для всех строк файла. None — вид берётся из колонки kind_column.
    product_kind: str | None = None
    # Колонка с видом номенклатуры в терминах 1С (сырьё, готовая продукция, тара).
    kind_column: str | None = None
    # Откуда брать название. Полное наименование точнее, поэтому оно главное.
    name_column: str = "Наименование"
    # Запасные колонки имени: первая непустая.
    name_fallback: tuple[str, ...] = ()
    role_field: str | None = None
    roles: tuple[str, ...] = DIRECTORY_WRITE_ROLES
    note: str | None = None
    # Колонки, которые читаем, только если они есть в файле.
    optional_columns: tuple[str, ...] = ()
    # listed=False: тип не показывается карточкой на «Загрузке данных» — только в журнале.
    listed: bool = True
    # full_catalog=True: файл — полный справочник, позиции вне файла удаляются.
    full_catalog: bool = False


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
    KIND_NOMENCLATURE: ImportKind(
        kind=KIND_NOMENCLATURE,
        title="Номенклатура",
        entity="products",
        columns=(
            "Код",
            "Полное наименование",
            "Базовая единица измерения",
            "Вид номенклатуры",
        ),
        # Старое «Наименование» нужно там, где 1С не заполнила полное.
        optional_columns=("Наименование",),
        name_column="Полное наименование",
        name_fallback=("Наименование",),
        kind_column="Вид номенклатуры",
        full_catalog=True,
        note=(
            "Один файл на сырьё, материалы и готовую продукцию. Вид берётся из колонки "
            "«Вид номенклатуры»: сырьё, готовая продукция, тара и тарные материалы — это "
            "материалы. Код 1С — ключ: повторная загрузка обновляет изменившиеся позиции, "
            "а позиции, которых в файле нет, удаляет (кроме тех, на которые ссылаются "
            "планы или партии)."
        ),
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
    KIND_STOCK: ImportKind(
        kind=KIND_STOCK,
        title="Остатки на складе",
        entity="stock",
        # Отчёт «Товары на складах»: шапка и группировка, поэтому это подсказка.
        columns=(
            "Номенклатура",
            "Код",
            "Начальный остаток",
            "Приход",
            "Расход",
            "Конечный остаток",
        ),
        roles=(ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER),
        note=(
            "Отчёт 1С «Товары на складах» за день. Берутся только строки с кодом "
            "номенклатуры: серии и документы движения кода не имеют и пропускаются. "
            "Позиции, которых нет в справочнике, не создаются — попадают в итог. "
            "Повторная загрузка за ту же дату заменяет числа."
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


# «Вид номенклатуры» из 1С → вид в программе. В скобках 1С пишет счёт учёта:
# он может смениться, поэтому сравниваем только текст до скобки.
NOMENCLATURE_KINDS: dict[str, str] = {
    "готовая продукция": "finished",
    "сырье": "raw",
    "сырьё": "raw",
    "тара и тарные материалы": "material",
    "тарные материалы": "material",
    "материалы": "material",
}


def _nomenclature_kind(value: str) -> str | None:
    """Вид продукции по значению колонки «Вид номенклатуры»."""
    key = value.split("(", 1)[0].strip().casefold()
    return NOMENCLATURE_KINDS.get(key)


def _import_products(db: Session, kind: ImportKind, rows: list[dict[str, str]]) -> Outcome:
    """Создать и обновить номенклатуру. Код 1С — ключ, поэтому дублей не бывает.

    Существующая позиция сравнивается с файлом: изменившиеся наименование,
    единица и вид перезаписываются, а в журнал попадает, сколько позиций
    изменилось. Строки без полного наименования не пропускаются — имя берётся
    из запасной колонки.
    """
    existing = {row.code: row for row in db.execute(select(Product)).scalars().all()}
    seen: set[str] = set()
    outcome = Outcome()

    changed_codes: list[str] = []
    renamed = unit_changed = kind_changed = 0
    units_guessed = 0

    for number, row in enumerate(rows, start=2):
        code = row["Код"]
        name = row.get(kind.name_column, "")
        if not name:
            for column in kind.name_fallback:
                name = row.get(column, "")
                if name:
                    break
        unit = row["Базовая единица измерения"]

        product_kind = kind.product_kind
        if kind.kind_column is not None:
            kind_value = row.get(kind.kind_column, "")
            product_kind = _nomenclature_kind(kind_value)
            if product_kind is None:
                outcome.failed += 1
                outcome.problem(f"строка {number}: неизвестный вид номенклатуры «{kind_value}»")
                continue

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
            if not unit:
                units_guessed += 1
            product = Product(
                code=code,
                name=name,
                kind=product_kind or "material",
                unit=unit or "шт",
                source="1c",
            )
            db.add(product)
            existing[code] = product
            outcome.created += 1
        else:
            changed = False
            if product.name != name:
                product.name = name
                renamed += 1
                changed = True
            if unit and product.unit != unit:
                product.unit = unit
                unit_changed += 1
                changed = True
            if product_kind is not None and product.kind != product_kind:
                product.kind = product_kind
                kind_changed += 1
                changed = True
            product.source = "1c"
            if changed:
                changed_codes.append(code)
            outcome.updated += 1

    if changed_codes:
        outcome.notes.append(
            f"Изменено {len(changed_codes)} поз."
            f" (наименование {renamed}, единица {unit_changed}, вид {kind_changed}): "
            + ", ".join(changed_codes[:MAX_PROBLEMS])
            + ("…" if len(changed_codes) > MAX_PROBLEMS else "")
        )
    elif outcome.updated:
        outcome.notes.append("Существующие позиции не изменились.")
    if units_guessed:
        outcome.notes.append(
            f"У {units_guessed} новых позиций не заполнена единица — записано «шт»."
        )

    if kind.full_catalog:
        removed, kept = _remove_absent(db, existing, seen)
        if removed or kept:
            note = f"Удалено {removed} поз., которых нет в файле."
            if kept:
                note += f" Оставлено {kept}: на них ссылаются планы или партии."
            outcome.notes.append(note)
    return outcome


def _remove_absent(db: Session, existing: dict[str, Product], seen: set[str]) -> tuple[int, int]:
    """Удалить позиции вне файла. Связанные с планами и партиями остаются.

    Удаление каждой позиции идёт в своей точке сохранения: если на неё
    ссылается план или партия, база отказывает, и позиция остаётся — загрузка
    при этом не падает и остальные позиции удаляются.
    """
    removed = kept = 0
    for code, product in list(existing.items()):
        if code in seen:
            continue
        try:
            with db.begin_nested():
                db.delete(product)
        except IntegrityError:
            kept += 1
        else:
            removed += 1
            del existing[code]
    return removed, kept


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

    if kind.entity == "stock":
        # Остатки — отчёт с шапкой и группировкой, разбор свой.
        from app.services.stock_import_service import import_stock

        return import_stock(db, file_name, content)

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
