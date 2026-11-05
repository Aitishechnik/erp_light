"""Загрузка продаж за месяц из отчёта 1С и сопоставление номенклатуры.

Файл — отчёт 1С «Продажи» за период: шапка с периодом, строки, сгруппированные
«Контрагент» → «Номенклатура», и итог. Одна строка файла — клиент × товар × месяц
(в файле данные уже сгруппированы по контрагенту и номенклатуре).

Правила:

* период берётся из шапки («Период: Октябрь 2026 г.»), при необходимости его можно
  передать явно;
* клиенты ищутся по ключу наименования; неизвестный клиент — отказ файла целиком
  (сначала грузим справочник покупателей, потом продажи);
* номенклатура ищется по нормализованному названию: регистр, «ё», кавычки, точки и
  запятые, лишние пробелы и хвост «, шт / кг / гр» не важны; при нескольких
  кандидатах предпочитаем «готовую продукцию»;
* не опознанная или неоднозначная позиция не угадывается: строка лежит в очереди
  сопоставления и в итоги не идёт, пока её не сопоставят вручную; выбор
  запоминается алиасом;
* возвраты — строки с минусом; они сохраняются как есть;
* повторная загрузка месяца заменяет его целиком (идемпотентно).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.counterparties import Counterparty, name_key
from app.models.domain import ImportSession, Product
from app.models.sales import ProductAlias, SalesFact, SalesFactUnmatched
from app.services.import_service import (
    MAX_FILE_SIZE,
    MAX_PROBLEMS,
    ImportDataError,
    ImportResult,
    Outcome,
    _repair_part_names,
)

ZERO = Decimal("0")
QUANTITY_STEP = Decimal("0.001")

# Первые три буквы месяца в шапке 1С: «Октябрь 2026 г.».
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

PERIOD_RE = re.compile(r"период:\s*([^\d]+?)\s*(\d{4})", re.IGNORECASE)

# Хвосты единиц измерения в названии: «… коробка, 500 гр., шт».
UNIT_TOKENS = frozenset({"шт", "кг", "гр", "г", "уп", "пач", "л", "мл", "компл", "наб"})

HEADER_ROW_LIMIT = 30


@dataclass(frozen=True)
class SalesLine:
    """Строка отчёта: клиент, название позиции и суммы."""

    client_name: str
    product_name: str
    quantity: Decimal
    amount_rub: Decimal
    discount_rub: Decimal


@dataclass
class ParsedSales:
    """Разобранный файл: период и строки."""

    year: int
    month: int
    lines: list[SalesLine] = field(default_factory=list)


@dataclass(frozen=True)
class ProductMatch:
    """Итог сопоставления названия: товар или причина, почему его нет."""

    product: Product | None
    reason: str = ""  # missing | ambiguous


def product_key(name: str) -> str:
    """Ключ названия позиции: без единиц измерения и знаков препинания."""
    text = str(name).casefold().replace("ё", "е").replace("«", '"').replace("»", '"')
    text = re.sub(r"[.,;:]", " ", text)
    words = [word for word in text.split() if word not in UNIT_TOKENS]
    return " ".join(words).strip()


def _decimal(value: Any) -> Decimal:
    """Число из ячейки: 1С может отдать и число, и строку с пробелами."""
    if value is None:
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


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _month_from_word(word: str) -> int | None:
    pitch = word.strip().casefold()[:3]
    for prefix, month in MONTH_PREFIXES:
        if pitch == prefix:
            return month
    return None


def _read_period(sheet: Any) -> tuple[int, int] | None:
    """Период из шапки: «Период: Октябрь 2026 г.»."""
    for row in range(1, min(HEADER_ROW_LIMIT, sheet.max_row) + 1):
        for column in range(1, min(4, sheet.max_column) + 1):
            text = _text(sheet.cell(row=row, column=column).value)
            found = PERIOD_RE.search(text)
            if found is None:
                continue
            month = _month_from_word(found.group(1))
            year = int(found.group(2))
            if month is None or not 2020 <= year <= 2100:
                return None
            return year, month
    return None


def _find_header(sheet: Any) -> tuple[int, dict[str, int]]:
    """Строка заголовков и номера колонок отчёта."""
    for row in range(1, min(HEADER_ROW_LIMIT, sheet.max_row) + 1):
        columns: dict[str, int] = {}
        for column in range(1, sheet.max_column + 1):
            title = _text(sheet.cell(row=row, column=column).value).casefold()
            if not title:
                continue
            if title == "контрагент":
                columns["client"] = column
            elif title.startswith("количество"):
                columns["quantity"] = column
            elif title.startswith("сумма продажи без скидок"):
                columns["no_discount"] = column
            elif title.startswith("сумма продажи"):
                columns["amount"] = column
            elif title.startswith("сумма скидки"):
                columns["discount"] = column
        if "client" in columns and "quantity" in columns and "amount" in columns:
            return row, columns
    raise ImportDataError(
        "Не похоже на отчёт «Продажи» из 1С: нет колонок «Контрагент», "
        "«Количество» и «Сумма продажи»"
    )


def parse_sales_file(content: bytes) -> ParsedSales:
    """Разобрать отчёт «Продажи»: период и строки клиент × позиция."""
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
        period = _read_period(sheet)
        if period is None:
            raise ImportDataError(
                "В шапке нет периода вида «Период: Октябрь 2026 г.» — "
                "выгрузите отчёт за месяц из 1С"
            )
        year, month = period
        header_row, columns = _find_header(sheet)

        parsed = ParsedSales(year=year, month=month)
        client = ""
        for row in range(header_row + 1, sheet.max_row + 1):
            cell = sheet.cell(row=row, column=columns["client"])
            name = _text(cell.value)
            if not name:
                continue
            lowered = name.casefold()
            if lowered.startswith("номенклатура") or lowered == "контрагент":
                continue
            indent = cell.alignment.indent if cell.alignment is not None else 0
            is_group = bool(cell.font is not None and cell.font.bold) or not indent
            if lowered.startswith("итог"):
                break
            if is_group:
                client = name
                continue
            if not client:
                raise ImportDataError(f"Строка {row}: позиция «{name}» идёт до первого контрагента")
            parsed.lines.append(
                SalesLine(
                    client_name=client,
                    product_name=name,
                    quantity=_decimal(cell_value(sheet, row, columns, "quantity")),
                    amount_rub=_decimal(cell_value(sheet, row, columns, "amount")),
                    discount_rub=_decimal(cell_value(sheet, row, columns, "discount")),
                )
            )
        # Пустой отчёт — тоже факт: продаж за месяц не было. Раньше такой файл
        # отклонялся, и месяц нельзя было закрыть.
        return parsed
    finally:
        workbook.close()


def cell_value(sheet: Any, row: int, columns: dict[str, int], name: str) -> Any:
    """Значение колонки, если она есть в отчёте."""
    column = columns.get(name)
    if column is None:
        return None
    return sheet.cell(row=row, column=column).value


@dataclass
class _ProductIndex:
    """Указатели для сопоставления названий: справочник и алиасы."""

    by_key: dict[str, list[Product]]
    aliases: dict[str, Product]

    def resolve(self, name: str) -> ProductMatch:
        key = product_key(name)
        alias = self.aliases.get(key)
        if alias is not None:
            return ProductMatch(product=alias)
        candidates = self.by_key.get(key, [])
        if len(candidates) == 1:
            return ProductMatch(product=candidates[0])
        finished = [row for row in candidates if row.kind == "finished"]
        if len(finished) == 1:
            return ProductMatch(product=finished[0])
        if not candidates:
            return ProductMatch(product=None, reason="missing")
        return ProductMatch(product=None, reason="ambiguous")


def _product_index(db: Session) -> _ProductIndex:
    by_key: dict[str, list[Product]] = {}
    for product in db.execute(select(Product)).scalars().all():
        by_key.setdefault(product_key(product.name), []).append(product)
    aliases = {
        row.name_key: row.product
        for row in db.execute(select(ProductAlias)).scalars().all()
        if row.product is not None
    }
    return _ProductIndex(by_key=by_key, aliases=aliases)


def _clients(db: Session) -> dict[str, Counterparty]:
    return {row.name_key: row for row in db.execute(select(Counterparty)).scalars().all()}


def _add_fact(
    db: Session,
    facts: dict[tuple[uuid.UUID, uuid.UUID], SalesFact],
    *,
    year: int,
    month: int,
    client_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: Decimal,
    amount_rub: Decimal,
    discount_rub: Decimal,
    session_id: uuid.UUID,
) -> SalesFact:
    """Накопить строку в памяти: одна строка на клиента и товар."""
    key = (client_id, product_id)
    fact = facts.get(key)
    if fact is None:
        fact = SalesFact(
            year=year,
            month=month,
            client_id=client_id,
            product_id=product_id,
            quantity=ZERO,
            amount_rub=ZERO,
            discount_rub=ZERO,
            import_session_id=session_id,
        )
        db.add(fact)
        facts[key] = fact
    fact.quantity = (fact.quantity + quantity).quantize(QUANTITY_STEP)
    fact.amount_rub = fact.amount_rub + amount_rub
    fact.discount_rub = fact.discount_rub + discount_rub
    return fact


def import_sales(
    db: Session,
    file_name: str,
    content: bytes,
    *,
    year: int | None = None,
    month: int | None = None,
) -> ImportResult:
    """Загрузить продажи за месяц: заменить месяц целиком, повторить можно."""
    parsed = parse_sales_file(content)
    period_year = year or parsed.year
    period_month = month or parsed.month
    if not 1 <= period_month <= 12:
        raise ImportDataError("Месяц продаж должен быть от 1 до 12")

    from app.services.month_close_service import is_closed

    if is_closed(db, period_year, period_month):
        raise ImportDataError(
            "Месяц закрыт — откройте его заново, чтобы загрузить другие продажи",
            status_code=409,
        )

    clients = _clients(db)
    missing: list[str] = []
    for line in parsed.lines:
        if name_key(line.client_name) not in clients and line.client_name not in missing:
            missing.append(line.client_name)
    if missing:
        shown = ", ".join(f"«{name}»" for name in missing[:MAX_PROBLEMS])
        tail = " и другие" if len(missing) > MAX_PROBLEMS else ""
        raise ImportDataError(
            f"Клиенты не найдены в справочнике: {shown}{tail}. "
            "Сначала загрузите файл «Покупатели», потом продажи"
        )

    index = _product_index(db)
    session = ImportSession(
        kind="sales",
        year=period_year,
        month=period_month,
        file_name=file_name,
        content_hash=hashlib.sha256(content).hexdigest(),
        status="pending",
        rows_total=len(parsed.lines),
        rows_created=0,
        rows_updated=0,
        rows_skipped=0,
        rows_failed=0,
    )
    db.add(session)
    db.flush()

    db.execute(
        delete(SalesFact).where(SalesFact.year == period_year, SalesFact.month == period_month)
    )
    db.execute(
        delete(SalesFactUnmatched).where(
            SalesFactUnmatched.year == period_year, SalesFactUnmatched.month == period_month
        )
    )

    facts: dict[tuple[uuid.UUID, uuid.UUID], SalesFact] = {}
    unmatched: dict[tuple[uuid.UUID, str], SalesFactUnmatched] = {}
    returns = 0
    ambiguous: list[str] = []
    missing_products: list[str] = []

    for line in parsed.lines:
        client = clients[name_key(line.client_name)]
        match = index.resolve(line.product_name)
        if line.quantity < 0 or line.amount_rub < 0:
            returns += 1
        if match.product is not None:
            _add_fact(
                db,
                facts,
                year=period_year,
                month=period_month,
                client_id=client.id,
                product_id=match.product.id,
                quantity=line.quantity,
                amount_rub=line.amount_rub,
                discount_rub=line.discount_rub,
                session_id=session.id,
            )
            continue
        key = (client.id, product_key(line.product_name))
        pending = unmatched.get(key)
        if pending is None:
            pending = SalesFactUnmatched(
                import_session_id=session.id,
                year=period_year,
                month=period_month,
                client_id=client.id,
                source_name=line.product_name,
                name_key=product_key(line.product_name),
                quantity=ZERO,
                amount_rub=ZERO,
            )
            db.add(pending)
            unmatched[key] = pending
        pending.quantity = (pending.quantity + line.quantity).quantize(QUANTITY_STEP)
        pending.amount_rub = pending.amount_rub + line.amount_rub
        if match.reason == "ambiguous" and line.product_name not in ambiguous:
            ambiguous.append(line.product_name)
        if match.reason == "missing" and line.product_name not in missing_products:
            missing_products.append(line.product_name)

    outcome = Outcome(
        created=len(facts),
        failed=len(unmatched),
        skipped=0,
    )
    for name in ambiguous[:MAX_PROBLEMS]:
        outcome.problem(
            f"«{name}»: в справочнике несколько подходящих позиций — сопоставьте вручную"
        )
    for name in missing_products[:MAX_PROBLEMS]:
        outcome.problem(f"«{name}»: позиции нет в справочнике — сопоставьте вручную")
    outcome.notes.append(
        f"месяц {period_month:02d}.{period_year} заменён целиком; "
        f"строк в файле: {len(parsed.lines)}, возвратов: {returns}"
    )
    if unmatched:
        outcome.notes.append(f"не сопоставлено: {len(unmatched)}")

    session.rows_created = outcome.created
    session.rows_failed = outcome.failed
    session.rows_skipped = 0
    if outcome.failed and not outcome.created:
        session.status = "failed"
    elif outcome.failed:
        session.status = "partial"
    else:
        session.status = "ok"
    session.message = "; ".join(outcome.problems + outcome.notes) or None

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


@dataclass(frozen=True)
class MatchResult:
    """Итог ручного сопоставления: сколько строк ушло в факт и сколько осталось."""

    matched: int
    remaining: int


def match_unmatched(db: Session, unmatched_id: uuid.UUID, product_id: uuid.UUID) -> MatchResult:
    """Сопоставить название из файла карточке номенклатуры и запомнить алиас."""
    row = db.get(SalesFactUnmatched, unmatched_id)
    if row is None:
        raise ImportDataError("Строка сопоставления не найдена — обновите экран", status_code=404)
    product = db.get(Product, product_id)
    if product is None:
        raise ImportDataError("Позиция номенклатуры не найдена", status_code=404)

    alias = (
        db.execute(select(ProductAlias).where(ProductAlias.name_key == row.name_key))
        .scalars()
        .one_or_none()
    )
    if alias is None:
        db.add(ProductAlias(name_key=row.name_key, product_id=product.id))
    else:
        alias.product_id = product.id

    siblings = (
        db.execute(
            select(SalesFactUnmatched).where(
                SalesFactUnmatched.year == row.year,
                SalesFactUnmatched.month == row.month,
                SalesFactUnmatched.name_key == row.name_key,
            )
        )
        .scalars()
        .all()
    )
    existing = {
        (fact.client_id, fact.product_id): fact
        for fact in db.execute(
            select(SalesFact).where(
                SalesFact.year == row.year,
                SalesFact.month == row.month,
                SalesFact.product_id == product.id,
            )
        )
        .scalars()
        .all()
    }
    matched = 0
    for sibling in siblings:
        if sibling.client_id is None:
            continue
        fact = existing.get((sibling.client_id, product.id))
        if fact is None:
            fact = SalesFact(
                year=row.year,
                month=row.month,
                client_id=sibling.client_id,
                product_id=product.id,
                quantity=ZERO,
                amount_rub=ZERO,
                discount_rub=ZERO,
                import_session_id=sibling.import_session_id,
            )
            db.add(fact)
            existing[(sibling.client_id, product.id)] = fact
        fact.quantity = (fact.quantity + sibling.quantity).quantize(QUANTITY_STEP)
        fact.amount_rub = fact.amount_rub + sibling.amount_rub
        db.delete(sibling)
        matched += 1

    db.commit()
    remaining = db.execute(
        select(func.count())
        .select_from(SalesFactUnmatched)
        .where(SalesFactUnmatched.year == row.year, SalesFactUnmatched.month == row.month)
    ).scalar_one()
    return MatchResult(matched=matched, remaining=int(remaining))
