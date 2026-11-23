"""Помесячный план продаж: пересмотр месячного объёма по менеджеру.

Годовой план задаёт базу. Каждый месяц менеджер пересматривает свой месяц в окне
с 23-го числа предыдущего месяца по его последний день: меняет количество, обнуляет
позиции и добавляет новые. Изменение цифры без причины не сохраняется.

Помесячный план — отдельный слой: годовой план и его согласование он не меняет.
Если месяц не трогали, помесячного плана нет, и в сравнении месяц равен годовому.
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
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.counterparties import Counterparty
    from app.models.domain import Product

# Черновик — правки в окне; утверждён — зафиксирован и идёт в сравнение.
MONTHLY_PLAN_STATUSES = ("draft", "approved")

MONTHLY_PLAN_STATUS_TITLES = {
    "draft": "Черновик",
    "approved": "Утверждён",
}

# События истории: правка строки, утверждение, автоутверждение.
MONTHLY_PLAN_EVENT_TITLES = {
    "edit": "Правка строки",
    "approve": "План утверждён",
    "auto_approve": "Утверждён автоматически",
}


class MonthlySalesPlan(Base):
    """Помесячный план одного менеджера: один документ на год, месяц и менеджера."""

    __tablename__ = "monthly_sales_plans"
    __table_args__ = (
        UniqueConstraint(
            "year",
            "month",
            "manager_id",
            name="monthly_sales_plan_year_month_manager",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    manager_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    manager: Mapped[User] = relationship(foreign_keys=[manager_id], lazy="joined")
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id], lazy="joined")
    items: Mapped[list[MonthlySalesPlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    events: Mapped[list[MonthlySalesPlanEvent]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="MonthlySalesPlanEvent.created_at",
    )


class MonthlySalesPlanItem(Base):
    """Строка месячного плана: клиент × товар, количество и причина изменения.

    ``annual_quantity`` — количество из годового плана на момент открытия окна.
    Для новой позиции (которой не было в годовом плане) оно равно нулю.
    Строка с нулевым количеством остаётся в плане: так в сравнении видно, что
    позицию вывели, а не потеряли.
    """

    __tablename__ = "monthly_sales_plan_items"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "client_id",
            "product_id",
            name="monthly_sales_plan_item_client_product",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("monthly_sales_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    annual_quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3),
        nullable=False,
        default=Decimal("0"),
        comment="Количество в годовом плане на момент открытия окна",
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False, default=Decimal("0"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    plan: Mapped[MonthlySalesPlan] = relationship(back_populates="items")
    client: Mapped[Counterparty] = relationship(lazy="joined")
    product: Mapped[Product] = relationship(lazy="joined")
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id], lazy="joined")


class MonthlySalesPlanEvent(Base):
    """История пересмотра: кто, когда, какую строку и почему изменил."""

    __tablename__ = "monthly_sales_plan_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("monthly_sales_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    old_quantity: Mapped[Decimal | None] = mapped_column(Numeric(15, 3), nullable=True)
    new_quantity: Mapped[Decimal | None] = mapped_column(Numeric(15, 3), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[MonthlySalesPlan] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id], lazy="joined")
    client: Mapped[Counterparty | None] = relationship(lazy="joined")
    product: Mapped[Product | None] = relationship(lazy="joined")
