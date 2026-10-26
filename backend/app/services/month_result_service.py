"""Итоги месяца: план продаж против факта продаж.

План — строки утверждённых планов менеджеров за месяц (корректировки уже применены
к строкам). Факт — продажи за месяц из выгрузки 1С. Ключ сравнения — клиент × товар.

Отклонение считается по количеству: в плане продаж цен нет, деньги есть только у
факта. Строка попадает в одну из трёх групп:

* ``plan`` — есть и план, и факт;
* ``extra`` — факт без плана («продали то, чего не планировали»);
* ``short`` — план без факта («плановое количество, но продаж ноль»).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import ROLE_COMMERCIAL_DIRECTOR, ROLE_SALES_MANAGER, User
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import SalesPlan
from app.models.sales import (
    REASON_CODES,
    DeviationReason,
    MonthResult,
    SalesFact,
    SalesFactUnmatched,
)

ZERO = Decimal("0")


@dataclass(frozen=True)
class MonthRow:
    """Одна строка отчёта: клиент, товар, план и факт."""

    client_id: uuid.UUID
    client_name: str
    manager_id: uuid.UUID | None
    manager_name: str | None
    product_id: uuid.UUID
    product_name: str
    unit: str
    plan_quantity: Decimal
    fact_quantity: Decimal
    fact_amount: Decimal
    group: str
    manager_mismatch: bool
    reason: DeviationReason | None = None
    reason_author: str | None = None

    @property
    def deviation(self) -> Decimal:
        return self.fact_quantity - self.plan_quantity


@dataclass
class MonthSummary:
    """Месяц целиком: строки, очередь сопоставления и признак утверждённого плана."""

    year: int
    month: int
    plan_approved: bool
    rows: list[MonthRow] = field(default_factory=list)
    unmatched: list[SalesFactUnmatched] = field(default_factory=list)

    @property
    def extra_lines(self) -> int:
        return sum(1 for row in self.rows if row.group == "extra")

    @property
    def short_lines(self) -> int:
        return sum(1 for row in self.rows if row.group == "short")

    @property
    def deviation_lines(self) -> int:
        return sum(1 for row in self.rows if row.fact_quantity != row.plan_quantity)

    @property
    def fact_amount(self) -> Decimal:
        return sum((row.fact_amount for row in self.rows), ZERO)

    @property
    def without_reason(self) -> int:
        """Строки с отклонением, у которых ещё нет причины."""
        return sum(1 for row in self.rows if row.deviation != ZERO and row.reason is None)


def _plan_map(
    db: Session, year: int, month: int
) -> dict[tuple[uuid.UUID, uuid.UUID], tuple[Decimal, set[uuid.UUID]]]:
    """План по ключу клиент × товар: количество и менеджеры, которые его запланировали."""
    plans = (
        db.execute(
            select(SalesPlan)
            .where(SalesPlan.year == year, SalesPlan.status == "approved")
            .options(selectinload(SalesPlan.items))
        )
        .scalars()
        .all()
    )
    result: dict[tuple[uuid.UUID, uuid.UUID], tuple[Decimal, set[uuid.UUID]]] = {}
    for plan in plans:
        for item in plan.items:
            if item.month != month:
                continue
            key = (item.client_id, item.product_id)
            quantity, managers = result.get(key, (ZERO, set()))
            result[key] = (quantity + item.quantity, managers | {plan.manager_id})
    return result


def _manager_names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    users = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    return {user.id: user.full_name for user in users}


def _plan_approved(db: Session, year: int) -> bool:
    return (
        db.execute(
            select(SalesPlan.id)
            .where(SalesPlan.year == year, SalesPlan.status == "approved")
            .limit(1)
        ).first()
        is not None
    )


def month_summary(db: Session, user: User, year: int, month: int) -> MonthSummary:
    """Собрать итоги месяца; менеджер по продажам видит только свои строки."""
    plans = _plan_map(db, year, month)
    facts = (
        db.execute(select(SalesFact).where(SalesFact.year == year, SalesFact.month == month))
        .scalars()
        .all()
    )
    fact_by_key = {(fact.client_id, fact.product_id): fact for fact in facts}
    keys = set(plans) | set(fact_by_key)

    clients = {
        row.id: row
        for row in db.execute(
            select(Counterparty).where(Counterparty.id.in_({key[0] for key in keys}))
        )
        .scalars()
        .all()
    }
    products = {
        row.id: row
        for row in db.execute(select(Product).where(Product.id.in_({key[1] for key in keys})))
        .scalars()
        .all()
    }

    manager_ids: set[uuid.UUID] = set()
    for client_id, _ in keys:
        client = clients.get(client_id)
        if client is None:
            continue
        if client.manager_id is not None:
            manager_ids.add(client.manager_id)
        manager_ids.update(plans.get((client_id, _), (ZERO, set()))[1])
    names = _manager_names(db, manager_ids)
    reasons = _month_reasons(db, year, month)

    rows: list[MonthRow] = []
    for client_id, product_id in keys:
        client = clients.get(client_id)
        product = products.get(product_id)
        if client is None or product is None:  # pragma: no cover — защита от битых ссылок
            continue
        fact = fact_by_key.get((client_id, product_id))
        plan_quantity, plan_managers = plans.get((client_id, product_id), (ZERO, set()))
        manager_id = next(iter(plan_managers)) if len(plan_managers) == 1 else client.manager_id
        mismatch = (
            len(plan_managers) == 1
            and client.manager_id is not None
            and client.manager_id not in plan_managers
        )
        if fact is None:
            group = "short"
        elif plan_quantity == ZERO:
            group = "extra"
        else:
            group = "plan"
        rows.append(
            MonthRow(
                client_id=client_id,
                client_name=client.name,
                manager_id=manager_id,
                manager_name=names.get(manager_id) if manager_id is not None else None,
                product_id=product_id,
                product_name=product.name,
                unit=product.unit,
                plan_quantity=plan_quantity,
                fact_quantity=fact.quantity if fact is not None else ZERO,
                fact_amount=fact.amount_rub if fact is not None else ZERO,
                group=group,
                manager_mismatch=mismatch,
                reason=reasons.get((client_id, product_id), (None, None))[0],
                reason_author=reasons.get((client_id, product_id), (None, None))[1],
            )
        )

    if user.role == ROLE_SALES_MANAGER:
        rows = [row for row in rows if row.manager_id == user.id]

    rows.sort(key=lambda row: (row.manager_name or "", row.client_name, row.product_name))
    return MonthSummary(
        year=year,
        month=month,
        plan_approved=_plan_approved(db, year),
        rows=rows,
        unmatched=month_unmatched(db, year, month),
    )


def _month_reasons(
    db: Session, year: int, month: int
) -> dict[tuple[uuid.UUID, uuid.UUID], tuple[DeviationReason, str | None]]:
    """Причины месяца по ключу клиент × товар вместе с именем автора."""
    rows = (
        db.execute(
            select(DeviationReason).where(
                DeviationReason.year == year, DeviationReason.month == month
            )
        )
        .scalars()
        .all()
    )
    names = _manager_names(db, {row.author_id for row in rows if row.author_id is not None})
    return {
        (row.client_id, row.product_id): (
            row,
            names.get(row.author_id) if row.author_id is not None else None,
        )
        for row in rows
    }


def month_unmatched(db: Session, year: int, month: int) -> list[SalesFactUnmatched]:
    """Очередь сопоставления за месяц — по названию позиции."""
    return list(
        db.execute(
            select(SalesFactUnmatched)
            .where(SalesFactUnmatched.year == year, SalesFactUnmatched.month == month)
            .order_by(SalesFactUnmatched.source_name)
        )
        .scalars()
        .all()
    )


class ReasonError(Exception):
    """Причину нельзя поставить: переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# Кто ставит причины: менеджер по своим строкам и коммерческий директор по всем.
