"""Журнал действий: запись событий, служебные сообщения, прочитанность.

Каталог событий — единственное место, где указаны уровень и адресаты. Сервисы
домена зовут ``record(...)`` перед своим ``commit``: событие попадает в ту же
транзакцию, что и само изменение, и не может «отстать» от него.

На этом этапе служебные сообщения получает **только исполнительный директор**
и только по критическим событиям (``is_message``). Журнал он видит целиком,
остальные роли — свои действия.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditEventRead
from app.models.auth import ROLE_EXECUTIVE_DIRECTOR, ROLE_TITLES, User
from app.schemas.audit import AuditEventOut, MessagesOut

# Сколько строк отдаём по умолчанию и максимум за раз.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


# Очистку журнала предлагаем с марта: до этого прошлый год ещё «свежий».
CLEANUP_FROM_MONTH = 3


class AuditError(Exception):
    """Ошибка журнала: нет прав."""

    def __init__(self, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class EventSpec:
    """Описание события каталога."""

    title: str
    level: str
    entity_kind: str


# Каталог критических событий первого этапа.
CATALOG: dict[str, EventSpec] = {
    "sales_plan.approved": EventSpec("План продаж утверждён", "critical", "sales_plan"),
    "sales_plan.items_changed": EventSpec("Изменены строки плана продаж", "critical", "sales_plan"),
    "sales_plan.deleted": EventSpec("План продаж удалён", "critical", "sales_plan"),
    "correction.approved": EventSpec("Корректировка плана утверждена", "critical", "sales_plan"),
    "annual_plan.approved": EventSpec("Годовой план отдела согласован", "critical", "sales_plan"),
    "annual_plan.invalidated": EventSpec(
        "Согласование годового плана снято", "critical", "sales_plan"
    ),
    "month.closed": EventSpec("Месяц закрыт", "critical", "month"),
    "month.reopened": EventSpec("Месяц открыт заново", "critical", "month"),
    "month.decision_set": EventSpec("Принято решение месяца", "critical", "month"),
    "month.transfer_drafts_created": EventSpec(
        "Созданы черновики корректировок", "critical", "month"
    ),
    "purchase_plan.items_changed": EventSpec(
        "Изменены строки плана закупок", "critical", "purchase_plan"
    ),
    "purchase_plan.approved": EventSpec("План закупок утверждён", "critical", "purchase_plan"),
    "purchase_plan.reopened": EventSpec(
        "План закупок возвращён в работу", "critical", "purchase_plan"
    ),
    "batch.items_changed": EventSpec("Изменены позиции поступления", "critical", "batch"),
    "batch.customs_applied": EventSpec("Растаможка поступления", "critical", "batch"),
    "batch.deleted": EventSpec("Поступление удалено", "critical", "batch"),
    "product.created": EventSpec("Заведена номенклатура", "critical", "product"),
    "product.updated": EventSpec("Изменена номенклатура", "critical", "product"),
    "counterparty.created": EventSpec("Заведён контрагент", "critical", "counterparty"),
    "counterparty.updated": EventSpec("Изменён контрагент", "critical", "counterparty"),
    "country.updated": EventSpec("Изменена страна и срок доставки", "critical", "country"),
    "auth.login_failed": EventSpec("Неудачная попытка входа", "critical", "user"),
    "task.created": EventSpec("Поставлена задача", "info", "task"),
    "task.updated": EventSpec("Изменена задача", "info", "task"),
    "task.status_changed": EventSpec("Сменён статус задачи", "info", "task"),
    "task.report_added": EventSpec("Отчёт по задаче", "info", "task"),
    "task.done": EventSpec("Задача выполнена", "critical", "task"),
    "task.reopened": EventSpec("Задача возвращена в работу", "critical", "task"),
    "task.deleted": EventSpec("Задача удалена", "critical", "task"),
    "audit.cleanup_offered": EventSpec("Предложена очистка журнала", "critical", "audit"),
    "audit.cleanup_done": EventSpec("Журнал очищен", "critical", "audit"),
}

# Кому на этом этапе уходят служебные сообщения (позже матрица расширится).
MESSAGE_AUDIENCE: tuple[str, ...] = (ROLE_EXECUTIVE_DIRECTOR,)


def record(
    db: Session,
    *,
    actor: User | None,
    action: str,
    summary: str,
    entity_id: uuid.UUID | None = None,
    entity_label: str | None = None,
    payload: dict[str, Any] | None = None,
    year: int | None = None,
    month: int | None = None,
    actor_login: str | None = None,
) -> AuditEvent:
    """Записать событие в журнал. Коммит делает вызывающий сервис."""
    spec = CATALOG.get(action)
    if spec is None:
        raise AuditError(f"Неизвестное событие журнала: {action}", status_code=500)
    is_message = spec.level == "critical"
    event = AuditEvent(
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        action=action,
        level=spec.level,
        entity_kind=spec.entity_kind,
        entity_id=entity_id,
        entity_label=(entity_label or "")[:255] or None,
        summary=summary[:2000],
        payload=payload,
        year=year,
        month=month,
        is_message=is_message,
        audience=list(MESSAGE_AUDIENCE) if is_message else [],
    )
    if actor is None and actor_login:
        event.payload = {**(payload or {}), "login": actor_login}
    db.add(event)
    return event


def _to_out(event: AuditEvent, read: bool) -> AuditEventOut:
    actor = event.actor
    return AuditEventOut(
        id=event.id,
        created_at=event.created_at,
        action=event.action,
        action_title=CATALOG[event.action].title if event.action in CATALOG else event.action,
        level=event.level,
        entity_kind=event.entity_kind,
        entity_id=event.entity_id,
        entity_label=event.entity_label,
        summary=event.summary,
        actor_name=actor.full_name if actor else None,
        actor_role_title=ROLE_TITLES.get(event.actor_role or "", None),
        year=event.year,
        month=event.month,
        read=read,
        link=_link(event),
    )


def _link(event: AuditEvent) -> str | None:
    """Адрес объекта события: по нему журнал открывает нужное место."""
    kind = event.entity_kind
    if event.action.startswith("audit."):
        return "#/messages"
    if kind == "month" and event.year and event.month:
        return f"#/month/{event.year}/{event.month}"
    if event.action.startswith("annual_plan") and event.year:
        return f"#/annual-plan/{event.year}"
    if kind == "sales_plan" and event.year and event.entity_id:
        return f"#/sales-plan/{event.year}/{event.entity_id}"
    if kind == "purchase_plan" and event.year:
        return f"#/purchase-plan/{event.year}"
    if kind == "batch" and event.entity_id:
        return f"#/receipt/{event.entity_id}"
    if kind == "product" and event.entity_id:
        return f"#/nomenclature/{event.entity_id}"
    if kind == "counterparty" and event.entity_id:
        return f"#/counterparties/{event.entity_id}"
    if kind == "country" and event.entity_id:
        return f"#/countries/{event.entity_id}"
    if kind == "task" and event.entity_id:
        return f"#/tasks/{event.entity_id}"
    return None


def _limit(limit: int | None) -> int:
    return max(1, min(limit or DEFAULT_LIMIT, MAX_LIMIT))


def messages(
    db: Session,
    user: User,
    *,
    unread_only: bool = False,
    limit: int | None = None,
    before: datetime | None = None,
) -> MessagesOut:
    """Служебные сообщения пользователя: свежие сверху."""
    limit = _limit(limit)
    read_alias = select(AuditEventRead.event_id).where(AuditEventRead.user_id == user.id).subquery()
    statement = (
        select(AuditEvent, read_alias.c.event_id.is_not(None))
        .outerjoin(read_alias, read_alias.c.event_id == AuditEvent.id)
        .where(AuditEvent.is_message.is_(True))
        .where(AuditEvent.audience.contains([user.role]))
        .order_by(AuditEvent.seq.desc())
        .limit(limit)
    )
    if unread_only:
        statement = statement.where(read_alias.c.event_id.is_(None))
    if before is not None:
        statement = statement.where(AuditEvent.created_at < before)
    rows = [(event, bool(is_read)) for event, is_read in db.execute(statement).all()]
    return MessagesOut(
        rows=[_to_out(event, is_read) for event, is_read in rows],
        unread=unread_count(db, user),
        total=message_total(db, user),
    )


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    """Начало и конец календарного года в UTC."""
    return (
        datetime(year, 1, 1, tzinfo=UTC),
        datetime(year + 1, 1, 1, tzinfo=UTC),
    )


def cleanup_year_for(today: date) -> int | None:
    """За какой год предлагаем чистку: прошлый, начиная с марта."""
    if today.month < CLEANUP_FROM_MONTH:
        return None
    return today.year - 1


def cleanup_suggestion(
    db: Session, user: User, *, today: date | None = None
) -> dict[str, int] | None:
    """Сколько записей прошлого года есть и за какой это год."""
    target = cleanup_year_for(today or date.today())
    if target is None:
        return None
    start, end = _year_bounds(target)
    count = int(
        db.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.created_at >= start, AuditEvent.created_at < end)
        ).scalar_one()
    )
    if count == 0:
        return None
    return {"year": target, "events": count}


def maybe_offer_cleanup(db: Session, user: User, *, today: date | None = None) -> None:
    """Раз в месяц, начиная с марта, предлагать директору очистить журнал за прошлый год."""
    if user.role != ROLE_EXECUTIVE_DIRECTOR:
        return
    current = today or date.today()
    suggestion = cleanup_suggestion(db, user, today=current)
    if suggestion is None:
        return
    month_start = datetime(current.year, current.month, 1, tzinfo=UTC)
    offered = db.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == "audit.cleanup_offered",
            AuditEvent.created_at >= month_start,
        )
    ).scalar_one()
    if offered:
        return
    record(
        db,
        actor=None,
        action="audit.cleanup_offered",
        summary=(
            f"Журнал за {suggestion['year']} год: записей {suggestion['events']}. "
            "Можно очистить — старое хранится только для истории"
        ),
        entity_label=str(suggestion["year"]),
        payload=suggestion,
        year=suggestion["year"],
    )
    db.commit()


def cleanup_journal(db: Session, user: User, year: int) -> int:
    """Удалить записи журнала за календарный год. Только исполнительный директор."""
    if user.role != ROLE_EXECUTIVE_DIRECTOR:
        raise AuditError("Очистить журнал может только исполнительный директор")
    if year >= date.today().year:
        raise AuditError("Чистить можно только прошлые годы", status_code=400)
    start, end = _year_bounds(year)
    deleted = int(
        db.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.created_at >= start, AuditEvent.created_at < end)
        ).scalar_one()
    )
    if deleted == 0:
        raise AuditError(f"За {year} год записей нет", status_code=409)
    db.execute(
        delete(AuditEvent).where(AuditEvent.created_at >= start, AuditEvent.created_at < end)
    )
    record(
        db,
        actor=user,
        action="audit.cleanup_done",
        summary=f"Журнал за {year} год очищен: удалено записей {deleted}",
        entity_label=str(year),
        payload={"year": year, "deleted": deleted},
        year=year,
    )
    db.commit()
    return deleted


def message_total(db: Session, user: User) -> int:
    """Сколько служебных сообщений у пользователя всего (для «показано N из M»)."""
    statement = (
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.is_message.is_(True))
        .where(AuditEvent.audience.contains([user.role]))
    )
    return int(db.execute(statement).scalar_one())


def unread_count(db: Session, user: User) -> int:
    """Сколько служебных сообщений пользователь ещё не открывал."""
    read_alias = select(AuditEventRead.event_id).where(AuditEventRead.user_id == user.id).subquery()
    statement = (
        select(func.count())
        .select_from(AuditEvent)
        .outerjoin(read_alias, read_alias.c.event_id == AuditEvent.id)
        .where(AuditEvent.is_message.is_(True))
        .where(AuditEvent.audience.contains([user.role]))
        .where(read_alias.c.event_id.is_(None))
    )
    return int(db.execute(statement).scalar_one())


def mark_read(db: Session, user: User, ids: Sequence[uuid.UUID]) -> int:
    """Отметить сообщения прочитанными. Чужие и несуществующие пропускаем."""
    if not ids:
        return unread_count(db, user)
    visible = set(
        db.execute(
            select(AuditEvent.id).where(
                AuditEvent.id.in_(list(ids)),
                AuditEvent.is_message.is_(True),
                AuditEvent.audience.contains([user.role]),
            )
        )
        .scalars()
        .all()
    )
    already: set[uuid.UUID] = set()
    if visible:
        already = set(
            db.execute(
                select(AuditEventRead.event_id).where(
                    AuditEventRead.user_id == user.id,
                    AuditEventRead.event_id.in_(list(visible)),
                )
            )
            .scalars()
            .all()
        )
    for event_id in visible - already:
        db.add(AuditEventRead(event_id=event_id, user_id=user.id))
    db.commit()
    return unread_count(db, user)


def mark_all_read(db: Session, user: User) -> int:
    """Отметить все свои сообщения прочитанными."""
    read_alias = select(AuditEventRead.event_id).where(AuditEventRead.user_id == user.id).subquery()
    unread = (
        db.execute(
            select(AuditEvent.id)
            .outerjoin(read_alias, read_alias.c.event_id == AuditEvent.id)
            .where(AuditEvent.is_message.is_(True))
            .where(AuditEvent.audience.contains([user.role]))
            .where(read_alias.c.event_id.is_(None))
        )
        .scalars()
        .all()
    )
    for event_id in unread:
        db.add(AuditEventRead(event_id=event_id, user_id=user.id))
    db.commit()
    return unread_count(db, user)


def journal(
    db: Session,
    user: User,
    *,
    action: str | None = None,
    entity_kind: str | None = None,
    entity_id: uuid.UUID | None = None,
    limit: int | None = None,
    before: datetime | None = None,
) -> list[AuditEventOut]:
    """Журнал: исполнительный директор видит всё, остальные — свои действия."""
    limit = _limit(limit)
    statement = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
    if user.role != ROLE_EXECUTIVE_DIRECTOR:
        statement = statement.where(AuditEvent.actor_id == user.id)
    if action:
        statement = statement.where(AuditEvent.action == action)
    if entity_kind:
        statement = statement.where(AuditEvent.entity_kind == entity_kind)
    if entity_id:
        statement = statement.where(AuditEvent.entity_id == entity_id)
    if before is not None:
        statement = statement.where(AuditEvent.created_at < before)
    rows = db.execute(statement).scalars().all()
    if user.role != ROLE_EXECUTIVE_DIRECTOR:
        return [_to_out(event, True) for event in rows]
    reads = set(
        db.execute(
            select(AuditEventRead.event_id).where(
                AuditEventRead.user_id == user.id,
                AuditEventRead.event_id.in_([event.id for event in rows]),
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(event, event.id in reads) for event in rows]
