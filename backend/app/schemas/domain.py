"""Pydantic-схемы API. Деньги — Decimal (в JSON уходят строкой, без потери точности)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    kind: str
    unit: str
    source: str
    is_active: bool


class ProductIn(BaseModel):
    """Ручное заведение номенклатуры."""

    code: str = Field(min_length=1, max_length=64, description="Код (артикул)")
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="goods", description="goods — товар, material — материал")
    unit: str = Field(default="шт", min_length=1, max_length=16)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    is_active: bool | None = None


class BatchExpenseCreate(BaseModel):
    """Общий расход на партию: название, валюта (только руб./usd) и сумма."""

    description: str = ""
    currency: Literal["RUB", "USD"] = Field(
        default="RUB", description="Валюта расхода: только RUB или USD"
    )
    amount_currency: Decimal = Field(ge=0, description="Сумма расхода в его валюте")


class BatchItemCreate(BaseModel):
    """Строка партии: товар, количество, цена за единицу и надбавки."""

    id: uuid.UUID | None = Field(
        default=None,
        description="Строка партии: по ней находится ссылка на план у растаможенной партии",
    )
    product_code: str = Field(min_length=1, max_length=64)
    product_name: str | None = None
    product_kind: str = "goods"
    unit: str = "шт"
    quantity: Decimal = Field(gt=0)
    unit_price_currency: Decimal = Field(
        default=Decimal("0"), ge=0, description="Стоимость единицы в валюте партии"
    )
    duty_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, description="Пошлина, %")
    vat_percent: Decimal = Field(default=Decimal("22"), ge=0, le=100, description="НДС, %")
    risk_unit_currency: Decimal = Field(
        default=Decimal("0"), ge=0, description="Risk за единицу в валюте партии"
    )
    purchase_plan_item_id: uuid.UUID | None = Field(
        default=None,
        description="Строка плана закупок, по которой пришёл товар; пусто — закупка без плана",
    )


class BatchPaymentCreate(BaseModel):
    """Валютный платёж: закрывает инвойс или Risk, курс фиксируется вручную."""

    payment_date: date
    amount_currency: Decimal = Field(gt=0)
    exchange_rate: Decimal = Field(gt=0, description="Курс платежа, фиксируется навсегда")
    category: Literal["invoice", "risk"] = Field(
        default="invoice", description="Какой валютный долг закрывает платёж"
    )
    comment: str | None = Field(default=None, max_length=255)


class BatchCreate(BaseModel):
    """Поступление партии: шапка, строки, общие расходы и валютные платежи.

    Поступления создаются только выгрузкой 1С; схема используется правкой карточки.
    Строк может не быть только у черновика из выгрузки — правило проверяет API.
    """

    batch_number: str = Field(min_length=1, max_length=100)
    batch_date: date
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    supplier_id: uuid.UUID | None = Field(default=None, description="Поставщик из справочника")
    supplier: str | None = Field(
        default=None, description="Наименование, если поставщик не из справочника"
    )
    current_exchange_rate: Decimal | None = Field(
        default=None, gt=0, description="Если не указан, берётся курс ЦБ на дату"
    )
    auto_rate: bool = Field(default=True, description="Разрешить запрос курса с сайта ЦБ")
    comment: str | None = None
    items: list[BatchItemCreate] = Field(default_factory=list)
    payments: list[BatchPaymentCreate] = Field(
        default=[], description="Валютные платежи по инвойсу и по Risk"
    )
    expenses: list[BatchExpenseCreate] = Field(
        default=[], description="Общие расходы на партию (руб. или usd)"
    )


class BatchCustomsIn(BaseModel):
    """Растаможка: дата, курс фиксации и (необязательно) правка итогов вручную.

    Итоги считаются по процентам строк и курсу; если пришла своя сумма — она
    распределяется по строкам, а не подменяет расчёт процентов.
    """

    customs_date: date = Field(description="Дата таможенной очистки (не дата прихода)")
    rate: Decimal = Field(gt=0, description="Курс на дату растаможки, фиксируется навсегда")
    duty_rub: Decimal | None = Field(
        default=None, ge=0, description="Пошлина, ₽: пусто — считать по процентам строк"
    )
    vat_rub: Decimal | None = Field(
        default=None, ge=0, description="НДС, ₽: пусто — считать по процентам строк"
    )


class BatchPaymentOut(BaseModel):
    id: uuid.UUID
    payment_date: date
    amount_currency: Decimal
    exchange_rate: Decimal
    amount_rub: Decimal
    category: str
    comment: str | None


class BatchExpenseOut(BaseModel):
    id: uuid.UUID
    description: str
    currency: str
    amount_currency: Decimal
    amount_rub: Decimal = Field(description="Сумма в рублях: для usd — по курсу ЦБ на сегодня")


class BatchFinanceOut(BaseModel):
    """Итог партии: курсы категорий, расходы, пошлины и себестоимость."""

    invoice_total_currency: Decimal
    risk_total_currency: Decimal
    exchange_rate: Decimal = Field(description="Курс ЦБ, по которому оценены незакрытые остатки")
    rate_date: date | None = Field(default=None, description="Дата курса ЦБ")
    rate_updated_at: datetime | None = Field(default=None, description="Когда курс обновлялся")
    invoice_paid_currency: Decimal
    invoice_paid_rub: Decimal
    invoice_remaining_currency: Decimal
    invoice_rate: Decimal = Field(description="Фактический курс инвойса: платежи + остаток по ЦБ")
    risk_paid_currency: Decimal
    risk_paid_rub: Decimal
    risk_remaining_currency: Decimal
    risk_rate: Decimal = Field(description="Фактический курс Risk")
    planned_invoice_currency: Decimal = Field(default=Decimal("0"))
    planned_invoice_rub: Decimal = Field(default=Decimal("0"))
    planned_risk_currency: Decimal = Field(default=Decimal("0"))
    planned_risk_rub: Decimal = Field(default=Decimal("0"))
    expenses_rub: Decimal = Field(default=Decimal("0"), description="Общие расходы, ₽")
    duty_rub: Decimal = Field(default=Decimal("0"), description="Пошлина по строкам, ₽")
    vat_rub: Decimal = Field(default=Decimal("0"), description="НДС по строкам, ₽")
    average_rate: Decimal = Field(
        default=Decimal("0"),
        description="Средний курс партии по инвойсу и Risk — виден в списке поступлений",
    )
    final_cost_rub: Decimal


class BatchItemOut(BaseModel):
    id: uuid.UUID
    product_code: str
    product_name: str
    product_kind: str
    unit: str
    quantity: Decimal
    unit_price_currency: Decimal
    duty_percent: Decimal
    vat_percent: Decimal
    risk_unit_currency: Decimal
    duty_fixed_rub: Decimal | None = Field(
        default=None, description="Пошлина строки, ₽: фикс после растаможки, иначе пусто"
    )
    vat_fixed_rub: Decimal | None = Field(
        default=None, description="НДС строки, ₽: фикс после растаможки, иначе пусто"
    )
    purchase_plan_item_id: uuid.UUID | None = Field(
        default=None, description="Строка плана закупок; пусто — закупка без плана"
    )
    purchase_plan_label: str | None = Field(
        default=None, description="Подпись строки плана: «2026 · Китай · поставщик»"
    )
    invoice_currency: Decimal
    risk_currency: Decimal
    duty_rub: Decimal
    vat_rub: Decimal
    risk_rub: Decimal
    expenses_rub: Decimal
    item_total_rub: Decimal
    unit_cost: Decimal
    quantity_on_hand: Decimal


class BatchOut(BaseModel):
    id: uuid.UUID
    batch_number: str
    batch_type: str
    batch_date: date
    currency: str
    supplier_id: uuid.UUID | None
    supplier: str | None
    source: str
    comment: str | None
    created_at: datetime
    customs_date: date | None = Field(
        default=None, description="Дата растаможки; пусто — партия не растаможена"
    )
    customs_rate: Decimal | None = Field(
        default=None, description="Курс, по которому зафиксированы пошлина и НДС"
    )
    finance: BatchFinanceOut
    payments: list[BatchPaymentOut]
    expenses: list[BatchExpenseOut]
    items: list[BatchItemOut]


class StockRowOut(BaseModel):
    batch_item_id: uuid.UUID
    batch_number: str
    batch_date: date
    product_code: str
    product_name: str
    product_kind: str
    unit: str
    quantity_on_hand: Decimal
    unit_cost: Decimal
    value_rub: Decimal
    snapshot_date: date | None
