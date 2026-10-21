"""Планирование: годовой план продаж по менеджерам.

Строка плана — клиент × товар × месяц и только количество: цены в плане продаж нет
(цены живут в матрице ценообразования и в закупках).
Прошедшие месяцы заморожены (см. app/services/plan_freeze.py).
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

# Статусы плана продаж: черновик → заполняется → на проверке → утверждён.
SALES_PLAN_STATUSES = ("draft", "filling", "on_review", "approved")

SALES_PLAN_STATUS_TITLES = {
    "draft": "Черновик",
    "filling": "Заполняется",
    "on_review": "На проверке",
    "approved": "Утверждён",
}


class SalesPlan(Base):
    """Годовой план продаж одного менеджера (один план на год и менеджера)."""

    __tablename__ = "sales_plans"
    __table_args__ = (UniqueConstraint("year", "manager_id", name="sales_plan_year_manager"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    manager_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    manager: Mapped[User] = relationship(foreign_keys=[manager_id], lazy="joined")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="joined")
    items: Mapped[list[SalesPlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class SalesPlanItem(Base):
    """Строка плана: товар, месяц, количество и цена за единицу."""

    __tablename__ = "sales_plan_items"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "client_id",
            "product_id",
            "month",
            name="sales_plan_item_client_product_month",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sales_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Клиент плана — контрагент с признаком «покупатель» (client_id оставлен
    # ради совместимости с уже согласованным API плана продаж).
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False, default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[SalesPlan] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")
    client: Mapped[Counterparty] = relationship(lazy="joined")


# Статусы плана закупок сырья: черновик → на проверке → утверждён.
PURCHASE_PLAN_STATUSES = ("draft", "on_review", "approved")

PURCHASE_PLAN_STATUS_TITLES = {
    "draft": "Черновик",
    "on_review": "На проверке",
    "approved": "Утверждён",
}


class PurchasePlan(Base):
    """Годовой план закупок сырья.

    Один план на год, ведётся вручную: строки не связаны со строками плана продаж.
    Утверждённый план продаж остаётся бизнес-контекстом, а не источником расчёта.
    """

    __tablename__ = "purchase_plans"
    __table_args__ = (UniqueConstraint("year", name="purchase_plan_year"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="joined")
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id], lazy="joined")
    items: Mapped[list[PurchasePlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PurchasePlanItem(Base):
    """Строка плана закупок сырья: сырьё × месяц, цена в рублях.

    Один товар и месяц могут встречаться несколько раз — например, два поставщика
    с разными ценами и сроками. Месяц заказа считается от срока логистики.
    """

    __tablename__ = "purchase_plan_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchase_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False, default=Decimal("0"))
    price_rub: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True, index=True
    )
    delivery_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    order_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[PurchasePlan] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")
    supplier: Mapped[Counterparty | None] = relationship(lazy="joined")
