"""Черновики корректировок из решения месяца «перенести в план продаж».

Решение месяца фиксирует намерение, а объём переезжает корректировкой плана
менеджера. Этот сервис делает первый шаг за человека: берёт недобор закрытого
месяца по строкам (план − факт) и раскладывает его в черновики корректировок
планов менеджеров на месяц переноса.

Что важно:

* утверждение остаётся за человеком — создаются только черновики, план не меняется,
  пока коммерческий или исполнительный директор не утвердит корректировку;
* если у менеджера уже есть открытая корректировка, его строки пропускаются: две
  правки одного плана одновременно — источник путаницы;
* если на год переноса нет утверждённого плана или месяц заморожен — менеджер
  попадает в список пропущенных с причиной, а не молча теряется.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.planning import SalesPlan, SalesPlanCorrection, SalesPlanCorrectionItem
from app.models.sales import DECISION_TITLES
from app.schemas.planning import SalesPlanCorrectionCreate
from app.services import month_close_service, month_result_service
from app.services import sales_plan_correction_service as correction_service
from app.services.plan_freeze import editable_months

ZERO = Decimal("0")
OPEN_STATUSES = ("draft", "on_review")


class TransferError(Exception):
    """Перенос нельзя оформить: переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class DraftCreated:
    """Созданный черновик корректировки одного менеджера."""

    manager_name: str
    plan_id: uuid.UUID
    correction_id: uuid.UUID
    lines: int
    quantity: Decimal


@dataclass(frozen=True)
class DraftSkipped:
    """Менеджер, чьи строки не удалось перенести, и причина."""

    manager_name: str
    reason: str


@dataclass
class TransferResult:
    created: list[DraftCreated] = field(default_factory=list)
    skipped: list[DraftSkipped] = field(default_factory=list)


def _manager_plan(db: Session, manager_id: uuid.UUID, year: int) -> SalesPlan | None:
    return (
        db.execute(
            select(SalesPlan).where(SalesPlan.year == year, SalesPlan.manager_id == manager_id)
        )
        .scalars()
        .one_or_none()
    )


def _open_correction(db: Session, plan_id: uuid.UUID) -> SalesPlanCorrection | None:
    return (
        db.execute(
            select(SalesPlanCorrection).where(
                SalesPlanCorrection.plan_id == plan_id,
                SalesPlanCorrection.status.in_(OPEN_STATUSES),
            )
        )
        .scalars()
        .first()
    )


def _month_label(month: int) -> str:
    names = (
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
    return names[month - 1]


def transfer_drafts(db: Session, user: User, year: int, month: int) -> TransferResult:
    """Создать черновики корректировок по недобору закрытого месяца."""
    if user.role not in month_close_service.CLOSE_ROLES:
        raise TransferError(
            "Черновики переноса создаёт коммерческий или исполнительный директор",
            status_code=403,
        )
    state = month_close_service.get_result(db, year, month)
    if state is None:
        raise TransferError("Сначала закройте месяц — перенос делается по снимку")
    if state.decision != "transfer_sales":
        raise TransferError(
            "Решение месяца — не «Перенести в план продаж». "
            "Перенос в план закупок оформляется пересмотром плана закупок"
        )
    if state.target_year is None or state.target_month is None:
        raise TransferError("В решении не указан месяц переноса")

    summary = month_result_service.month_summary(db, user, year, month)
    shortfalls: dict[uuid.UUID | None, dict[tuple[uuid.UUID, uuid.UUID], Decimal]] = {}
    names: dict[uuid.UUID | None, str] = {}
    for row in summary.rows:
        shortfall = row.plan_quantity - row.fact_quantity
        if shortfall <= ZERO:
            continue
        key = row.manager_id
        shortfalls.setdefault(key, {})
        shortfalls[key][(row.client_id, row.product_id)] = (
            shortfalls[key].get((row.client_id, row.product_id), ZERO) + shortfall
        )
        names[key] = row.manager_name or "Менеджер не определён"

    if not shortfalls:
        raise TransferError("В месяце нет недобора — переносить нечего")

    result = TransferResult()
    for manager_id, pairs in shortfalls.items():
        manager_name = names.get(manager_id, "Менеджер не определён")
        if manager_id is None:
            result.skipped.append(
                DraftSkipped(manager_name=manager_name, reason="клиент не закреплён за менеджером")
            )
            continue
        plan = _manager_plan(db, manager_id, state.target_year)
        if plan is None or plan.status != "approved":
            result.skipped.append(
                DraftSkipped(
                    manager_name=manager_name,
                    reason=f"нет утверждённого плана на {state.target_year} год",
                )
            )
            continue
        if state.target_month not in editable_months(plan.year):
            result.skipped.append(
                DraftSkipped(
                    manager_name=manager_name,
                    reason=f"месяц переноса заморожен: {_month_label(state.target_month)}",
                )
            )
            continue
        if _open_correction(db, plan.id) is not None:
            result.skipped.append(
                DraftSkipped(manager_name=manager_name, reason="уже есть открытая корректировка")
            )
            continue

        reason = (
            f"Перенос недобора {_month_label(month)} {year} "
            f"({DECISION_TITLES['transfer_sales'].lower()})"
        )
        try:
            correction = correction_service.create(
                db, user, SalesPlanCorrectionCreate(plan_id=plan.id, reason=reason)
            )
        except correction_service.CorrectionError as exc:
            db.rollback()
            result.skipped.append(DraftSkipped(manager_name=manager_name, reason=exc.message))
            continue

        added = _apply_shortfalls(db, correction.id, pairs, state.target_month)
        if added == 0:
            result.skipped.append(
                DraftSkipped(manager_name=manager_name, reason="недобор не удалось разложить")
            )
            continue
        result.created.append(
            DraftCreated(
                manager_name=manager_name,
                plan_id=plan.id,
                correction_id=correction.id,
                lines=len(pairs),
                quantity=sum(pairs.values(), ZERO),
            )
        )
    return result


def _apply_shortfalls(
    db: Session,
    correction_id: uuid.UUID,
    pairs: dict[tuple[uuid.UUID, uuid.UUID], Decimal],
    target_month: int,
) -> int:
    """Добавить недобор к строкам месяца переноса в черновике корректировки.

    Из полной копии оставляем только месяц переноса: перенос не должен заодно
    переписывать другие месяцы плана (и не сломается, когда они станут
    замороженными до утверждения).
    """
    for extra in (
        db.execute(
            select(SalesPlanCorrectionItem).where(
                SalesPlanCorrectionItem.correction_id == correction_id,
                SalesPlanCorrectionItem.month != target_month,
            )
        )
        .scalars()
        .all()
    ):
        db.delete(extra)
    db.flush()
    items = {
        (item.client_id, item.product_id): item
        for item in db.execute(
            select(SalesPlanCorrectionItem).where(
                SalesPlanCorrectionItem.correction_id == correction_id,
                SalesPlanCorrectionItem.month == target_month,
            )
        )
        .scalars()
        .all()
    }
    added = 0
    for (client_id, product_id), quantity in pairs.items():
        item = items.get((client_id, product_id))
        if item is not None:
            item.quantity = item.quantity + quantity
        else:
            db.add(
                SalesPlanCorrectionItem(
                    correction_id=correction_id,
                    client_id=client_id,
                    product_id=product_id,
                    month=target_month,
                    quantity=quantity,
                    current_quantity=ZERO,
                    notes="перенос недобора из итогов месяца",
                )
            )
        added += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return 0
    return added
