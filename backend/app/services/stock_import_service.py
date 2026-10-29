"""Загрузка отчёта 1С «Товары на складах» — остатки и движение по номенклатуре.

Файл — отчёт 1С: шапка с периодом («Период: 28 октября 2026 г.») и группировка
«Номенклатура → Серия номенклатуры → Документ движения». Позицией считается
только строка с кодом номенклатуры: у серий и документов движения код пуст, они
в загрузку не попадают.

Колонки: Начальный остаток, Приход, Расход, Конечный остаток.

Правила:

* позиция опознаётся по коду 1С — тому же, что в справочнике номенклатуры;
* позиции, которых нет в справочнике, не создаются: строка пропускается, а коды
  попадают в итог загрузки. Так справочник не засоряется полуфабрикатами и
  ингредиентами, которые в него не входят;
* отсутствие позиции в файле (нет ни остатка, ни движения) — это ноль, а не
  ошибка: 1С показывает только то, что лежит или двигалось за день;
* повторная загрузка за ту же дату заменяет числа по позиции, а не создаёт дубль.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.domain import ImportSession, Product, StockBalance
from app.services.import_service import (
    MAX_FILE_SIZE,
    MAX_PROBLEMS,
    ImportDataError,
    ImportResult,
    Outcome,
    _repair_part_names,
)

ZERO = Decimal("0")
STEP = Decimal("0.001")
HEADER_ROW_LIMIT = 30

# Первые три буквы месяца в шапке 1С: «28 октября 2026 г.».
MONTH_PREFIXES = (
    ("янв", 1),
    ("фев", 2),
    ("мар", 3),
    ("апр", 4),
    ("май", 5),
    ("мая", 5),
    ("июн", 6),
    ("июл", 7),
    ("авг", 8),
    ("сен", 9),
    ("окт", 10),
    ("ноя", 11),
    ("дек", 12),
)

PERIOD_RE = re.compile(r"(\d{1,2})\s+([А-Яа-яЁё]+)\s+(\d{4})")


@dataclass(frozen=True)
class StockRow:
    """Строка отчёта: остаток на начало дня, движение за день и остаток на конец."""

    code: str
    name: str
    opening: Decimal
    income: Decimal
    outcome: Decimal
    closing: Decimal


@dataclass(frozen=True)
class ParsedStock:
    """Разобранный файл: дата отчёта и строки номенклатуры."""

    period: date | None
    rows: list[StockRow]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _norm(value: Any) -> str:
    return _text(value).casefold()


def _decimal(value: Any) -> Decimal:
    """Число из ячейки: 1С отдаёт и число, и строку с пробелами."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if not text:
        return ZERO
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ImportDataError(f"В файле не число: «{value}»") from exc


def _month_from_word(word: str) -> int | None:
    pitch = word.strip().casefold()[:3]
    for prefix, month in MONTH_PREFIXES:
        if pitch == prefix:
            return month
    return None


def _read_period(rows: list[tuple[Any, ...]]) -> date | None:
    """Дата из шапки: «Период: 28 октября 2026 г.»."""
    for row in rows[:HEADER_ROW_LIMIT]:
        for cell in row:
            text = _text(cell)
            if not text.casefold().startswith("период"):
                continue
            found = PERIOD_RE.search(text)
            if found is None:
                continue
            month = _month_from_word(found.group(2))
            year = int(found.group(3))
            if month is None or not 2020 <= year <= 2100:
                return None
            return date(year, month, int(found.group(1)))
    return None


@dataclass(frozen=True)
class _Columns:
    """Номера колонок отчёта: код, наименование и четыре числа."""

    code: int
    name: int
    opening: int
    income: int
    outcome: int
    closing: int
    header_row: int


def _find_columns(rows: list[tuple[Any, ...]]) -> _Columns:
    """Найти шапку отчёта: код и наименование, затем строку с числами.

    У отчёта два уровня шапки: сначала «Номенклатура, Базовая единица измерения»
    и «Код», ниже — «Начальный остаток», «Приход», «Расход», «Конечный остаток».
    Названия колонок с числами могут занимать две строки, поэтому ищем их в
    пределах двух строк под шапкой.
    """
    for row_index, row in enumerate(rows[:HEADER_ROW_LIMIT]):
        cells = [_norm(cell) for cell in row]
        if "код" not in cells:
            continue
        name_index = next(
            (index for index, cell in enumerate(cells) if cell.startswith("номенклатура")),
            None,
        )
        if name_index is None:
            continue
        code_index = cells.index("код")
        for offset in range(0, 3):
            if row_index + offset >= len(rows):
                break
            titles = [_norm(cell) for cell in rows[row_index + offset]]
            positions: dict[str, int] = {}
            for index, title in enumerate(titles):
                if title.startswith("начальный остаток"):
                    positions["opening"] = index
                elif title.startswith("приход"):
                    positions["income"] = index
                elif title.startswith("расход"):
                    positions["outcome"] = index
                elif title.startswith("конечный остаток"):
                    positions["closing"] = index
            if len(positions) == 4:
                return _Columns(
                    code=code_index,
                    name=name_index,
                    opening=positions["opening"],
                    income=positions["income"],
                    outcome=positions["outcome"],
                    closing=positions["closing"],
                    header_row=row_index + offset,
                )
    raise ImportDataError(
        "Не похоже на отчёт «Товары на складах» из 1С: нет колонок «Код», "
        "«Номенклатура», «Начальный остаток», «Приход», «Расход» и «Конечный остаток»"
    )


