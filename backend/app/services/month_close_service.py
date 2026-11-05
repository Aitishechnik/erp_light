"""Закрытие месяца итогов и решение о переносе нереализованного объёма.

Закрытие фиксирует снимок: план, факт, отклонения, причины и решение на этот
момент. Снимок не пересчитывается задним числом — каждая версия лежит в истории,
а закрытый месяц перестаёт принимать выгрузку продаж и правку причин, пока его
не откроют заново (с обязательной причиной).

Решение месяца — что руководство делает с недобором: переносит объём в план
продаж, переносит его в план закупок или принимает как есть. Планы система сама
не правит: перенос оформляется штатной корректировкой плана продаж или
пересмотром плана закупок.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR, User
from app.models.domain import ImportSession
from app.models.sales import (
    DECISION_CODES,
    DECISION_TITLES,
    REASON_TITLES,
    MonthResult,
    MonthResultSnapshot,
    SalesFact,
)
from app.services import audit_service, month_result_service, purchase_signal_service

CLOSE_ROLES = (ROLE_COMMERCIAL_DIRECTOR, ROLE_EXECUTIVE_DIRECTOR)


class MonthCloseError(Exception):
    """Месяц нельзя закрыть, открыть или решить так, как просят."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_result(db: Session, year: int, month: int) -> MonthResult | None:
    return (
        db.execute(select(MonthResult).where(MonthResult.year == year, MonthResult.month == month))
        .scalars()
        .one_or_none()
    )


def _sales_uploaded(db: Session, year: int, month: int) -> bool:
    """Выгрузка продаж за месяц загружена, даже если строк в ней ноль."""
    return (
        db.execute(
            select(ImportSession.id)
            .where(
                ImportSession.kind == "sales",
                ImportSession.year == year,
                ImportSession.month == month,
                ImportSession.status.in_(("ok", "partial")),
            )
            .limit(1)
        ).first()
        is not None
    )


def is_closed(db: Session, year: int, month: int) -> bool:
    """Закрыт ли месяц: проверяют загрузка продаж и правка причин."""
    result = get_result(db, year, month)
    return result is not None and result.status == "closed"


def history(db: Session, year: int, month: int) -> list[MonthResultSnapshot]:
    """Версии снимков месяца: каждая фиксация закрытия, от старой к новой.

    Снимок не пересчитывается: история показывает, что именно было зафиксировано
    при каждом закрытии, даже если потом месяц открывали и загружали заново.
    """
    result = get_result(db, year, month)
    if result is None:
        return []
    return list(
        db.execute(
            select(MonthResultSnapshot)
            .where(MonthResultSnapshot.month_result_id == result.id)
            .options(selectinload(MonthResultSnapshot.closed_by))
            .order_by(MonthResultSnapshot.version)
        )
        .scalars()
        .all()
    )


def _require_role(user: User) -> None:
    if user.role not in CLOSE_ROLES:
        raise MonthCloseError(
            "Закрывает месяц и принимает решение коммерческий или исполнительный директор",
            status_code=403,
        )


def _snapshot(summary: month_result_service.MonthSummary, result: MonthResult) -> dict[str, Any]:
    """Снимок месяца: строки с причинами, итоги и решение на момент закрытия."""
    rows = []
    for row in summary.rows:
        rows.append(
            {
                "client_id": str(row.client_id),
                "client": row.client_name,
                "manager": row.manager_name,
                "product_id": str(row.product_id),
                "product": row.product_name,
                "unit": row.unit,
                "plan": str(row.plan_quantity),
                "fact": str(row.fact_quantity),
                "amount_rub": str(row.fact_amount),
                "deviation": str(row.deviation),
                "group": row.group,
                "reason": (
                    {
                        "code": row.reason.reason,
                        "title": REASON_TITLES.get(row.reason.reason, row.reason.reason),
                        "comment": row.reason.comment,
                        "author": row.reason_author,
                    }
                    if row.reason is not None
                    else None
                ),
            }
        )
    return {
        "year": summary.year,
        "month": summary.month,
        "plan_approved": summary.plan_approved,
        "rows": rows,
        "totals": {
            "lines": len(summary.rows),
            "deviation_lines": summary.deviation_lines,
            "extra_lines": summary.extra_lines,
            "short_lines": summary.short_lines,
            "without_reason": summary.without_reason,
            "fact_amount": str(summary.fact_amount),
        },
        "decision": _decision_snapshot(result),
        "closed_at": result.closed_at.isoformat() if result.closed_at else None,
        "version": result.version,
    }


def _decision_snapshot(result: MonthResult) -> dict[str, Any] | None:
    if result.decision is None:
        return None
    return {
        "code": result.decision,
        "title": DECISION_TITLES.get(result.decision, result.decision),
        "comment": result.decision_comment,
        "target_year": result.target_year,
        "target_month": result.target_month,
        "author": result.decision_by.full_name if result.decision_by is not None else None,
        "at": result.decision_at.isoformat() if result.decision_at is not None else None,
    }


