"""Растаможка партии: проценты пошлины и НДС превращаются в фикс в рублях.

Курс таможенных платежей берётся на **дату растаможки** (она не обязана совпадать с
датой прихода товара на склад) и фиксируется навсегда: дальше пошлину и НДС не
трогают ни движение валюты, ни платежи, ни общие расходы. Пока партия растаможена,
строки неизменны — правка только через отмену растаможки.

Деньги считает [`cost.py`](cost.py): здесь только раскладка итога по строкам и
запись в партию.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.domain import Batch
from app.schemas.domain import BatchCustomsIn
from app.services.batch_service import load_batch
from app.services.cost import (
    ZERO,
    CustomsLine,
    customs_lines,
    customs_totals_rub,
    items_from_batch,
    q2,
    q6,
    split_fixed_rub,
)

#: Тексты отказов — их показываем пользователю как есть.
ALREADY_CLEARED = "Партия уже растаможена: сначала отмените растаможку"
NO_ITEMS = "У поступления нет позиций: растаможивать нечего"


def _weights(lines: list[CustomsLine], field: str) -> list[Decimal]:
    """Веса раскладки ручной правки: пошлина (НДС) строки, иначе инвойсная стоимость."""
    values = [getattr(line, field) for line in lines]
    if sum(values, ZERO) > 0:
        return values
    # Пошлина по процентам нулевая во всех строках — делим по стоимости товара.
    return [line.invoice_currency for line in lines]


def apply_customs(db: Session, batch_id: uuid.UUID, payload: BatchCustomsIn) -> Batch | None:
    """Зафиксировать пошлину и НДС партии в рублях по курсу на дату растаможки.

    Возвращает ``None``, если партии нет; при уже растаможенной партии или партии
    без позиций поднимает ``ValueError`` — API отдаёт по нему 400.
    """
    batch = load_batch(db, batch_id)
    if batch is None:
        return None
    if batch.customs_date is not None:
        raise ValueError(ALREADY_CLEARED)
    if not batch.items:
        raise ValueError(NO_ITEMS)

    lines = customs_lines(items_from_batch(batch))
    duty_total, vat_total = customs_totals_rub(lines, payload.rate)
    if payload.duty_rub is not None:
        duty_total = q2(payload.duty_rub)
    if payload.vat_rub is not None:
        vat_total = q2(payload.vat_rub)

    duties = split_fixed_rub(duty_total, _weights(lines, "duty_currency"))
    vats = split_fixed_rub(vat_total, _weights(lines, "vat_currency"))
    for item, duty, vat in zip(batch.items, duties, vats, strict=True):
        item.duty_fixed_rub = duty
        item.vat_fixed_rub = vat

    batch.customs_date = payload.customs_date
    batch.customs_rate = q6(payload.rate)
    db.commit()
    return load_batch(db, batch_id)


def cancel_customs(db: Session, batch_id: uuid.UUID) -> Batch | None:
    """Снять фиксацию: в строках снова действуют проценты пошлины и НДС."""
    batch = load_batch(db, batch_id)
    if batch is None:
        return None
    if batch.customs_date is None:
        raise ValueError("Партия не растаможена: отменять нечего")
    for item in batch.items:
        item.duty_fixed_rub = None
        item.vat_fixed_rub = None
    batch.customs_date = None
    batch.customs_rate = None
    db.commit()
    return load_batch(db, batch_id)
