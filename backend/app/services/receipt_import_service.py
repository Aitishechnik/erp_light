"""Черновики импортных поступлений из выгрузки 1С.

Файл «ИмпортныеПоступления» содержит только шапки поступлений. Из него берём
четыре колонки — **Номер, Дата, Контрагент, Комментарий** — и создаём партию-черновик:
позиций и платежей у неё нет, их дозаполняют в карточке или другой выгрузкой.
Суммы, валюта, склад, организация и состояние ЭДО в расчёт не идут.

Правила:
  * поступление опознаётся **по номеру** — повторная загрузка обновляет дату,
    поставщика и комментарий, а не создаёт дубль;
  * поставщик ищется в справочнике контрагентов по наименованию; страна в скобках
    в конце («AZHAZELNUT LLC (Азербайджан)») на поиск не влияет;
  * поставщика нет — заводим его автоматически с признаком «импортный поставщик»;
  * номер занят заполненным или заведённым вручную поступлением — строка
    пропускается и попадает в отчёт.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.counterparties import Counterparty, name_key
from app.models.domain import Batch
from app.services.import_service import MAX_PROBLEMS, Outcome

# Курс черновику не нужен: пока в партии нет позиций, считать нечего.
DRAFT_CURRENCY = "RUB"

DATE_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def parse_date(value: str) -> date | None:
    """Дата из 1С: «06.10.2026 11:14:21», «06.10.2026» или ISO-формат."""
    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def supplier_key(name: str) -> str:
    """Ключ поиска поставщика без страны в скобках на конце."""
    without_country = re.sub(r"\s*\([^)]*\)\s*$", "", str(name))
    return " ".join(without_country.split()).strip().casefold()


def _supplier_maps(db: Session) -> tuple[dict[str, Counterparty], dict[str, Counterparty]]:
    """Два указателя на справочник: точное наименование и без страны в скобках."""
    exact: dict[str, Counterparty] = {}
    short: dict[str, Counterparty] = {}
    for row in db.execute(select(Counterparty)).scalars().all():
        exact.setdefault(row.name_key, row)
        short.setdefault(supplier_key(row.name), row)
    return exact, short


def _resolve_supplier(
    db: Session,
    name: str,
    exact: dict[str, Counterparty],
    short: dict[str, Counterparty],
) -> tuple[Counterparty | None, bool]:
    """Поставщик из справочника; если такого нет — заводим импортного."""
    text = " ".join(name.split()).strip()
    if not text:
        return None, False

    key = name_key(text)
    found = exact.get(key) or short.get(supplier_key(text))
    if found is not None:
        return found, False

    created = Counterparty(
        name=text,
        name_key=key,
        is_import_supplier=True,
        source="1c",
    )
    db.add(created)
    exact[key] = created
    short[supplier_key(text)] = created
    return created, True


def import_receipts(db: Session, rows: list[dict[str, str]]) -> Outcome:
    """Создать или обновить черновики поступлений по строкам выгрузки."""
    outcome = Outcome()
    exact, short = _supplier_maps(db)
    batches = {
        row.batch_number: row
        for row in db.execute(select(Batch).options(selectinload(Batch.items))).scalars().all()
    }
    seen: set[str] = set()
    new_suppliers = 0

    for number, row in enumerate(rows, start=2):
        batch_number = row["Номер"].strip()
        batch_date = parse_date(row["Дата"])
        if not batch_number:
            outcome.failed += 1
            outcome.problem(f"строка {number}: пустой номер поступления")
            continue
        if batch_date is None:
            outcome.failed += 1
            outcome.problem(f"строка {number}: не разобрана дата «{row['Дата']}»")
            continue
        if batch_number in seen:
            outcome.skipped += 1
            outcome.problem(f"строка {number}: номер {batch_number} уже встречался в файле")
            continue
        seen.add(batch_number)

        supplier, supplier_created = _resolve_supplier(db, row["Контрагент"], exact, short)
        if supplier_created:
            new_suppliers += 1
        comment = row["Комментарий"].strip() or None

        batch = batches.get(batch_number)
        if batch is None:
            batch = Batch(
                batch_number=batch_number,
                batch_type="purchase",
                batch_date=batch_date,
                currency=DRAFT_CURRENCY,
                supplier_id=supplier.id if supplier is not None else None,
                supplier=supplier.name if supplier is not None else None,
                source="1c",
                comment=comment,
            )
            db.add(batch)
            batches[batch_number] = batch
            outcome.created += 1
            continue

        if batch.source == "1c" and not batch.items:
            batch.batch_date = batch_date
            batch.supplier_id = supplier.id if supplier is not None else None
            batch.supplier = supplier.name if supplier is not None else None
            batch.comment = comment
            outcome.updated += 1
            continue

        outcome.skipped += 1
        outcome.problem(
            f"строка {number}: поступление {batch_number} уже заполнено — строка пропущена"
        )

    if new_suppliers:
        outcome.notes.append(f"заведено новых поставщиков: {new_suppliers}")
    return outcome


__all__ = [
    "MAX_PROBLEMS",
    "import_receipts",
    "parse_date",
    "supplier_key",
]