def close_month(db: Session, user: User, year: int, month: int) -> MonthResult:
    """Закрыть месяц: зафиксировать снимок и запретить правки."""
    _require_role(user)
    result = get_result(db, year, month)
    if result is None:
        result = MonthResult(year=year, month=month, version=0)
        db.add(result)
        db.flush()
    if result.status == "closed":
        raise MonthCloseError("Месяц уже закрыт", status_code=409)

    facts = db.execute(
        select(func.count())
        .select_from(SalesFact)
        .where(SalesFact.year == year, SalesFact.month == month)
    ).scalar_one()
    if not facts and not _sales_uploaded(db, year, month):
        raise MonthCloseError(
            "За этот месяц нет факта продаж — сначала загрузите выгрузку «Продажи»",
            status_code=409,
        )
    summary = month_result_service.month_summary(db, user, year, month)
    if summary.unmatched:
        raise MonthCloseError(
            f"В очереди сопоставления осталось строк: {len(summary.unmatched)} — "
            "сопоставьте их и закройте месяц",
            status_code=409,
        )

    result.version += 1
    result.status = "closed"
    result.closed_by_id = user.id
    result.closed_at = datetime.now().astimezone()
    result.snapshot = _snapshot(summary, result)
    db.add(
        MonthResultSnapshot(
            month_result_id=result.id,
            version=result.version,
            snapshot=result.snapshot,
            closed_by_id=user.id,
            closed_at=result.closed_at,
        )
    )
    # Перевыполнение плана: продали больше, чем запланировали, — закупщику
    # нужен пересмотр плана закупок. Недобор (перенос) закупки не трогает.
    purchase_signal_service.notify_overperformance(db, actor=user, year=year, month=month)
    audit_service.record(
        db,
        actor=user,
        action="month.closed",
        summary=f"Месяц {month:02d}.{year} закрыт, версия снимка {result.version}",
        entity_id=result.id,
        entity_label=f"{month:02d}.{year}",
        payload={"version": result.version, "rows": len(summary.rows)},
        year=year,
        month=month,
    )
    db.commit()
    db.refresh(result)
    return result


def reopen_month(db: Session, user: User, year: int, month: int, reason: str) -> MonthResult:
    """Открыть закрытый месяц заново: причина обязательна, снимок остаётся в истории."""
    _require_role(user)
    text = " ".join((reason or "").split()).strip()
    if not text:
        raise MonthCloseError("Чтобы открыть месяц заново, укажите причину")
    result = get_result(db, year, month)
    if result is None or result.status != "closed":
        raise MonthCloseError("Месяц не закрыт", status_code=409)
    result.status = "open"
    result.reopened_by_id = user.id
    result.reopened_at = datetime.now().astimezone()
    result.reopen_reason = text
    audit_service.record(
        db,
        actor=user,
        action="month.reopened",
        summary=f"Месяц {month:02d}.{year} открыт заново: {text}",
        entity_id=result.id,
        entity_label=f"{month:02d}.{year}",
        year=year,
        month=month,
    )
    db.commit()
    db.refresh(result)
    return result


def set_decision(
    db: Session,
    user: User,
    year: int,
    month: int,
    decision: str,
    *,
    target_year: int | None,
    target_month: int | None,
    comment: str | None,
) -> MonthResult:
    """Решение месяца: перенос в план продаж, перенос в план закупок или «принять»."""
    _require_role(user)
    if decision not in DECISION_CODES:
        raise MonthCloseError("Неизвестное решение месяца")
    if decision != "accept" and (target_year is None or target_month is None):
        raise MonthCloseError("Для переноса укажите месяц, на который переносим")
    if target_month is not None and not 1 <= target_month <= 12:
        raise MonthCloseError("Месяц переноса должен быть от 1 до 12")
    result = get_result(db, year, month)
    if result is None:
        result = MonthResult(year=year, month=month, version=0)
        db.add(result)
    elif result.status == "closed":
        raise MonthCloseError("Месяц закрыт — решение не меняется", status_code=409)

    result.decision = decision
    result.decision_comment = " ".join((comment or "").split()).strip() or None
    result.decision_by_id = user.id
    result.decision_at = datetime.now().astimezone()
    if decision == "accept":
        result.target_year = None
        result.target_month = None
    else:
        result.target_year = target_year
        result.target_month = target_month
    target = (
        f" → {target_month:02d}.{target_year}"
        if decision != "accept" and target_month and target_year
        else ""
    )
    audit_service.record(
        db,
        actor=user,
        action="month.decision_set",
        summary=f"Решение месяца {month:02d}.{year}: {DECISION_TITLES[decision]}{target}",
        entity_id=result.id,
        entity_label=f"{month:02d}.{year}",
        payload={"decision": decision, "comment": result.decision_comment},
        year=year,
        month=month,
    )
    db.commit()
    db.refresh(result)
    return result
