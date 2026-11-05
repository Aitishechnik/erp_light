"""Сигнал закупкам: перевыполнение плана продаж — нужен пересмотр плана закупок.

Вызывается при закрытии месяца. Сравнивает факт продаж за месяц с планом
продаж того же месяца по каждой позиции: если продали больше плана, сырья
не хватило — по нормам расхода считаем, сколько ещё нужно, и пишем служебное
сообщение закупщикам.

Недобор и перенос недобора на следующий период закупки не трогают: товар
под этот объём уже закуплен, он учтён в распределении плана закупок. Склад
и остатки в расчёте не участвуют — «сколько уже учтено» видно из плана.

Количества не правятся: утверждённый план закупок меняет человек, вернув его
в работу. Сигнал только показывает, чего не хватило и на сколько.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auth import ROLE_IMPORT_MANAGER, ROLE_PURCHASE_DIRECTOR, User
from app.models.planning import PurchasePlan, PurchasePlanItem
from app.models.sales import SalesFact
from app.services import audit_service
from app.services import purchase_need as need

ZERO = Decimal("0")

# Кому уходит сигнал: тем, кто правит план закупок.
PURCHASE_AUDIENCE = (ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER)

MONTH_NAMES = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def _plan(db: Session, year: int) -> PurchasePlan | None:
    return db.execute(select(PurchasePlan).where(PurchasePlan.year == year)).scalars().one_or_none()


def _qty(value: Decimal) -> str:
    """Число по-русски: десятичная запятая и без хвостовых нулей."""
    text = f"{value.normalize():f}"
    return text.replace(".", ",") if "." in text else text


def _line_payload(item: PurchasePlanItem, units: Decimal) -> dict[str, object]:
    raw = need.quantize_qty(units * item.norm) if item.norm is not None else None
    return {
        "item_id": str(item.id),
        "sales_product": item.sales_product.name,
        "product": item.product.name,
        "unit": item.product.unit,
        "norm": str(item.norm) if item.norm is not None else None,
        "units_delta": str(need.quantize_qty(units)),
        "raw_delta": str(raw) if raw is not None else None,
        "alternative": item.alternative_of_id is not None,
    }


def _month_label(month: int) -> str:
    return MONTH_NAMES[month - 1]


def notify_overperformance(
    db: Session,
    *,
    actor: User | None,
    year: int,
    month: int,
) -> int:
    """Посчитать перевыполнение месяца и, если оно есть, позвать закупщиков.

    Возвращает число затронутых строк плана закупок: 0 — сигнала нет.
    Коммит делает вызывающий сервис (закрытие месяца).
    """
    plan = _plan(db, year)
    if plan is None:
        return 0
    db.flush()

    plan_month = {
        product_id: position.months.get(month, ZERO)
        for product_id, position in need.need_positions(db, year).items()
    }
    facts = db.execute(
        select(SalesFact.product_id, func.sum(SalesFact.quantity))
        .where(SalesFact.year == year, SalesFact.month == month)
        .group_by(SalesFact.product_id)
    ).all()

    # Перевыполнение по позиции: продали больше, чем стояло в плане месяца.
    over: dict[uuid.UUID, Decimal] = {}
    for product_id, quantity in facts:
        delta = need.quantize_qty(quantity or ZERO) - plan_month.get(product_id, ZERO)
        if delta > ZERO:
            over[product_id] = delta
    if not over:
        return 0

    lines = [
        _line_payload(item, over[item.sales_product_id])
        for item in plan.items
        if over.get(item.sales_product_id) not in (None, ZERO)
    ]
    if not lines:
        return 0

    missing_norm = [row["product"] for row in lines if row["norm"] is None]
    details: list[str] = []
    for row in lines[:3]:
        units = Decimal(str(row["units_delta"]))
        text = f"{row['sales_product']}: +{_qty(units)} ед."
        raw = row["raw_delta"]
        if raw is None:
            text += " — норма не задана"
        else:
            text += f" → +{_qty(Decimal(str(raw)))} {row['unit']}"
            if row["alternative"]:
                text += " (альтернатива)"
        details.append(text)
    tail = f" и ещё {len(lines) - 3}" if len(lines) > 3 else ""
    label = _month_label(month)
    summary = (
        f"Продажи за {label} {year} выше плана: позиций {len(over)}, строк плана "
        f"закупок {len(lines)} — нужно увеличить план закупок. " + "; ".join(details) + tail
    )
    reason = f"перевыполнение плана продаж за {label} {year}"
    audit_service.record(
        db,
        actor=actor,
        action="purchase_plan.revision_needed",
        summary=summary,
        entity_id=plan.id,
        entity_label=f"План закупок, {year}",
        payload={
            "reason": reason,
            "month": month,
            "overperformance": [
                {
                    "product_id": str(product_id),
                    "sales_plan": str(plan_month.get(product_id, ZERO)),
                    "fact": str(
                        need.quantize_qty(over[product_id] + plan_month.get(product_id, ZERO))
                    ),
                    "delta": str(need.quantize_qty(over[product_id])),
                }
                for product_id in over
            ],
            "lines": lines,
            "missing_norm": missing_norm,
        },
        year=year,
        month=month,
        audience=PURCHASE_AUDIENCE,
    )

    if plan.status == "approved" and plan.revision_requested_at is None:
        plan.revision_requested_at = datetime.now(UTC)
        plan.revision_requested_by_id = actor.id if actor is not None else None
        note = f"Запрошен пересмотр: {reason}"
        plan.notes = f"{plan.notes}\n{note}" if plan.notes else note
    return len(lines)
