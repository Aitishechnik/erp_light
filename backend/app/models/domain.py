"""Доменные модели erp_lite.

Только оперативный контур: партии, строки партий, расходы партии, снимки остатков.
Бухгалтерский слой (счета, проводки, курсовые разницы) сознательно отсутствует —
это зона 1С.

Деньги — только Numeric/Decimal. Числа с плавающей точкой в финансовых полях запрещены.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
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

# Виды номенклатуры: соответствуют файлам выгрузки из 1С.
PRODUCT_KINDS = ("goods", "material", "raw", "finished")

PRODUCT_KIND_TITLES = {
    "goods": "Товар",
    "material": "Материалы",
    "raw": "Сырьё",
    "finished": "Готовая продукция",
}

# Типы партий.
BATCH_TYPES = ("purchase", "production")

# Источник записи: выгрузка из 1С или ручной ввод.
SOURCES = ("1c", "manual")


class Product(Base):
    """Номенклатура: товар, материал, сырьё или готовая продукция.

    Код — код из 1С, поэтому выгрузки обновляют позиции по нему, а не создают дубли.
    """

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="goods", index=True)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="шт")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    batch_items: Mapped[list[BatchItem]] = relationship(back_populates="product")


class Batch(Base):
    """Партия: единица оперативного учёта себестоимости."""

    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    batch_type: Mapped[str] = mapped_column(String(20), nullable=False, default="purchase")
    batch_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True, index=True
    )
    supplier: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Наименование поставщика на момент поступления"
    )
    total_invoice_value: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="Общая инвойсная стоимость партии в валюте контракта",
    )
    current_exchange_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 6),
        nullable=True,
        comment="Курс валюты контракта к рублю на дату оценки (для RUB = 1)",
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list[BatchItem]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    expenses: Mapped[list[BatchExpense]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class BatchItem(Base):
    """Строка партии: товар, количество и инвойсная стоимость в валюте."""

    __tablename__ = "batch_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False, default=Decimal("0"))
    total_invoice_currency: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="Инвойсная стоимость строки в валюте контракта",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    batch: Mapped[Batch] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="batch_items", lazy="joined")
    snapshots: Mapped[list[StockSnapshot]] = relationship(
        back_populates="batch_item", cascade="all, delete-orphan"
    )


class BatchExpense(Base):
    """Доп. расход по партии в рублях (входит в себестоимость)."""

    __tablename__ = "batch_expenses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    batch: Mapped[Batch] = relationship(back_populates="expenses")


class StockSnapshot(Base):
    """Актуальный остаток по строке партии на дату (из отчёта «Остатки»)."""

    __tablename__ = "stock_snapshots"
    __table_args__ = (
        UniqueConstraint("batch_item_id", "snapshot_date", name="batch_item_snapshot_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("batch_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False, default=Decimal("0"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="1c")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    batch_item: Mapped[BatchItem] = relationship(back_populates="snapshots")


class ImportSession(Base):
    """Журнал загрузки файлов выгрузки из 1С."""

    __tablename__ = "import_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
