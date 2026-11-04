"""Планирование: годовой план продаж по менеджерам.

Строка плана — клиент × товар × месяц и только количество: цены в плане продаж нет
(цены живут в матрице ценообразования и в закупках).
Прошедшие месяцы заморожены (см. app/services/plan_freeze.py).
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
    from app.models.countries import Country
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
    """Годовой план закупок сырья на основании годового плана продаж.

    Один план на год. Позиции берутся из финально согласованного годового плана
    продаж, закупщик вручную раскладывает их на сырьё. Снимок источника и его
    отпечаток позволяют показать, что план продаж пересмотрели после составления
    плана закупок.
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
    # Снимок утверждённого годового плана продаж: позиция × месяц × количество.
    source_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revision_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revision_requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="joined")
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id], lazy="joined")
    revision_requested_by: Mapped[User | None] = relationship(
        foreign_keys=[revision_requested_by_id], lazy="joined"
    )
    items: Mapped[list[PurchasePlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    source_events: Mapped[list[PurchasePlanSourceEvent]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PurchasePlanSourceEvent.acknowledged_at",
    )


class PurchasePlanItem(Base):
    """Строка плана закупок: потребность позиции закрывается сырьём.

    ``sales_product_id`` — позиция плана продаж, которую закрывает строка;
    ``product_id`` — закупаемое сырьё. Количество — годовое: по месяцам оно
    раскладывается расчётом (``services/purchase_need.py``) пропорционально
    продажам позиции, а месяц заказа сдвигается на срок доставки страны.

    ``alternative_of_id`` — строка-замена: другое сырьё (сорт, калибр) или та же
    позиция из другой страны, которая закрывает потребность основной строки,
    когда основного сырья не хватает. Своей потребности у альтернативы нет:
    её количество — план закупки, а её приходы идут в тот же котёл.
    """

    __tablename__ = "purchase_plan_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchase_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alternative_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("purchase_plan_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Основная строка, которую закрывает эта альтернатива",
    )
    sales_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Позиция годового плана продаж, которую закрывает строка",
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    country_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("countries.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Страна происхождения сырья: из неё берётся срок доставки",
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), nullable=False, default=Decimal("0"), comment="Годовое количество"
    )
    norm: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 4),
        nullable=True,
        comment="Норма расхода: единиц сырья на единицу позиции плана продаж",
    )
    price_rub: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    delivery_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, comment="Снимок срока доставки страны, дней"
    )
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[PurchasePlan] = relationship(back_populates="items", lazy="joined")
    sales_product: Mapped[Product] = relationship(foreign_keys=[sales_product_id], lazy="joined")
    product: Mapped[Product] = relationship(foreign_keys=[product_id], lazy="joined")
    country: Mapped[Country] = relationship(lazy="joined")


class PurchasePlanSourceEvent(Base):
    """Принятое к сведению изменение плана продаж.

    Хранит diff на момент подтверждения — чтобы директор по закупкам мог
    вернуться и посмотреть, что именно изменилось.
    """

    __tablename__ = "purchase_plan_source_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchase_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[PurchasePlan] = relationship(back_populates="source_events")
    acknowledged_by: Mapped[User | None] = relationship(lazy="joined")


# Статусы годового плана отдела продаж: не отправлен → на финальном согласовании →
# финально согласован / требует повторного согласования.
SALES_PLAN_APPROVAL_STATUSES = ("draft", "on_review", "approved", "revision")

SALES_PLAN_APPROVAL_STATUS_TITLES = {
    "draft": "Не отправлен",
    "on_review": "На финальном согласовании",
    "approved": "Финально согласован",
    "revision": "Требует повторного согласования",
}


class SalesPlanApproval(Base):
    """Годовой план отдела продаж: собирается из утверждённых планов менеджеров.

    Финальное согласование — за генеральным директором. Любое изменение плана
    менеджера снимает согласование: документ переходит в `revision`.
    """

    __tablename__ = "sales_plan_approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    submitted_by: Mapped[User | None] = relationship(foreign_keys=[submitted_by_id], lazy="joined")
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id], lazy="joined")


# Статусы корректировки утверждённого плана менеджера.
SALES_PLAN_CORRECTION_STATUSES = ("draft", "on_review", "approved", "rejected")

SALES_PLAN_CORRECTION_STATUS_TITLES = {
    "draft": "Черновик корректировки",
    "on_review": "Корректировка на утверждении",
    "approved": "Корректировка утверждена",
    "rejected": "Корректировка отклонена",
}


class SalesPlanCorrection(Base):
    """Предложение корректировки утверждённого плана менеджера.

    Хранит только изменения («клиент × товар × месяц → новое количество»), а не копию
    всего плана. Применяется коммерческим директором; после применения годовой план
    отдела требует повторного финального согласования.
    """

    __tablename__ = "sales_plan_corrections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sales_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    plan: Mapped[SalesPlan] = relationship(lazy="joined")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="joined")
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id], lazy="joined")
    items: Mapped[list[SalesPlanCorrectionItem]] = relationship(
        back_populates="correction", cascade="all, delete-orphan"
    )


class SalesPlanCorrectionItem(Base):
    """Изменение корректировки: новое количество; 0 — удалить строку плана."""

    __tablename__ = "sales_plan_correction_items"
    __table_args__ = (
        UniqueConstraint(
            "correction_id",
            "client_id",
            "product_id",
            "month",
            name="sales_plan_correction_item_client_product_month",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    correction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("sales_plan_corrections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False, default=Decimal("0"))
    current_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 3), nullable=True, comment="Количество в плане на момент предложения"
    )
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    correction: Mapped[SalesPlanCorrection] = relationship(back_populates="items")
    client: Mapped[Counterparty] = relationship(lazy="joined")
    product: Mapped[Product] = relationship(lazy="joined")
