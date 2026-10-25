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

from app.models.auth import ROLE_SALES_MANAGER, User
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.planning import SalesPlan
from app.models.sales import SalesFact, SalesFactUnmatched

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
