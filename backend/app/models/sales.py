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
from typing import TYPE_CHECKING

from sqlalchemy import (
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
