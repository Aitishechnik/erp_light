"""Позиции партии из выгрузки 1С «Партия» (грузятся из карточки поступления).

Из файла берём только то, что есть в нашей программе: **номенклатуру** (поиск в
справочнике по наименованию) и **количество**. Остальные колонки выгрузки —
способ отражения расходов, серия, коэффициент, цена, суммы, НДС, страна
происхождения, заказ поставщику, заказ, склад, счёт передачи — не читаются.

Финансовую часть партии (цены, суммы, курс, себестоимость) этот загрузчик не
считает — это отдельная задача. Строки создаются без инвойсной суммы, поэтому
такая партия в остатки не попадает, пока суммы не появятся.

Правила:
  * файл принимается целиком или не принимается вовсе: если хоть одна строка не
    сходится со справочником, в поступлении ничего не меняется, а причины
    показываются закупщику;
  * номенклатура ищется по наименованию без учёта регистра, «ё» и лишних
    пробелов; нашлось несколько позиций — просим уточнить справочник, сами не
    угадываем;
  * новая номенклатура не заводится;
  * единица измерения из файла сверяется со справочником: количество в другой
    единице испортило бы себестоимость единицы;
  * повторная загрузка заменяет позиции партии; если у партии уже есть платежи,
    замена отклоняется — суммы платежей считались бы от другого инвойса.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Batch, BatchItem, ImportSession, Product
from app.services.import_service import (
    KIND_BATCH_ITEMS,
    MAX_PROBLEMS,
    ImportDataError,
    read_rows,
)


def name_key(name: str) -> str:
    """Ключ поиска номенклатуры: регистр, «ё» и лишние пробелы не важны."""
    return " ".join(str(name).split()).strip().casefold().replace("ё", "е")


def parse_quantity(value: str) -> Decimal | None:
    """Количество из 1С: «20000», «20 000», «2 000,5». None — если не число."""
    text = " ".join(str(value).split()).replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class PreparedItem:
    """Разобранная и проверенная строка файла."""

    product: Product
    quantity: Decimal


def _product_map(db: Session) -> dict[str, list[Product]]:
    """Справочник номенклатуры, разложенный по ключу наименования."""
    found: dict[str, list[Product]] = {}
    for product in db.execute(select(Product)).scalars().all():
        found.setdefault(name_key(product.name), []).append(product)
    return found


def _prepare(db: Session, rows: list[dict[str, str]]) -> tuple[list[PreparedItem], list[str]]:
    """Проверить все строки файла. Пишем только если проблем нет ни в одной."""
    products = _product_map(db)
    prepared: list[PreparedItem] = []
    problems: list[str] = []

    for number, row in enumerate(rows, start=2):
        name = row["Номенклатура"].strip()
        quantity = parse_quantity(row["Количество"])
        unit = row.get("Ед.", "").strip()

        if not name:
            problems.append(f"строка {number}: пустая номенклатура")
            continue
        if quantity is None:
            problems.append(f"строка {number}: не разобрано количество «{row['Количество']}»")
            continue
        if quantity <= 0:
            problems.append(f"строка {number}: количество должно быть больше нуля")
            continue

        matches = products.get(name_key(name), [])
        if not matches:
            problems.append(f"строка {number}: номенклатура «{name}» не найдена в справочнике")
            continue
        if len(matches) > 1:
            codes = ", ".join(sorted(product.code for product in matches))
            problems.append(
                f"строка {number}: по названию «{name}» в справочнике несколько позиций ({codes})"
            )
            continue

        product = matches[0]
        if unit and name_key(unit) != name_key(product.unit):
            problems.append(
                f"строка {number}: единица в файле «{unit}», а в справочнике «{product.unit}»"
            )
            continue

        prepared.append(PreparedItem(product=product, quantity=quantity))

    return prepared, problems


def _message(problems: list[str]) -> str:
    """Текст для закупщика: первые MAX_PROBLEMS причин и сколько ещё осталось."""
    head = problems[:MAX_PROBLEMS]
    text = "Файл не загружен. " + "; ".join(head)
    rest = len(problems) - len(head)
    if rest > 0:
        text += f" (и ещё {rest})"
    return text


def _journal(
    db: Session,
    batch: Batch,
    file_name: str,
    content: bytes,
    *,
    rows_total: int,
    loaded: int,
    replaced: int,
    problems: list[str],
) -> ImportSession:
    """Строка журнала загрузок: видно и в карточке поступления, и на «Загрузке данных»."""
    message = [f"поступление {batch.batch_number}: загружено строк {loaded}"]
    if replaced:
        message.append(f"заменено прежних строк: {replaced}")
    message.extend(problems)
    session = ImportSession(
        kind=KIND_BATCH_ITEMS,
        file_name=file_name,
        content_hash=hashlib.sha256(content).hexdigest(),
        status="failed" if problems else "ok",
        rows_total=rows_total,
        rows_created=loaded,
        rows_updated=replaced,
        rows_skipped=0,
        rows_failed=len(problems),
        message="; ".join(message),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def import_items(db: Session, batch: Batch, file_name: str, content: bytes) -> ImportSession:
    """Заменить позиции партии строками файла «Партия» из 1С."""
    rows = read_rows(content, KIND_BATCH_ITEMS)
    prepared, problems = _prepare(db, rows)
    if not problems and not prepared:
        problems = ["в файле нет строк с товаром"]

    if problems:
        _journal(
            db,
            batch,
            file_name,
            content,
            rows_total=len(rows),
            loaded=0,
            replaced=0,
            problems=problems,
        )
        raise ImportDataError(_message(problems))

    replaced = len(batch.items)
    for item in list(batch.items):
        db.delete(item)
    db.flush()
    for row in prepared:
        db.add(
            BatchItem(
                batch_id=batch.id,
                product_id=row.product.id,
                quantity=row.quantity,
            )
        )

    return _journal(
        db,
        batch,
        file_name,
        content,
        rows_total=len(rows),
        loaded=len(prepared),
        replaced=replaced,
        problems=[],
    )


__all__ = [
    "MAX_PROBLEMS",
    "PreparedItem",
    "import_items",
    "name_key",
    "parse_quantity",
]
