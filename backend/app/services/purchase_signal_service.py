"""Сигнал закупкам: план продаж изменился — нужен пересмотр плана закупок.

Вызывается после применения корректировки плана продаж (в том числе созданной
переносом недобора из итогов месяца). Сравнивает снимок плана продаж, с которым
составлялся план закупок, с текущей потребностью и, если позиции разошлись,
пишет служебное сообщение закупщикам и запрашивает пересмотр плана.

Количества не правятся: утверждённый план закупок меняет человек, вернув его
в работу. Сигнал только показывает, что именно выросло или просело.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import ROLE_IMPORT_MANAGER, ROLE_PURCHASE_DIRECTOR, User
from app.models.planning import PurchasePlan, PurchasePlanItem
from app.services import audit_service
from app.services import purchase_need as need

ZERO = Decimal("0")

# Кому уходит сигнал: тем, кто правит план закупок.
PURCHASE_AUDIENCE = (ROLE_PURCHASE_DIRECTOR, ROLE_IMPORT_MANAGER)


def _plan(db: Session, year: int) -> PurchasePlan | None:
    return db.execute(select(PurchasePlan).where(PurchasePlan.year == year)).scalars().one_or_none()


def _units_by_product(changes: list[need.NeedChange]) -> dict[uuid.UUID, Decimal]:
    """Суммарная дельта продаж по позиции за год (в единицах позиции)."""
    totals: dict[uuid.UUID, Decimal] = {}
    for change in changes:
        before = change.was or ZERO
        after = change.now or ZERO
        totals[change.product_id] = totals.get(change.product_id, ZERO) + (after - before)
    return totals


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


def notify_sales_change(
    db: Session,
    *,
    actor: User | None,
    year: int,
    reason: str,
) -> int:
    """Создать сигнал закупкам, если изменение продаж задело план закупок.

    Возвращает число затронутых строк плана закупок: 0 — сигнала нет.
    Коммит делает вызывающий сервис. Снимка нет — сравнивать не с чем, сигнала
    тоже нет: без базовой версии любое изменение выглядело бы как «всё новое».
    """
    plan = _plan(db, year)
    if plan is None or plan.source_snapshot is None:
        return 0
    db.flush()
    changes = need.diff_positions(
        need.snapshot_positions(plan.source_snapshot),
        need.need_positions(db, year),
    )
    if not changes:
        return 0

    units = _units_by_product(changes)
    lines = [
        _line_payload(item, units[item.sales_product_id])
        for item in plan.items
        if units.get(item.sales_product_id) not in (None, ZERO)
    ]
    if not lines:
        return 0

    missing_norm = [row["product"] for row in lines if row["norm"] is None]
    products = len({change.product_id for change in changes})
    # Показатели — прямо в сообщении: закупщик видит, что именно выросло и на сколько,
    # не открывая план. Строки без нормы так и помечаем.
    details: list[str] = []
    for row in lines[:3]:
        units_delta = Decimal(str(row["units_delta"]))
        sign = "+" if units_delta > 0 else "−"
        text = f"{row['sales_product']}: {sign}{_qty(abs(units_delta))} ед."
        raw = row["raw_delta"]
        if raw is None:
            text += " — норма не задана"
        else:
            text += f" → {_qty(Decimal(str(raw)))} {row['unit']}"
            if row["alternative"]:
                text += " (альтернатива)"
        details.append(text)
    tail = f" и ещё {len(lines) - 3}" if len(lines) > 3 else ""
    summary = (
        f"План продаж на {year} год изменён: позиций {products}, строк плана закупок "
        f"{len(lines)} — нужен пересмотр плана закупок. " + "; ".join(details) + tail
    )
    audit_service.record(
        db,
        actor=actor,
        action="purchase_plan.revision_needed",
        summary=summary,
        entity_id=plan.id,
        entity_label=f"План закупок, {year}",
        payload={
            "reason": reason,
            "changes": [
                {
                    "product": change.name,
                    "code": change.code,
                    "month": change.month,
                    "was": str(change.was) if change.was is not None else None,
                    "now": str(change.now) if change.now is not None else None,
                }
                for change in changes
            ],
            "lines": lines,
            "missing_norm": missing_norm,
        },
        year=year,
        audience=PURCHASE_AUDIENCE,
    )

    if plan.status == "approved" and plan.revision_requested_at is None:
        plan.revision_requested_at = datetime.now(UTC)
        plan.revision_requested_by_id = actor.id if actor is not None else None
        note = f"Запрошен пересмотр: {reason}"
        plan.notes = f"{plan.notes}\n{note}" if plan.notes else note
    return len(lines)