def parse_stock_file(content: bytes) -> ParsedStock:
    """Разобрать отчёт: дата периода и строки с кодом номенклатуры."""
    if not content:
        raise ImportDataError("Файл пустой")
    if len(content) > MAX_FILE_SIZE:
        raise ImportDataError("Файл больше 10 МБ — выгрузку нужно разделить")
    try:
        workbook = load_workbook(BytesIO(_repair_part_names(content)), data_only=True)
    except Exception as exc:  # noqa: BLE001 — любая ошибка чтения .xlsx
        raise ImportDataError("Не удалось прочитать файл: нужен .xlsx из 1С") from exc

    try:
        sheet = workbook.worksheets[0]
        if sheet.max_row is None or sheet.max_row < 2:
            raise ImportDataError("В файле нет строк отчёта")
        rows = [tuple(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()

    columns = _find_columns(rows)
    period = _read_period(rows)

    parsed: list[StockRow] = []
    for row in rows[columns.header_row + 1 :]:
        if columns.code >= len(row):
            continue
        code = _text(row[columns.code])
        # Серии и документы движения идут без кода — это не позиция номенклатуры.
        if not code or code.casefold() == "код":
            continue
        name = _text(row[columns.name]) if columns.name < len(row) else ""
        try:
            opening = _decimal(row[columns.opening])
            income = _decimal(row[columns.income])
            outcome = _decimal(row[columns.outcome])
            closing = _decimal(row[columns.closing])
        except ImportDataError as exc:
            raise ImportDataError(f"{code}: {exc.message}") from exc
        parsed.append(
            StockRow(
                code=code,
                name=name,
                opening=opening.quantize(STEP),
                income=income.quantize(STEP),
                outcome=outcome.quantize(STEP),
                closing=closing.quantize(STEP),
            )
        )
    if not parsed:
        raise ImportDataError("В файле нет строк с кодом номенклатуры")
    return ParsedStock(period=period, rows=parsed)


def latest_balances(db: Session, product_ids: list[Any]) -> dict[Any, StockBalance]:
    """Самый свежий остаток по каждой позиции."""
    if not product_ids:
        return {}
    latest = (
        select(
            StockBalance.product_id.label("product_id"),
            func.max(StockBalance.balance_date).label("max_date"),
        )
        .where(StockBalance.product_id.in_(list(product_ids)))
        .group_by(StockBalance.product_id)
        .subquery()
    )
    rows = (
        db.execute(
            select(StockBalance).join(
                latest,
                (StockBalance.product_id == latest.c.product_id)
                & (StockBalance.balance_date == latest.c.max_date),
            )
        )
        .scalars()
        .all()
    )
    return {row.product_id: row for row in rows}


def import_stock(
    db: Session,
    file_name: str,
    content: bytes,
    *,
    on_date: date | None = None,
) -> ImportResult:
    """Загрузить остатки за дату. Позиции вне справочника пропускаются."""
    parsed = parse_stock_file(content)
    balance_date = on_date or parsed.period
    if balance_date is None:
        raise ImportDataError(
            "В шапке файла нет периода («Период: 28 октября 2026 г.») — " "укажите дату отчёта"
        )

    products = {row.code: row for row in db.execute(select(Product)).scalars().all()}
    merged: dict[Any, StockRow] = {}
    unknown: list[str] = []
    for row in parsed.rows:
        product = products.get(row.code)
        if product is None:
            unknown.append(f"{row.code} · {row.name}")
            continue
        # Одна позиция может прийти несколькими складами — складываем.
        previous = merged.get(product.id)
        if previous is None:
            merged[product.id] = row
            continue
        merged[product.id] = StockRow(
            code=row.code,
            name=row.name,
            opening=previous.opening + row.opening,
            income=previous.income + row.income,
            outcome=previous.outcome + row.outcome,
            closing=previous.closing + row.closing,
        )

    existing = {
        row.product_id: row
        for row in db.execute(select(StockBalance).where(StockBalance.balance_date == balance_date))
        .scalars()
        .all()
    }

    outcome = Outcome(skipped=len(unknown))
    for product_id, row in merged.items():
        stored = existing.get(product_id)
        if stored is None:
            db.add(
                StockBalance(
                    product_id=product_id,
                    balance_date=balance_date,
                    opening=row.opening,
                    income=row.income,
                    outcome=row.outcome,
                    closing=row.closing,
                    source="1c",
                )
            )
            outcome.created += 1
            continue
        stored.opening = row.opening
        stored.income = row.income
        stored.outcome = row.outcome
        stored.closing = row.closing
        stored.source = "1c"
        outcome.updated += 1

    if unknown:
        shown = "; ".join(unknown[:MAX_PROBLEMS])
        tail = f" и ещё {len(unknown) - MAX_PROBLEMS}" if len(unknown) > MAX_PROBLEMS else ""
        outcome.notes.append(f"пропущено, нет в справочнике: {len(unknown)} — {shown}{tail}")
    outcome.notes.append(
        f"остатки на {balance_date:%d.%m.%Y}: позиций {len(merged)}, "
        f"приход {sum(row.income for row in merged.values()):.3f}, "
        f"расход {sum(row.outcome for row in merged.values()):.3f}"
    )

    if not merged and unknown:
        raise ImportDataError(
            f"Ни одна позиция отчёта не нашлась в справочнике: кодов {len(unknown)}. "
            "Сначала загрузите файл «Номенклатура»"
        )

    session = ImportSession(
        kind="stock",
        file_name=file_name,
        content_hash=hashlib.sha256(content).hexdigest(),
        status="ok",
        rows_total=len(parsed.rows),
        rows_created=outcome.created,
        rows_updated=outcome.updated,
        rows_skipped=outcome.skipped,
        rows_failed=0,
        message="; ".join(outcome.problems + outcome.notes) or None,
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ImportDataError(
            "Эту выгрузку уже сохраняет другой пользователь — повторите загрузку",
            status_code=409,
        ) from exc
    db.refresh(session)
    return ImportResult(session=session, problems=outcome.problems)
