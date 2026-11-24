"""Страница «План и факт»: годовой план, месячный план и факт по месяцам.

Годовой план — утверждённые планы менеджеров. Месячный — утверждённый пересмотр
месяца; если менеджер месяц не пересматривал, его месячный план равен годовому.
Факт — продажи из выгрузки 1С. Сравнение по количеству: цен в плане продаж нет.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import User
from app.models.counterparties import Counterparty
from app.models.domain import Product
from app.models.monthly_plans import MonthlySalesPlan
from app.models.planning import SalesPlan
from app.models.sales import REASON_TITLES, DeviationReason, MonthResult, SalesFact
from app.permissions import scope_of
from app.schemas.plan_fact import (
    PlanFactDetailOut,
    PlanFactMonthOut,
    PlanFactRowOut,
    PlanFactSummaryOut,
)
from app.services.monthly_sales_plan_service import window_bounds, window_state

ZERO = Decimal("0")
QUANTITY_STEP = Decimal("0.001")
MONTHS = range(1, 13)


def _q(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_STEP)


@dataclass
class _Month:
    year: int
    month: int
    annual: Decimal = ZERO
    monthly: Decimal = ZERO
    fact: Decimal = ZERO
    fact_lines: int = 0
    revised: bool = False
    managers: int = 0
    monthly_plans: int = 0
    closed: bool = False


def _resolve_manager(user: User, manager_id: uuid.UUID | None) -> uuid.UUID | None:
    if scope_of(user, "plan_fact") == "own":
        return user.id
    return manager_id


def _annual_plans(db: Session, year: int, manager_id: uuid.UUID | None) -> list[SalesPlan]:
    statement = (
        select(SalesPlan)
        .where(SalesPlan.year == year, SalesPlan.status == "approved")
        .options(selectinload(SalesPlan.items))
    )
    if manager_id is not None:
        statement = statement.where(SalesPlan.manager_id == manager_id)
    return list(db.execute(statement).scalars().all())


def _monthly_plans(db: Session, year: int, manager_id: uuid.UUID | None) -> list[MonthlySalesPlan]:
    statement = (
        select(MonthlySalesPlan)
        .where(MonthlySalesPlan.year == year, MonthlySalesPlan.status == "approved")
        .options(selectinload(MonthlySalesPlan.items))
    )
    if manager_id is not None:
        statement = statement.where(MonthlySalesPlan.manager_id == manager_id)
    return list(db.execute(statement).scalars().all())


def _facts(db: Session, year: int, manager_id: uuid.UUID | None) -> list[SalesFact]:
    statement = select(SalesFact).where(SalesFact.year == year)
    if manager_id is not None:
        statement = statement.join(Counterparty, Counterparty.id == SalesFact.client_id).where(
            Counterparty.manager_id == manager_id
        )
    return list(db.execute(statement).scalars().all())


def _closed_months(db: Session, year: int) -> set[int]:
    rows = (
        db.execute(
            select(MonthResult.month).where(
                MonthResult.year == year, MonthResult.status == "closed"
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


def _month_stats(db: Session, year: int, manager_id: uuid.UUID | None) -> list[_Month]:
    annual_plans = _annual_plans(db, year, manager_id)
    monthly_plans = _monthly_plans(db, year, manager_id)
    facts = _facts(db, year, manager_id)
    closed = _closed_months(db, year)

    months = {month: _Month(year=year, month=month) for month in MONTHS}
    annual_by_manager: dict[uuid.UUID, dict[int, Decimal]] = {}
    for annual_plan in annual_plans:
        by_month: dict[int, Decimal] = {}
        for item in annual_plan.items:
            by_month[item.month] = by_month.get(item.month, ZERO) + item.quantity
        annual_by_manager[annual_plan.manager_id] = by_month
        for month, quantity in by_month.items():
            months[month].annual += quantity
            months[month].managers += 1

    monthly_by_manager: dict[uuid.UUID, dict[int, Decimal]] = {}
    for month_plan in monthly_plans:
        by_month = monthly_by_manager.setdefault(month_plan.manager_id, {})
        by_month[month_plan.month] = by_month.get(month_plan.month, ZERO) + sum(
            (item.quantity for item in month_plan.items), ZERO
        )
        months[month_plan.month].monthly_plans += 1
        if any(item.quantity != item.annual_quantity for item in month_plan.items):
            months[month_plan.month].revised = True

    for manager, by_month in monthly_by_manager.items():
        for month, quantity in by_month.items():
            if month in annual_by_manager.get(manager, {}):
                continue
            months[month].monthly += quantity

    for manager, by_month in annual_by_manager.items():
        for month, quantity in by_month.items():
            months[month].monthly += monthly_by_manager.get(manager, {}).get(month, quantity)

    for fact in facts:
        months[fact.month].fact += fact.quantity
        months[fact.month].fact_lines += 1

    for month in MONTHS:
        stat = months[month]
        if stat.monthly != stat.annual:
            stat.revised = True
        stat.closed = month in closed
    return [months[month] for month in MONTHS]


def summary(
    db: Session, user: User, year: int, manager_id: uuid.UUID | None = None
) -> PlanFactSummaryOut:
    target = _resolve_manager(user, manager_id)
    rows = _month_stats(db, year, target)
    months: list[PlanFactMonthOut] = []
    for row in rows:
        start, end = window_bounds(year, row.month)
        if row.monthly_plans == 0:
            monthly_state = "none"
        elif row.managers == 0 or row.monthly_plans >= row.managers:
            monthly_state = "approved"
        else:
            monthly_state = "partial"
        months.append(
            PlanFactMonthOut(
                year=year,
                month=row.month,
                annual_quantity=_q(row.annual),
                monthly_quantity=_q(row.monthly),
                fact_quantity=_q(row.fact),
                fact_loaded=row.fact_lines > 0,
                revised=row.revised,
                monthly_state=monthly_state,
                month_closed=row.closed,
                window_start=start,
                window_end=end,
                window_state=window_state(year, row.month),
            )
        )
    return PlanFactSummaryOut(
        year=year,
        annual_total=sum((row.annual_quantity for row in months), ZERO),
        monthly_total=sum((row.monthly_quantity for row in months), ZERO),
        fact_total=sum((row.fact_quantity for row in months), ZERO),
        months=months,
    )


def _reason_title(reason: DeviationReason) -> str:
    title = REASON_TITLES.get(reason.reason, reason.reason)
    return f"{title}: {reason.comment}" if reason.comment else title


def detail(
    db: Session,
    user: User,
    year: int,
    month: int,
    manager_id: uuid.UUID | None = None,
) -> PlanFactDetailOut:
    target = _resolve_manager(user, manager_id)
    annual_plans = _annual_plans(db, year, target)
    monthly_plans = [plan for plan in _monthly_plans(db, year, target) if plan.month == month]
    facts = [fact for fact in _facts(db, year, target) if fact.month == month]

    annual: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
    annual_manager: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = {}
    for annual_plan in annual_plans:
        for item in annual_plan.items:
            if item.month != month:
                continue
            key = (item.client_id, item.product_id)
            annual[key] = annual.get(key, ZERO) + item.quantity
            annual_manager[key] = annual_plan.manager_id

    monthly: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
    reasons: dict[tuple[uuid.UUID, uuid.UUID], str] = {}
    managers_with_plan = {month_plan.manager_id for month_plan in monthly_plans}
    for month_plan in monthly_plans:
        for month_item in month_plan.items:
            key = (month_item.client_id, month_item.product_id)
            monthly[key] = monthly.get(key, ZERO) + month_item.quantity
            if (
                month_item.quantity != month_item.annual_quantity
                and (month_item.reason or "").strip()
            ):
                reasons.setdefault(key, month_item.reason or "")
    for annual_plan in annual_plans:
        if annual_plan.manager_id in managers_with_plan:
            continue
        for annual_item in annual_plan.items:
            if annual_item.month != month:
                continue
            key = (annual_item.client_id, annual_item.product_id)
            monthly[key] = monthly.get(key, ZERO) + annual_item.quantity

    fact_map = {(fact.client_id, fact.product_id): fact for fact in facts}
    keys = set(annual) | set(monthly) | set(fact_map)

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
    reason_rows = (
        db.execute(
            select(DeviationReason).where(
                DeviationReason.year == year,
                DeviationReason.month == month,
            )
        )
        .scalars()
        .all()
    )
    fact_reasons = {(row.client_id, row.product_id): _reason_title(row) for row in reason_rows}
    manager_ids = {
        manager
        for manager in (
            [*annual_manager.values(), *(client.manager_id for client in clients.values())]
        )
        if manager is not None
    }
    names = {
        user.id: user.full_name
        for user in db.execute(select(User).where(User.id.in_(manager_ids))).scalars().all()
    }

    rows: list[PlanFactRowOut] = []
    for key in keys:
        client = clients.get(key[0])
        product = products.get(key[1])
        if client is None or product is None:  # pragma: no cover — защита от битых ссылок
            continue
        annual_quantity = annual.get(key, ZERO)
        monthly_quantity = monthly.get(key, ZERO)
        fact = fact_map.get(key)
        manager = annual_manager.get(key) or client.manager_id
        rows.append(
            PlanFactRowOut(
                client_id=client.id,
                client_name=client.name,
                manager_id=manager,
                manager_name=names.get(manager) if manager is not None else None,
                product_id=product.id,
                product_name=product.name,
                unit=product.unit,
                annual_quantity=_q(annual_quantity),
                monthly_quantity=_q(monthly_quantity),
                fact_quantity=_q(fact.quantity if fact is not None else ZERO),
                plan_reason=reasons.get(key),
                fact_reason=fact_reasons.get(key),
                is_new=key not in annual and monthly_quantity > ZERO,
                removed=key in annual and monthly_quantity == ZERO and annual_quantity > ZERO,
            )
        )

    rows.sort(key=lambda row: (row.client_name, row.product_name))
    return PlanFactDetailOut(
        year=year,
        month=month,
        annual_quantity=sum((row.annual_quantity for row in rows), ZERO),
        monthly_quantity=sum((row.monthly_quantity for row in rows), ZERO),
        fact_quantity=sum((row.fact_quantity for row in rows), ZERO),
        rows=rows,
    )
