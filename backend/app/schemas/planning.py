"""Схемы плана продаж. Количество — Decimal, в JSON уходит строкой.

Цен в плане продаж нет: планируем объём, деньги считаются в других разделах.
"""

from __future__ import annotations

import uuid
from datetime import datetime
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
    alternative_of_id: uuid.UUID | None = Field(
        default=None, description="Основная строка, если это альтернативное сырьё"
    )
    sales_product_id: uuid.UUID = Field(description="Позиция годового плана продаж")
    product_id: uuid.UUID = Field(description="Закупаемое сырьё")
    country_id: uuid.UUID = Field(description="Страна происхождения: срок доставки")
    quantity: Decimal = Field(
        gt=0, le=Decimal("999999999999.999"), description="Годовое количество"
    )
    norm: Decimal | None = Field(
        default=None,
        gt=0,
        le=Decimal("999999.9999"),
        description="Норма расхода: единиц сырья на единицу позиции плана продаж",
    )
    price_rub: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("9999999999999.99"),
        description="Цена за единицу, ₽",
    )
    notes: str | None = Field(default=None, max_length=255)


class PurchasePlanCreate(BaseModel):
    year: int = Field(ge=2020, le=2100)
    notes: str | None = None


class PurchasePlanItemsIn(BaseModel):
    items: list[PurchasePlanItemIn] = []
    version: datetime | None = Field(
        default=None,
        description="updated_at плана, который видел клиент: защита от потери правок",
    )


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
    alternative_of_id: uuid.UUID | None = None
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
    norm: Decimal | None = Field(
        default=None, description="Норма расхода: единиц сырья на единицу позиции"
    )
    need_quantity: Decimal = Field(
        default=Decimal("0"), description="Потребность за год по норме, в единицах сырья"
    )
    need_months: list[PurchasePlanMonthOut] = Field(
        default_factory=list, description="Потребность по месяцам по норме"
    )
    plan_gap: Decimal = Field(
        default=Decimal("0"), description="Запас (+) или дефицит (−): план закупки − потребность"
    )
    price_rub: Decimal | None
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
    used_quantity: Decimal = Field(
        default=Decimal("0"),
        description="Альтернатива: сколько её прихода ушло на покрытие основной потребности",
    )
    used_months: list[PurchasePlanMonthOut] = Field(
        default_factory=list,
        description="Альтернатива: покрытие по месяцам, только месяцы с расходом",
    )
    carry_forward: Decimal = Field(
        default=Decimal("0"),
        description="Излишек после последнего месяца — переходит на следующий год",
    )
    carryover: Decimal = Field(
        default=Decimal("0"),
        description="Остаток сырья на конец последнего закрытого месяца: куплено, но не продано",
    )
    carryover_month: int | None = Field(
        default=None, description="Месяц, на конец которого посчитан остаток"
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
    fact_months: list[PurchasePlanMonthOut] = Field(
        default_factory=list,
        description="Продажи закрытых месяцев по факту: подменяют план в покрытии",
    )
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


class PurchasePlanSignalLineOut(BaseModel):
    """Строка истории изменений: было → стало по конкретному сырью."""

    sales_product: str
    product: str
    unit: str
    norm: Decimal | None = None
    plan_units: Decimal
    fact_units: Decimal
    units_delta: Decimal
    was_kg: Decimal | None = None
    now_kg: Decimal | None = None
    delta_kg: Decimal | None = None
    alternative: bool = False


class PurchasePlanSignalOut(BaseModel):
    """Одно изменение плана закупок: месяц, причина, автор и строки."""

    id: uuid.UUID
    created_at: datetime
    month: int | None = None
    reason: str | None = None
    actor_name: str | None = None
    lines: list[PurchasePlanSignalLineOut]


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
    closed_months: list[int] = Field(
        default_factory=list, description="Закрытые месяцы года: потребность считается по факту"
    )
    source: PurchasePlanSourceOut
    positions: list[PurchasePlanPositionOut]
    items: list[PurchasePlanItemOut]
    signals: list[PurchasePlanSignalOut] = Field(
        default_factory=list, description="История изменений: было → стало"
    )


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
