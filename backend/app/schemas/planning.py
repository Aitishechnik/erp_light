"""Схемы плана продаж. Количество — Decimal, в JSON уходит строкой.

Цен в плане продаж нет: планируем объём, деньги считаются в других разделах.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SalesPlanItemIn(BaseModel):
    client_id: uuid.UUID = Field(description="Клиент, по которому планируется продажа")
    product_id: uuid.UUID
    month: int = Field(ge=1, le=12)
    quantity: Decimal = Field(ge=0, description="Количество на месяц")
    notes: str | None = Field(default=None, max_length=255)


class SalesPlanCreate(BaseModel):
    year: int = Field(ge=2020, le=2100)
    manager_id: uuid.UUID | None = Field(
        default=None, description="Обязателен, когда план создаёт коммерческий директор"
    )
    notes: str | None = None


class SalesPlanItemsIn(BaseModel):
    items: list[SalesPlanItemIn] = []


class SalesPlanRejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class SalesPlanItemOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str
    product_id: uuid.UUID
    product_code: str
    product_name: str
    product_kind: str
    unit: str
    month: int
    quantity: Decimal
    notes: str | None


class SalesPlanOut(BaseModel):
    id: uuid.UUID
    year: int
    manager_id: uuid.UUID
    manager_name: str
    created_by_name: str
    status: str
    status_title: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
    editable_months: list[int] = Field(description="Месяцы, которые сейчас можно менять")
    items: list[SalesPlanItemOut]


# --- План закупок сырья ---------------------------------------------------


class PurchasePlanItemIn(BaseModel):
    """Строка плана закупок: сырьё, страна и годовое количество.

    ``id`` приходит у уже сохранённой строки: по нему сервер обновляет её на месте,
    чтобы ссылки поступлений не терялись при каждом сохранении плана.
    """

    id: uuid.UUID | None = Field(default=None, description="Строка плана при сохранении")
    sales_product_id: uuid.UUID = Field(description="Позиция годового плана продаж")
    product_id: uuid.UUID = Field(description="Закупаемое сырьё")
    country_id: uuid.UUID = Field(description="Страна происхождения: срок доставки")
    quantity: Decimal = Field(gt=0, description="Годовое количество")
    price_rub: Decimal | None = Field(default=None, ge=0, description="Цена за единицу, ₽")
    supplier_id: uuid.UUID | None = Field(default=None, description="Поставщик из справочника")
    notes: str | None = Field(default=None, max_length=255)


class PurchasePlanCreate(BaseModel):
    year: int = Field(ge=2020, le=2100)
    notes: str | None = None


class PurchasePlanItemsIn(BaseModel):
    items: list[PurchasePlanItemIn] = []


class PurchasePlanRejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class PurchasePlanScheduleEntryOut(BaseModel):
    """Месяц плана: потребность, её покрытие и что ещё нужно докупить."""

    month: int
    quantity: Decimal = Field(description="Потребность месяца, в единицах сырья")
    covered: Decimal = Field(
        default=Decimal("0"),
        description="Перекрыто остатком на складе и приходами этого и прошлых месяцев",
    )
    remaining: Decimal = Field(
        default=Decimal("0"), description="Ещё нужно докупить: потребность минус покрытие"
    )
    carry: Decimal = Field(
        default=Decimal("0"), description="Остаток после месяца — переходит на следующий"
    )
    share: Decimal = Field(default=Decimal("0"), description="Перекрыто, %: не больше 100")
    order_year: int
    order_month: int
    overdue: bool = Field(description="Срок заказа уже прошёл")


class PurchasePlanMonthOut(BaseModel):
    month: int
    quantity: Decimal


class PurchasePlanItemOut(BaseModel):
    id: uuid.UUID
    sales_product_id: uuid.UUID
    sales_product_name: str
    product_id: uuid.UUID
    product_code: str
    product_name: str
    product_kind: str
    unit: str
    country_id: uuid.UUID
    country_name: str
    delivery_days: int
    quantity: Decimal
    price_rub: Decimal | None
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    notes: str | None
    fact_quantity: Decimal = Field(
        default=Decimal("0"), description="Поступило по связанным поступлениям, в единицах сырья"
    )
    fact_share: Decimal = Field(
        default=Decimal("0"), description="Исполнение, %: факт ÷ годовое количество × 100"
    )
    fact_months: list[PurchasePlanMonthOut] = Field(
        default_factory=list,
        description="Поступило по месяцам (месяц прихода партии): только месяцы с фактом",
    )
    coverage_months: list[PurchasePlanMonthOut] = Field(
        default_factory=list,
        description="Приходы, которые участвуют в покрытии: пришедшие после снимка остатков",
    )
    stock_quantity: Decimal = Field(
        default=Decimal("0"), description="Остаток сырья на складе по последнему отчёту"
    )
    stock_date: date | None = Field(default=None, description="Дата снимка остатков")
    product_stock_quantity: Decimal = Field(
        default=Decimal("0"),
        description="Остаток готовой продукции на складе: закрывает часть потребности",
    )
    product_stock_date: date | None = Field(
        default=None, description="Дата снимка остатков готовой продукции"
    )
    product_stock_raw: Decimal = Field(
        default=Decimal("0"),
        description="Сколько сырья не нужно заказывать: остаток готовой продукции в сырье",
    )
    carry_forward: Decimal = Field(
        default=Decimal("0"),
        description="Излишек после последнего месяца — переходит на следующий год",
    )
    schedule: list[PurchasePlanScheduleEntryOut]


class PurchasePlanPositionOut(BaseModel):
    """Позиция годового плана продаж и её ручная разузловка на сырьё."""

    product_id: uuid.UUID
    code: str
    name: str
    unit: str
    total: Decimal
    months: list[PurchasePlanMonthOut]
    decomposed: bool
    status: str = Field(description="ok | added | removed | orphan")
    changed: bool


class PurchasePlanChangeOut(BaseModel):
    """Одно расхождение снимка и текущего плана продаж."""

    product_id: uuid.UUID
    code: str
    name: str
    unit: str
    month: int
    was: Decimal | None
    now: Decimal | None
    kind: str = Field(description="added | removed | changed")


class PurchasePlanSourceEventOut(BaseModel):
    id: uuid.UUID
    acknowledged_at: datetime
    acknowledged_by_name: str | None
    changes: list[PurchasePlanChangeOut]


class PurchasePlanSourceOut(BaseModel):
    """Состояние источника: финально согласованный годовой план продаж."""

    state: str = Field(description="ok | changed | revision | missing | no_snapshot")
    title: str
    annual_status_title: str | None
    annual_approved_at: datetime | None
    snapshot_at: datetime | None
    acknowledged_at: datetime | None
    changes: list[PurchasePlanChangeOut]
    history: list[PurchasePlanSourceEventOut]
    revision_requested_at: datetime | None
    revision_requested_by_name: str | None


class PurchasePlanOut(BaseModel):
    id: uuid.UUID
    year: int
    status: str
    status_title: str
    created_by_name: str
    approved_by_name: str | None
    approved_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    editable_months: list[int] = Field(description="Месяцы, которые сейчас можно менять")
    source: PurchasePlanSourceOut
    positions: list[PurchasePlanPositionOut]
    items: list[PurchasePlanItemOut]


# --- Годовой план отдела продаж и корректировки --------------------------


class AnnualSalesPlanManagerOut(BaseModel):
    manager_id: uuid.UUID
    manager_name: str
    plan_id: uuid.UUID | None
    plan_status: str | None
    plan_status_title: str | None
    approved: bool
    positions: int
    clients: int


class AnnualSalesPlanItemOut(BaseModel):
    manager_id: uuid.UUID
    manager_name: str
    client_id: uuid.UUID
    client_name: str
    product_id: uuid.UUID
    product_code: str
    product_name: str
    unit: str
    month: int
    quantity: Decimal


class AnnualSalesPlanOut(BaseModel):
    year: int
    status: str
    status_title: str
    submitted_by_name: str | None
    submitted_at: datetime | None
    approved_by_name: str | None
    approved_at: datetime | None
    notes: str | None
    is_stale: bool
    all_approved: bool
    missing_managers: list[str]
    managers: list[AnnualSalesPlanManagerOut]
    items: list[AnnualSalesPlanItemOut]


class AnnualSalesPlanRejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class SalesPlanCorrectionItemIn(BaseModel):
    client_id: uuid.UUID
    product_id: uuid.UUID
    month: int = Field(ge=1, le=12)
    quantity: Decimal = Field(ge=0, description="Новое количество; 0 — удалить строку")
    notes: str | None = Field(default=None, max_length=255)


class SalesPlanCorrectionCreate(BaseModel):
    plan_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=500)


class SalesPlanCorrectionItemsIn(BaseModel):
    items: list[SalesPlanCorrectionItemIn] = []


class SalesPlanCorrectionRejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class SalesPlanCorrectionItemOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str
    product_id: uuid.UUID
    product_code: str
    product_name: str
    unit: str
    month: int
    quantity: Decimal
    current_quantity: Decimal
    notes: str | None


class SalesPlanCorrectionOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    status: str
    status_title: str
    created_by_name: str
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    reason: str | None
    review_reason: str | None
    created_at: datetime
    updated_at: datetime
    annual_needs_reapproval: bool = Field(
        description="Годовой план отдела всё ещё требует повторного согласования"
    )
    items: list[SalesPlanCorrectionItemOut]
