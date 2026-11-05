"""Сигнал закупкам: перевыполнение плана продаж — нужен пересмотр плана закупок.

Вызывается при закрытии месяца. Сравнивает факт продаж за месяц с планом
продаж того же месяца по каждой позиции: если продали больше плана, сырья
не хватило — по нормам расхода считаем, сколько ещё нужно, и пишем короткое
служебное сообщение закупщикам со ссылкой на историю изменений плана.

Недобор и перенос недобора на следующий период закупки не трогают: товар
под этот объём уже закуплен, он учтён в распределении плана закупок. Склад
и остатки в расчёте не участвуют — «сколько уже учтено» видно из плана.

Количества не правятся: утверждённый план закупок меняет человек, вернув его
в работу. Сообщение — только сигнал; подробности лежат в истории плана.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
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

SIGNAL_ACTION = "purchase_plan.revision_needed"

# Недобор — не повод увеличивать план: сырьё уже куплено и лежит на складе.
# Сообщение только говорит закупщику, что следующую поставку можно сдвинуть.
CARRY_ACTION = "purchase_plan.carryover"


def _plan(db: Session, year: int) -> PurchasePlan | None:
    return db.execute(select(PurchasePlan).where(PurchasePlan.year == year)).scalars().one_or_none()


def _qty(value: Decimal) -> str:
    """Число по-русски: пробелы между тысячами и десятичная запятая."""
    text = f"{value.normalize():f}"
    whole, _, fraction = text.partition(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{grouped},{fraction}" if fraction else grouped


def _kg(item: PurchasePlanItem, units: Decimal) -> Decimal | None:
    if item.norm is None:
        return None
    return need.quantize_qty(units * item.norm)


def _line_payload(
    item: PurchasePlanItem, plan_units: Decimal, fact_units: Decimal
) -> dict[str, object]:
    was = _kg(item, plan_units)
    now = _kg(item, fact_units)
    return {
        "item_id": str(item.id),
        "sales_product_id": str(item.sales_product_id),
        "sales_product": item.sales_product.name,
        "product": item.product.name,
        "unit": item.product.unit,
        "norm": str(item.norm) if item.norm is not None else None,
        "plan_units": str(need.quantize_qty(plan_units)),
        "fact_units": str(need.quantize_qty(fact_units)),
        "units_delta": str(need.quantize_qty(fact_units - plan_units)),
        "was_kg": str(was) if was is not None else None,
        "now_kg": str(now) if now is not None else None,
        "delta_kg": str(now - was) if was is not None and now is not None else None,
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

    lines: list[dict[str, object]] = []
    for item in plan.items:
        item_delta = over.get(item.sales_product_id)
        if item_delta is None or item_delta == ZERO:
            continue
        plan_units = plan_month.get(item.sales_product_id, ZERO)
        lines.append(_line_payload(item, plan_units, plan_units + item_delta))
    if not lines:
        return 0

    missing_norm = [row["product"] for row in lines if row["norm"] is None]
    added = sum(
        (Decimal(str(row["delta_kg"])) for row in lines if row["delta_kg"] is not None),
        ZERO,
    )
    label = _month_label(month)
    summary = (
        f"Продажи за {label} {year} выше плана: позиций {len(over)}, строк плана "
        f"закупок {len(lines)}, добавка {_qty(added)} кг — история изменений в плане закупок"
    )
    reason = f"перевыполнение плана продаж за {label} {year}"
    audit_service.record(
        db,
        actor=actor,
        action=SIGNAL_ACTION,
        summary=summary,
        entity_id=plan.id,
        entity_label=f"План закупок, {year}",
        payload={
            "reason": reason,
            "month": month,
            "actor": actor.full_name if actor is not None else None,
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


def notify_underperformance(
    db: Session,
    *,
    actor: User | None,
    year: int,
    month: int,
) -> int:
    """Посчитать недобор месяца и сказать закупщикам про остаток на складе.

    Недобор не увеличивает план закупок и не просит пересмотра: сырьё под
    невыполненный план уже куплено, оно закрывает следующие месяцы. Закупщик
    видит остаток в плане и может сдвинуть ближайшую поставку. Возвращает число
    затронутых строк: 0 — сообщения нет. Коммит делает закрытие месяца.
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
    fact_by_product = {
        product_id: need.quantize_qty(quantity or ZERO) for product_id, quantity in facts
    }

    # Недобор по позиции: продали меньше, чем стояло в плане месяца.
    under: dict[uuid.UUID, Decimal] = {}
    for product_id, plan_units in plan_month.items():
        short = plan_units - fact_by_product.get(product_id, ZERO)
        if short > ZERO:
            under[product_id] = short
    if not under:
        return 0

    lines: list[dict[str, object]] = []
    for item in plan.items:
        item_short = under.get(item.sales_product_id)
        if item_short is None:
            continue
        plan_units = plan_month.get(item.sales_product_id, ZERO)
        lines.append(_line_payload(item, plan_units, plan_units - item_short))
    if not lines:
        return 0

    missing_norm = [row["product"] for row in lines if row["norm"] is None]
    leftover = sum(
        (-Decimal(str(row["delta_kg"])) for row in lines if row["delta_kg"] is not None),
        ZERO,
    )
    label = _month_label(month)
    summary = (
        f"Продажи за {label} {year} ниже плана: позиций {len(under)}, строк плана "
        f"закупок {len(lines)}, остаток {_qty(leftover)} кг закрывает следующие месяцы — "
        "поставки можно сдвинуть"
    )
    reason = f"недобор плана продаж за {label} {year}"
    audit_service.record(
        db,
        actor=actor,
        action=CARRY_ACTION,
        summary=summary,
        entity_id=plan.id,
        entity_label=f"План закупок, {year}",
        payload={
            "reason": reason,
            "month": month,
            "actor": actor.full_name if actor is not None else None,
            "lines": lines,
            "missing_norm": missing_norm,
        },
        year=year,
        month=month,
        audience=PURCHASE_AUDIENCE,
    )
    return len(lines)


def history(db: Session, plan: PurchasePlan) -> list[dict[str, Any]]:
    """История сигналов по плану: что менялось, было и стало.

    Читается из журнала: отдельной таблицы нет. События без полей «было/стало»
    (старый формат) пропускаем — их всё равно не показать построчно.
    """
    events = (
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.action == SIGNAL_ACTION,
                AuditEvent.entity_id == plan.id,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    result: list[dict[str, Any]] = []
    for event in events:
        payload = event.payload or {}
        lines = [
            row
            for row in payload.get("lines", [])
            if isinstance(row, dict) and row.get("plan_units") is not None
        ]
        if not lines:
            continue
        result.append(
            {
                "id": event.id,
                "created_at": event.created_at,
                "month": payload.get("month"),
                "reason": payload.get("reason"),
                "actor_name": payload.get("actor"),
                "lines": lines,
            }
        )
    return result
