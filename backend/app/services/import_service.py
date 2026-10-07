"""Загрузка справочников из выгрузок 1С (.xlsx).

Шесть типов данных, у каждого свой файл и свой набор колонок:

| Тип | Файл | Колонки |
|---|---|---|
| Локальные поставщики | одна колонка | Наименование |
| Импортные поставщики | одна колонка | Наименование |
| Покупатели | одна колонка | Наименование |
| Материалы | три колонки | Код, Наименование, Базовая единица измерения |
| Сырьё | три колонки | Код, Наименование, Базовая единица измерения |
| Готовая продукция | три колонки | Код, Наименование, Базовая единица измерения |

Дубли не создаются: номенклатура опознаётся по коду 1С, контрагенты — по
наименованию без учёта регистра и лишних пробелов. Повторная загрузка того же файла
только обновляет найденные записи.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty, name_key
from app.models.domain import ImportSession, Product

KIND_LOCAL_SUPPLIERS = "local_suppliers"
KIND_IMPORT_SUPPLIERS = "import_suppliers"
KIND_CUSTOMERS = "customers"
KIND_MATERIALS = "materials"
KIND_RAW = "raw"
KIND_FINISHED = "finished"

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_ROWS = 50_000
MAX_PROBLEMS = 5


@dataclass(frozen=True)
class ImportKind:
    """Описание типа загрузки."""

    kind: str
    title: str
    entity: str  # products | counterparties
    columns: tuple[str, ...]
    product_kind: str | None = None
    role_field: str | None = None


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
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
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
        for column in kind.columns:
            wanted = _norm_header(column)
            if wanted not in header:
                raise ImportDataError(
                    f"Нет колонки «{column}». Ожидаются колонки: {', '.join(kind.columns)}"
                )
            index[column] = header.index(wanted)

        parsed: list[dict[str, str]] = []
        for row in rows:
            if row is None or all(cell is None for cell in row):
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


def _import_products(
    db: Session, kind: ImportKind, rows: list[dict[str, str]]
) -> tuple[int, int, int, int, list[str]]:
    existing = {row.code: row for row in db.execute(select(Product)).scalars().all()}
    seen: set[str] = set()
    created = updated = skipped = failed = 0
    problems: list[str] = []

    for number, row in enumerate(rows, start=2):
        code = row["Код"]
        name = row["Наименование"]
        unit = row["Базовая единица измерения"] or "шт"
        if not code or not name:
            failed += 1
            if len(problems) < MAX_PROBLEMS:
                problems.append(f"строка {number}: пустой код или наименование")
            continue
        if len(code) > 64 or len(name) > 255 or len(unit) > 16:
            failed += 1
            if len(problems) < MAX_PROBLEMS:
                problems.append(f"строка {number}: слишком длинные значения")
            continue
        if code in seen:
            skipped += 1
            if len(problems) < MAX_PROBLEMS:
                problems.append(f"строка {number}: код {code} уже встречался в файле")
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
            created += 1
        else:
            product.name = name
            product.unit = unit
            if kind.product_kind is not None:
                product.kind = kind.product_kind
            product.source = "1c"
            updated += 1
    return created, updated, skipped, failed, problems


def _import_counterparties(
    db: Session, kind: ImportKind, rows: list[dict[str, str]]
) -> tuple[int, int, int, int, list[str]]:
    if kind.role_field is None:  # pragma: no cover — защита от неверной конфигурации
        raise ImportDataError("У типа загрузки не задан признак роли")

    existing = {row.name_key: row for row in db.execute(select(Counterparty)).scalars().all()}
    seen: set[str] = set()
    created = updated = skipped = failed = 0
    problems: list[str] = []

    for number, row in enumerate(rows, start=2):
        name = row["Наименование"]
        if not name:
            failed += 1
            if len(problems) < MAX_PROBLEMS:
                problems.append(f"строка {number}: пустое наименование")
            continue
        if len(name) > 255:
            failed += 1
            if len(problems) < MAX_PROBLEMS:
                problems.append(f"строка {number}: наименование длиннее 255 символов")
            continue
        key = name_key(name)
        if key in seen:
            skipped += 1
            if len(problems) < MAX_PROBLEMS:
                problems.append(f"строка {number}: «{name}» уже встречался в файле")
            continue
        seen.add(key)

        counterparty = existing.get(key)
        if counterparty is None:
            counterparty = Counterparty(name=name, name_key=key, source="1c")
            setattr(counterparty, kind.role_field, True)
            db.add(counterparty)
            existing[key] = counterparty
            created += 1
        else:
            counterparty.name = name
            setattr(counterparty, kind.role_field, True)
            if counterparty.source != "manual":
                counterparty.source = "1c"
            updated += 1
    return created, updated, skipped, failed, problems


def import_file(db: Session, kind_code: str, file_name: str, content: bytes) -> ImportResult:
    """Загружает файл выгрузки и пишет журнал. Идемпотентно."""
    kind = KINDS.get(kind_code)
    if kind is None:
        raise ImportDataError(f"Неизвестный тип загрузки: {kind_code}", status_code=404)

    rows = _read_rows(content, kind)
    if kind.entity == "products":
        created, updated, skipped, failed, problems = _import_products(db, kind, rows)
    else:
        created, updated, skipped, failed, problems = _import_counterparties(db, kind, rows)

    if failed and not created and not updated:
        status = "failed"
    elif failed:
        status = "partial"
    else:
        status = "ok"

    session = ImportSession(
        kind=kind.kind,
        file_name=file_name,
        content_hash=hashlib.sha256(content).hexdigest(),
        status=status,
        rows_total=len(rows),
        rows_created=created,
        rows_updated=updated,
        rows_skipped=skipped,
        rows_failed=failed,
        message="; ".join(problems) if problems else None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return ImportResult(session=session, problems=problems)


def list_sessions(db: Session, *, limit: int = 20) -> list[ImportSession]:
    statement = select(ImportSession).order_by(ImportSession.created_at.desc()).limit(limit)
    return list(db.execute(statement).scalars().all())