REASON_ROLES = (ROLE_SALES_MANAGER, ROLE_COMMERCIAL_DIRECTOR)
MAX_COMMENT = 500


def _month_closed(db: Session, year: int, month: int) -> bool:
    """Закрытый месяц не принимает правку причин."""
    return (
        db.execute(
            select(MonthResult.id).where(
                MonthResult.year == year,
                MonthResult.month == month,
                MonthResult.status == "closed",
            )
        ).first()
        is not None
    )


def _find_row(
    db: Session, user: User, year: int, month: int, client_id: uuid.UUID, product_id: uuid.UUID
) -> MonthRow:
    """Строка так, как её видит пользователь: чужая для менеджера — 404."""
    summary = month_summary(db, user, year, month)
    for row in summary.rows:
        if row.client_id == client_id and row.product_id == product_id:
            return row
    raise ReasonError("Строки нет в итогах месяца", status_code=404)


def set_reason(
    db: Session,
    user: User,
    year: int,
    month: int,
    client_id: uuid.UUID,
    product_id: uuid.UUID,
    reason: str,
    comment: str | None,
) -> DeviationReason:
    """Поставить или изменить причину отклонения по строке месяца."""
    if user.role not in REASON_ROLES:
        raise ReasonError("Причину ставит менеджер или коммерческий директор", status_code=403)
    if _month_closed(db, year, month):
        raise ReasonError("Месяц закрыт — причину менять нельзя", status_code=409)
    if reason not in REASON_CODES:
        raise ReasonError("Неизвестная причина", status_code=400)
    text = (comment or "").strip() or None
    if reason == "other" and text is None:
        raise ReasonError("Для причины «Другое» нужен комментарий")
    if text is not None and len(text) > MAX_COMMENT:
        raise ReasonError(f"Комментарий длиннее {MAX_COMMENT} символов")
    row = _find_row(db, user, year, month, client_id, product_id)
    if row.deviation == ZERO:
        raise ReasonError("У этой строки нет отклонения — причина не нужна")

    existing = (
        db.execute(
            select(DeviationReason).where(
                DeviationReason.year == year,
                DeviationReason.month == month,
                DeviationReason.client_id == client_id,
                DeviationReason.product_id == product_id,
            )
        )
        .scalars()
        .one_or_none()
    )
    if existing is None:
        existing = DeviationReason(
            year=year,
            month=month,
            client_id=client_id,
            product_id=product_id,
            reason=reason,
            comment=text,
            author_id=user.id,
        )
        db.add(existing)
    else:
        existing.reason = reason
        existing.comment = text
        existing.author_id = user.id
    db.commit()
    db.refresh(existing)
    return existing


def clear_reason(
    db: Session, user: User, year: int, month: int, client_id: uuid.UUID, product_id: uuid.UUID
) -> None:
    """Снять причину: строка снова попадёт в «без причины»."""
    if user.role not in REASON_ROLES:
        raise ReasonError("Причину снимает менеджер или коммерческий директор", status_code=403)
    if _month_closed(db, year, month):
        raise ReasonError("Месяц закрыт — причину менять нельзя", status_code=409)
    _find_row(db, user, year, month, client_id, product_id)
    row = (
        db.execute(
            select(DeviationReason).where(
                DeviationReason.year == year,
                DeviationReason.month == month,
                DeviationReason.client_id == client_id,
                DeviationReason.product_id == product_id,
            )
        )
        .scalars()
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.commit()
