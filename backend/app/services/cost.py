"""Оперативная себестоимость партии.

Формула перенесена без изменений из custom_erp (`erp_v_2`):
  * ``backend/app/services/finance_service.py::calculate_batch_finance``
  * ``backend/app/core/cost_calculator.py::calculate_unit_cost``

Что сохранено дословно:
    remaining_payment = max(0, total_invoice_value - total_paid_currency)
    final_cost_rub    = total_paid_rub + доп.расходы + remaining_payment * курс
    unit_cost         = final_cost_rub / total_invoice_value
                        * total_invoice_currency(строки) / quantity(строки)

Что НЕ перенесено (осознанно): бухгалтерский слой — счета, проводки, курсовые
разницы по ПБУ. Это зона 1С.

Оплаты приходят из валютных платежей партии (``batch_payments``): каждый платёж
хранит свой курс, поэтому ``total_paid_rub`` — сумма платежей по их курсам. Курс для
незакрытой части — текущий (последний доступный курс ЦБ), поэтому она переоценивается,
а сделанные платежи — нет.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.models.domain import Batch, BatchPayment

ZERO = Decimal("0.00")
ONE = Decimal("1")
CENT = Decimal("0.01")


def q2(value: Decimal) -> Decimal:
    """Округление денег до копейки (HALF_UP), как в custom_erp."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BatchFinance:
    """Финансовый итог партии в рублях."""

    invoice_total_currency: Decimal
    total_paid_currency: Decimal
    total_paid_rub: Decimal
    additional_expenses_rub: Decimal
    remaining_payment_currency: Decimal
    exchange_rate: Decimal
    final_cost_rub: Decimal

    def as_dict(self) -> dict[str, str]:
        return {
            "invoice_total_currency": str(self.invoice_total_currency),
            "total_paid_currency": str(self.total_paid_currency),
            "total_paid_rub": str(self.total_paid_rub),
            "additional_expenses_rub": str(self.additional_expenses_rub),
            "remaining_payment_currency": str(self.remaining_payment_currency),
            "exchange_rate": str(self.exchange_rate),
            "final_cost_rub": str(self.final_cost_rub),
        }


def calculate_batch_finance(
    *,
    invoice_total_currency: Decimal,
    additional_expenses_rub: Decimal = ZERO,
    total_paid_currency: Decimal = ZERO,
    total_paid_rub: Decimal = ZERO,
    exchange_rate: Decimal | None = None,
) -> BatchFinance:
    """Финальная стоимость партии в рублях (оперативный слой)."""
    rate = exchange_rate if exchange_rate is not None else ONE
    remaining = max(ZERO, invoice_total_currency - total_paid_currency)
    final_cost_rub = total_paid_rub + additional_expenses_rub + remaining * rate
    return BatchFinance(
        invoice_total_currency=q2(invoice_total_currency),
        total_paid_currency=q2(total_paid_currency),
        total_paid_rub=q2(total_paid_rub),
        additional_expenses_rub=q2(additional_expenses_rub),
        remaining_payment_currency=q2(remaining),
        exchange_rate=rate,
        final_cost_rub=q2(final_cost_rub),
    )


def calculate_item_cost(
    finance: BatchFinance,
    *,
    item_invoice_currency: Decimal,
    item_quantity: Decimal,
) -> tuple[Decimal, Decimal]:
    """``(стоимость строки в рублях, себестоимость единицы)``.

    Доля строки в инвойсе партии — база распределения доп.расходов и курса.
    """
    if finance.final_cost_rub == 0 or finance.invoice_total_currency == 0:
        return ZERO, ZERO
    if item_quantity == 0 or item_invoice_currency == 0:
        return ZERO, ZERO

    item_share = item_invoice_currency / finance.invoice_total_currency
    item_total_rub = q2(finance.final_cost_rub * item_share)
    unit_cost = q2(item_total_rub / item_quantity)
    return item_total_rub, unit_cost


def batch_expenses_rub(batch: Batch) -> Decimal:
    """Сумма доп.расходов партии в рублях."""
    return q2(sum((expense.amount_rub for expense in batch.expenses), ZERO))


def batch_invoice_total_currency(batch: Batch) -> Decimal:
    """Инвойсная стоимость партии: если не задана — сумма по строкам."""
    if batch.total_invoice_value:
        return q2(batch.total_invoice_value)
    return q2(sum((item.total_invoice_currency for item in batch.items), ZERO))


def payments_totals(payments: Sequence[BatchPayment]) -> tuple[Decimal, Decimal]:
    """``(оплачено в валюте, оплачено рублей)`` по зафиксированным курсам платежей."""
    paid_currency = q2(sum((payment.amount_currency for payment in payments), ZERO))
    paid_rub = q2(
        sum((payment.amount_currency * payment.exchange_rate for payment in payments), ZERO)
    )
    return paid_currency, paid_rub


def finance_for_batch(
    batch: Batch,
    *,
    rate: Decimal | None = None,
    paid_currency: Decimal | None = None,
    paid_rub: Decimal | None = None,
) -> BatchFinance:
    """Финансовый итог партии по строкам, расходам и валютным платежам.

    ``rate`` — курс для незакрытой части (последний доступный, обновляется сам).
    Если оплаты не переданы, берутся из платежей партии.
    """
    if paid_currency is None or paid_rub is None:
        from_payments_currency, from_payments_rub = payments_totals(batch.payments)
        paid_currency = from_payments_currency if paid_currency is None else paid_currency
        paid_rub = from_payments_rub if paid_rub is None else paid_rub
    return calculate_batch_finance(
        invoice_total_currency=batch_invoice_total_currency(batch),
        additional_expenses_rub=batch_expenses_rub(batch),
        total_paid_currency=paid_currency,
        total_paid_rub=paid_rub,
        exchange_rate=rate if rate is not None else batch.current_exchange_rate,
    )
