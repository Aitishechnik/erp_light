"""Оперативная себестоимость партии.

Формула согласована с продукт-менеджером и описана в
[`docs/data-contract-receipts.md`](../../../docs/data-contract-receipts.md) §3:

    инвойс$      = Σ (стоимость за ед. × кол-во)
    risk$        = Σ (risk за ед. × кол-во)
    пошлина$     = стоимость за ед. × пошлина %
    НДС$         = (стоимость за ед. + пошлина$) × НДС %
    остаток кат. = max(0, сумма категории$ − оплачено по категории$)
    курс кат.    = (Σ платёж × курс платежа + остаток × курс ЦБ) ÷ сумма категории$
    цена за ед.₽ = (стоимость за ед. + пошлина$ + НДС$) × курс инвойса
                   + risk за ед. × курс risk
                   + доля общих расходов на единицу
    сумма строки = цена за ед.₽ × кол-во

Что сохранено из формулы custom_erp (`erp_v_2`): незакрытая часть валютного долга
оценивается по текущему курсу ЦБ и потому переоценивается, а курсы уже сделанных
платежей зафиксированы в платежах и не меняются никогда.

Что НЕ перенесено (осознанно): бухгалтерский слой — счета, проводки, курсовые
разницы по ПБУ. Это зона 1С.

Курс для незакрытой части приходит снаружи (последний доступный курс ЦБ), общие
расходы — уже в рублях: расход в валюте пересчитывается по курсу ЦБ на текущий день
в `batch_service`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.models.domain import Batch, BatchExpense, BatchPayment

ZERO = Decimal("0.00")
ONE = Decimal("1")
CENT = Decimal("0.01")
MICRO = Decimal("0.000001")
HUNDRED = Decimal("100")

#: Категории валютных платежей: инвойс и рисковая надбавка закрываются отдельно.
CATEGORY_INVOICE = "invoice"
CATEGORY_RISK = "risk"


def q2(value: Decimal) -> Decimal:
    """Округление денег до копейки (HALF_UP), как в custom_erp."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def q6(value: Decimal) -> Decimal:
    """Округление курса до шести знаков — как хранится курс платежа."""
    return value.quantize(MICRO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ItemInput:
    """Строка партии для расчёта: цена, количество и надбавки."""

    unit_price_currency: Decimal = ZERO
    quantity: Decimal = ZERO
    duty_percent: Decimal = ZERO
    vat_percent: Decimal = ZERO
    risk_unit_currency: Decimal = ZERO
    duty_fixed_rub: Decimal | None = None
    vat_fixed_rub: Decimal | None = None

    @property
    def is_customs_cleared(self) -> bool:
        """Растаможена ли строка: пошлина и НДС пришли фиксом в рублях."""
        return self.duty_fixed_rub is not None and self.vat_fixed_rub is not None

    @property
    def invoice_currency(self) -> Decimal:
        """Инвойсная стоимость строки в валюте партии."""
        return q2(self.unit_price_currency * self.quantity)

    @property
    def risk_currency(self) -> Decimal:
        """Risk строки в валюте партии."""
        return q2(self.risk_unit_currency * self.quantity)

    @property
    def full_currency(self) -> Decimal:
        """Полная валютная стоимость строки — база распределения общих расходов."""
        return self.invoice_currency + self.risk_currency


@dataclass(frozen=True)
class CategoryPayments:
    """Валютные платежи одной категории: вступившие в силу и план."""

    paid_currency: Decimal = ZERO
    paid_rub: Decimal = ZERO
    planned_currency: Decimal = ZERO
    planned_rub: Decimal = ZERO


@dataclass(frozen=True)
class CategoryFinance:
    """Итог по валютному долгу одной категории (инвойс или risk)."""

    total_currency: Decimal
    paid_currency: Decimal
    paid_rub: Decimal
    remaining_currency: Decimal
    rate: Decimal
    planned_currency: Decimal
    planned_rub: Decimal


@dataclass(frozen=True)
class ItemCost:
    """Себестоимость строки партии в рублях."""

    unit_price_currency: Decimal
    quantity: Decimal
    duty_percent: Decimal
    vat_percent: Decimal
    risk_unit_currency: Decimal
    invoice_currency: Decimal
    risk_currency: Decimal
    duty_rub: Decimal
    vat_rub: Decimal
    risk_rub: Decimal
    expenses_rub: Decimal
    unit_cost: Decimal
    item_total_rub: Decimal


@dataclass(frozen=True)
class BatchFinance:
    """Финансовый итог партии: курсы категорий, расходы и себестоимость."""

    cbr_rate: Decimal
    invoice: CategoryFinance
    risk: CategoryFinance
    expenses_rub: Decimal
    duty_rub: Decimal
    vat_rub: Decimal
    final_cost_rub: Decimal
    items: tuple[ItemCost, ...]

    @property
    def invoice_total_currency(self) -> Decimal:
        return self.invoice.total_currency

    @property
    def risk_total_currency(self) -> Decimal:
        return self.risk.total_currency

    @property
    def average_rate(self) -> Decimal:
        """Средний курс партии по всем валютным долгам — он виден в списке поступлений.

        Взвешиваем по суммам категорий: инвойс и Risk закрываются своими платежами,
        поэтому курс каждой категории входит в средний со своим весом. Пример:
        инвойс 124 000 $ по 88 и Risk 60 000 $ по 91 → 88,978261.
        """
        total = self.invoice.total_currency + self.risk.total_currency
        if total == 0:
            return ZERO
        rub = (
            self.invoice.rate * self.invoice.total_currency
            + self.risk.rate * self.risk.total_currency
        )
        return q6(rub / total)


def _category(
    total_currency: Decimal, payments: CategoryPayments, cbr_rate: Decimal
) -> CategoryFinance:
    """Курс категории: платежи по своим курсам + остаток по курсу ЦБ."""
    total = q2(total_currency)
    remaining = max(ZERO, total - payments.paid_currency)
    rate = q6((payments.paid_rub + remaining * cbr_rate) / total) if total > 0 else ZERO
    return CategoryFinance(
        total_currency=total,
        paid_currency=q2(payments.paid_currency),
        paid_rub=q2(payments.paid_rub),
        remaining_currency=q2(remaining),
        rate=rate,
        planned_currency=q2(payments.planned_currency),
        planned_rub=q2(payments.planned_rub),
    )


def calculate_finance(
    items: Sequence[ItemInput],
    *,
    cbr_rate: Decimal = ONE,
    expenses_rub: Decimal = ZERO,
    invoice: CategoryPayments | None = None,
    risk: CategoryPayments | None = None,
) -> BatchFinance:
    """Себестоимость партии и каждой её строки по согласованной формуле.

    ``cbr_rate`` — курс ЦБ для незакрытых остатков; ``expenses_rub`` — общие
    расходы партии, уже переведённые в рубли.
    """
    rate = cbr_rate if cbr_rate > 0 else ONE
    invoice_finance = _category(
        sum((item.invoice_currency for item in items), ZERO), invoice or CategoryPayments(), rate
    )
    risk_finance = _category(
        sum((item.risk_currency for item in items), ZERO), risk or CategoryPayments(), rate
    )
    full_total = invoice_finance.total_currency + risk_finance.total_currency

    costs: list[ItemCost] = []
    duty_rub = vat_rub = ZERO
    for item in items:
        duty_unit = item.unit_price_currency * item.duty_percent / HUNDRED
        vat_unit = (item.unit_price_currency + duty_unit) * item.vat_percent / HUNDRED
        share = item.full_currency / full_total if full_total > 0 else ZERO
        expenses_item_rub = q2(expenses_rub * share)
        risk_item_rub = q2(item.risk_unit_currency * item.quantity * risk_finance.rate)

        if item.is_customs_cleared:
            # Партия растаможена: пошлина и НДС — фикс в рублях, курс их не трогает.
            assert item.duty_fixed_rub is not None and item.vat_fixed_rub is not None
            duty_item_rub = q2(item.duty_fixed_rub)
            vat_item_rub = q2(item.vat_fixed_rub)
            goods_rub = q2(item.invoice_currency * invoice_finance.rate)
            base_rub = goods_rub + duty_item_rub + vat_item_rub + risk_item_rub
            item_total_rub = q2(base_rub + expenses_item_rub)
        else:
            base_unit_rub = (
                item.unit_price_currency + duty_unit + vat_unit
            ) * invoice_finance.rate + item.risk_unit_currency * risk_finance.rate
            item_total_rub = q2(base_unit_rub * item.quantity + expenses_item_rub)
            duty_item_rub = q2(duty_unit * item.quantity * invoice_finance.rate)
            vat_item_rub = q2(vat_unit * item.quantity * invoice_finance.rate)

        unit_cost = q2(item_total_rub / item.quantity) if item.quantity != 0 else ZERO
        duty_rub += duty_item_rub
        vat_rub += vat_item_rub
        costs.append(
            ItemCost(
                unit_price_currency=item.unit_price_currency,
                quantity=item.quantity,
                duty_percent=item.duty_percent,
                vat_percent=item.vat_percent,
                risk_unit_currency=item.risk_unit_currency,
                invoice_currency=item.invoice_currency,
                risk_currency=item.risk_currency,
                duty_rub=duty_item_rub,
                vat_rub=vat_item_rub,
                risk_rub=risk_item_rub,
                expenses_rub=expenses_item_rub,
                unit_cost=unit_cost,
                item_total_rub=item_total_rub,
            )
        )

    return BatchFinance(
        cbr_rate=rate,
        invoice=invoice_finance,
        risk=risk_finance,
        expenses_rub=q2(expenses_rub),
        duty_rub=q2(duty_rub),
        vat_rub=q2(vat_rub),
        final_cost_rub=q2(sum((cost.item_total_rub for cost in costs), ZERO)),
        items=tuple(costs),
    )


@dataclass(frozen=True)
class CustomsLine:
    """Строка при растаможке: валютные надбавки и база распределения правки.

    ``duty_currency`` и ``vat_currency`` — пошлина и НДС строки в валюте партии,
    ``invoice_currency`` — инвойсная стоимость строки (по ней делим итог, если
    пошлины по процентам нет вовсе).
    """

    duty_currency: Decimal
    vat_currency: Decimal
    invoice_currency: Decimal


def customs_lines(items: Sequence[ItemInput]) -> list[CustomsLine]:
    """Валютные пошлина и НДС по строкам — основа фикса при растаможке."""
    lines: list[CustomsLine] = []
    for item in items:
        duty_unit = item.unit_price_currency * item.duty_percent / HUNDRED
        vat_unit = (item.unit_price_currency + duty_unit) * item.vat_percent / HUNDRED
        lines.append(
            CustomsLine(
                duty_currency=q2(duty_unit * item.quantity),
                vat_currency=q2(vat_unit * item.quantity),
                invoice_currency=item.invoice_currency,
            )
        )
    return lines


def customs_totals_rub(lines: Sequence[CustomsLine], rate: Decimal) -> tuple[Decimal, Decimal]:
    """Пошлина и НДС партии в рублях по курсу на дату растаможки."""
    duty = sum((q2(line.duty_currency * rate) for line in lines), ZERO)
    vat = sum((q2(line.vat_currency * rate) for line in lines), ZERO)
    return q2(duty), q2(vat)


def split_fixed_rub(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Разложить рублёвый итог по строкам пропорционально весам.

    Считаем в копейках и раздаём остаток по крупнейшим дробным частям, поэтому
    сумма строк в точности равна итогу — даже когда итог поправили руками.
    """
    if not weights:
        return []
    cents = int(q2(total) * 100)
    positive = [weight if weight > 0 else ZERO for weight in weights]
    base = sum(positive, ZERO)
    if base <= 0:
        positive = [ONE] * len(weights)
        base = Decimal(len(weights))
    exact = [Decimal(cents) * weight / base for weight in positive]
    whole = [int(value) for value in exact]
    order = sorted(range(len(weights)), key=lambda index: exact[index] - whole[index], reverse=True)
    for index in order[: cents - sum(whole)]:
        whole[index] += 1
    return [Decimal(value) / HUNDRED for value in whole]


def payments_by_category(
    payments: Sequence[BatchPayment], *, today: date | None = None
) -> dict[str, CategoryPayments]:
    """Платежи по категориям: ``invoice`` и ``risk``.

    Платёж с будущей датой попадает в «план» и в себестоимость не входит.
    """
    current = today or date.today()
    totals: dict[str, dict[str, Decimal]] = {
        CATEGORY_INVOICE: {
            "paid_currency": ZERO,
            "paid_rub": ZERO,
            "planned_currency": ZERO,
            "planned_rub": ZERO,
        },
        CATEGORY_RISK: {
            "paid_currency": ZERO,
            "paid_rub": ZERO,
            "planned_currency": ZERO,
            "planned_rub": ZERO,
        },
    }
    for payment in payments:
        bucket = totals.get(payment.category, totals[CATEGORY_INVOICE])
        amount_rub = payment.amount_currency * payment.exchange_rate
        prefix = "paid" if payment.payment_date <= current else "planned"
        bucket[f"{prefix}_currency"] += payment.amount_currency
        bucket[f"{prefix}_rub"] += amount_rub
    return {key: CategoryPayments(**value) for key, value in totals.items()}


def expenses_rub(
    expenses: Sequence[BatchExpense], *, rates: Mapping[str, Decimal] | None = None
) -> Decimal:
    """Общие расходы партии в рублях.

    Расход в рублях берётся как есть, расход в валюте — по курсу ЦБ на текущий
    день (``rates``); если курса нет, валютный расход оценивается в ноль, чтобы
    себестоимость не получила выдуманное число.
    """
    known = rates or {}
    total = ZERO
    for expense in expenses:
        code = (expense.currency or "RUB").strip().upper()
        if code == "RUB":
            total += expense.amount_currency
        else:
            total += expense.amount_currency * known.get(code, ZERO)
    return q2(total)


def items_from_batch(batch: Batch) -> list[ItemInput]:
    """Строки партии в виде входных данных расчёта."""
    return [
        ItemInput(
            unit_price_currency=item.unit_price_currency,
            quantity=item.quantity,
            duty_percent=item.duty_percent,
            vat_percent=item.vat_percent,
            risk_unit_currency=item.risk_unit_currency,
            duty_fixed_rub=item.duty_fixed_rub,
            vat_fixed_rub=item.vat_fixed_rub,
        )
        for item in batch.items
    ]


def finance_for_batch(
    batch: Batch,
    *,
    rate: Decimal | None = None,
    today: date | None = None,
    expense_rates: Mapping[str, Decimal] | None = None,
) -> BatchFinance:
    """Финансовый итог партии по строкам, общим расходам и платежам."""
    cbr_rate = rate if rate is not None else batch.current_exchange_rate
    by_category = payments_by_category(batch.payments, today=today)
    return calculate_finance(
        items_from_batch(batch),
        cbr_rate=cbr_rate if cbr_rate is not None else ONE,
        expenses_rub=expenses_rub(batch.expenses, rates=expense_rates),
        invoice=by_category[CATEGORY_INVOICE],
        risk=by_category[CATEGORY_RISK],
    )
