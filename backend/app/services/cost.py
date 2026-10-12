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

В расчёт входят только платежи с наступившей датой. Платежи с будущей датой —
это план: они видны в ответе (``planned_*``), но себестоимость не меняют.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.models.domain import Batch, BatchExpense, BatchPayment

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
    planned_payments_currency: Decimal = ZERO
    planned_payments_rub: Decimal = ZERO
    planned_expenses_rub: Decimal = ZERO

    @property
    def effective_rate(self) -> Decimal:
        """Фактический курс партии: себестоимость / инвойс в валюте."""
        if self.invoice_total_currency == 0:
            return ZERO
        return (self.final_cost_rub / self.invoice_total_currency).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "invoice_total_currency": str(self.invoice_total_currency),
            "total_paid_currency": str(self.total_paid_currency),
            "total_paid_rub": str(self.total_paid_rub),
            "additional_expenses_rub": str(self.additional_expenses_rub),
            "remaining_payment_currency": str(self.remaining_payment_currency),
            "exchange_rate": str(self.exchange_rate),
            "final_cost_rub": str(self.final_cost_rub),
            "planned_payments_currency": str(self.planned_payments_currency),
            "planned_payments_rub": str(self.planned_payments_rub),
            "planned_expenses_rub": str(self.planned_expenses_rub),
            "effective_rate": str(self.effective_rate),
        }


def calculate_batch_finance(
    *,
    invoice_total_currency: Decimal,
    additional_expenses_rub: Decimal = ZERO,
    total_paid_currency: Decimal = ZERO,
    total_paid_rub: Decimal = ZERO,
    exchange_rate: Decimal | None = None,
    planned_payments_currency: Decimal = ZERO,
    planned_payments_rub: Decimal = ZERO,
    planned_expenses_rub: Decimal = ZERO,
) -> BatchFinance:
    """Финальная стоимость партии в рублях (оперативный слой).

    ``total_paid_*`` и ``additional_expenses_rub`` — только вступившие в силу платежи;
    ``planned_*`` показываются отдельно и в расчёт не входят.
    """
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
        planned_payments_currency=q2(planned_payments_currency),
        planned_payments_rub=q2(planned_payments_rub),
        planned_expenses_rub=q2(planned_expenses_rub),
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


def expenses_totals(
    expenses: Sequence[BatchExpense], *, today: date | None = None
) -> tuple[Decimal, Decimal]:
    """``(рублёвые платежи, план по рублёвым платежам)`` с учётом даты."""
    current = today or date.today()
    fact = planned = ZERO
    for expense in expenses:
        if expense.expense_date <= current:
            fact += expense.amount_rub
        else:
            planned += expense.amount_rub
    return q2(fact), q2(planned)


def batch_expenses_rub(batch: Batch, *, today: date | None = None) -> Decimal:
    """Сумма вступивших в силу рублёвых платежей партии."""
    fact, _ = expenses_totals(batch.expenses, today=today)
    return fact


def batch_invoice_total_currency(batch: Batch) -> Decimal:
    """Инвойсная стоимость партии: если не задана — сумма по строкам."""
    if batch.total_invoice_value:
        return q2(batch.total_invoice_value)
    return q2(sum((item.total_invoice_currency for item in batch.items), ZERO))


def payments_totals(
    payments: Sequence[BatchPayment], *, today: date | None = None
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """``(оплачено валюта, оплачено ₽, план валюта, план ₽)``.

    Платежи с датой в будущем попадают в «план» и в себестоимость не входят.
    """
    current = today or date.today()
    paid_currency = paid_rub = planned_currency = planned_rub = ZERO
    for payment in payments:
        amount_rub = payment.amount_currency * payment.exchange_rate
        if payment.payment_date <= current:
            paid_currency += payment.amount_currency
            paid_rub += amount_rub
        else:
            planned_currency += payment.amount_currency
            planned_rub += amount_rub
    return q2(paid_currency), q2(paid_rub), q2(planned_currency), q2(planned_rub)


def finance_for_batch(
    batch: Batch,
    *,
    rate: Decimal | None = None,
    today: date | None = None,
) -> BatchFinance:
    """Финансовый итог партии по строкам, платежам и расходам.

    ``rate`` — курс для незакрытой части (последний доступный, обновляется сам).
    В расчёт входят только платежи и расходы с наступившей датой.
    """
    paid_currency, paid_rub, planned_currency, planned_rub = payments_totals(
        batch.payments, today=today
    )
    expenses_fact, expenses_planned = expenses_totals(batch.expenses, today=today)
    return calculate_batch_finance(
        invoice_total_currency=batch_invoice_total_currency(batch),
        additional_expenses_rub=expenses_fact,
        total_paid_currency=paid_currency,
        total_paid_rub=paid_rub,
        exchange_rate=rate if rate is not None else batch.current_exchange_rate,
        planned_payments_currency=planned_currency,
        planned_payments_rub=planned_rub,
        planned_expenses_rub=expenses_planned,
    )
