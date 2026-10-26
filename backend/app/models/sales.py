"""Факт продаж: месячная выгрузка 1С и сопоставление номенклатуры.

Только оперативный контур. Продажи приходят файлом 1С за месяц, а не заводятся
руками: одна строка — клиент × товар × месяц. Если позицию файла не удалось
опознать в справочнике, строка лежит в очереди (`SalesFactUnmatched`) и в итоги
не идёт, пока её не сопоставят; выбранное соответствие запоминается алиасом
(`ProductAlias`) для будущих месяцев.

Суммы в таблице спецификации 1С — «Сумма продажи в руб.», поэтому деньги храним
в Numeric без плавающей точки.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.counterparties import Counterparty
    from app.models.domain import ImportSession, Product


class SalesFact(Base):
    """Продажа за месяц по клиенту и товару: количество и сумма в рублях."""

    __tablename__ = "sales_facts"
    __table_args__ = (
        UniqueConstraint(
            "year",
            "month",
            "client_id",
            "product_id",
            name="sales_fact_month_client_product",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("counterparties.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), nullable=False, default=Decimal("0"), comment="Количество в единице товара"
    )
    amount_rub: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"), comment="Сумма продажи, ₽"
    )
    discount_rub: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"), comment="Сумма скидки, ₽"
    )
    import_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("import_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    client: Mapped[Counterparty] = relationship(lazy="joined")
    product: Mapped[Product] = relationship(lazy="joined")
    import_session: Mapped[ImportSession | None] = relationship()


class SalesFactUnmatched(Base):
    """Строка файла, которую не удалось опознать в справочнике номенклатуры.

    Хранится до ручного сопоставления: пока очередь не пуста, месяц нельзя закрыть.
    """

    __tablename__ = "sales_fact_unmatched"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    import_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("import_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("counterparties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False, default=Decimal("0"))
    amount_rub: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    client: Mapped[Counterparty | None] = relationship(lazy="joined")


class ProductAlias(Base):
    """Запомненное соответствие названия из выгрузки карточке номенклатуры."""

    __tablename__ = "product_aliases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped[Product] = relationship(lazy="joined")


# Причины отклонений: фиксированный список, меняется только решением продукта.
REASON_CODES = (
    "return",
    "quality",
    "supply_late",
    "no_stock",
    "price",
    "client_refused",
    "plan_error",
    "other",
)

REASON_TITLES = {
    "return": "Возврат клиента",
    "quality": "Качество продукции",
    "supply_late": "Товар не пришёл вовремя",
    "no_stock": "Нет товара на складе",
    "price": "Цена и условия",
    "client_refused": "Клиент отказался или сократил",
    "plan_error": "Ошибка планирования",
    "other": "Другое",
}


class DeviationReason(Base):
    """Причина отклонения по строке итогов: клиент × товар × месяц.

    Причина объясняет отклонение, но не меняет план и факт. Одна причина на ключ;
    автор и дата видны в карточке и попадут в снимок закрытого месяца.
    """

    __tablename__ = "deviation_reasons"
    __table_args__ = (
        UniqueConstraint(
            "year",
            "month",
            "client_id",
            "product_id",
            name="deviation_reason_month_client_product",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("counterparties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    author: Mapped[User | None] = relationship()


# Решения месяца: что руководство сделало с нереализованным объёмом.
DECISION_CODES = ("transfer_sales", "transfer_purchase", "accept")

DECISION_TITLES = {
    "transfer_sales": "Перенести в план продаж",
    "transfer_purchase": "Перенести в план закупок",
    "accept": "Принять как есть",
}

MONTH_STATUSES = ("open", "closed")


class MonthResult(Base):
    """Состояние месяца итогов: закрытие, решение и последний снимок.

    Строка заводится при первом закрытии или решении; пока её нет, месяц открыт.
    Снимок — JSON плана, факта, причин и решения на момент закрытия: он не
    пересчитывается задним числом, а каждая версия ещё и лежит в истории.
    """

    __tablename__ = "month_results"
    __table_args__ = (UniqueConstraint("year", "month", name="month_result_year_month"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    closed_by: Mapped[User | None] = relationship(foreign_keys=[closed_by_id])
    reopened_by: Mapped[User | None] = relationship(foreign_keys=[reopened_by_id])
    decision_by: Mapped[User | None] = relationship(foreign_keys=[decision_by_id])
    snapshots: Mapped[list[MonthResultSnapshot]] = relationship(
        back_populates="month_result", cascade="all, delete-orphan"
    )


class MonthResultSnapshot(Base):
    """История закрытий месяца: снимок каждого закрытия остаётся навсегда."""

    __tablename__ = "month_result_snapshots"
    __table_args__ = (
        UniqueConstraint("month_result_id", "version", name="month_snapshot_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    month_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("month_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    month_result: Mapped[MonthResult] = relationship(back_populates="snapshots")
