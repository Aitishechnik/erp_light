"""Проверка перенесённой оперативной формулы себестоимости.

Числовые векторы взяты из тестов custom_erp (erp_v_2), чтобы доказать, что
перенос не изменил результат:
  * tests/test_supplier_payment_cycle.py — полная/частичная оплата RUB и USD;
  * tests/test_purchase_receipt_service.py — курс и доп.расходы.
"""

from decimal import Decimal

from app.services.cost import calculate_batch_finance, calculate_item_cost


def test_fully_paid_rub_keeps_invoice_amount() -> None:
    """Оплачено 87400 из 87400 → остаток 0, себестоимость 87400 (вектор erp_v_2)."""
    finance = calculate_batch_finance(
        invoice_total_currency=Decimal("87400.00"),
        total_paid_currency=Decimal("87400.00"),
        total_paid_rub=Decimal("87400.00"),
    )
    assert finance.remaining_payment_currency == Decimal("0.00")
    assert finance.final_cost_rub == Decimal("87400.00")


def test_fully_paid_usd_uses_payment_rate() -> None:
    """3600 USD оплачено по курсу 90 → 324000 руб, остатка нет (вектор erp_v_2)."""
    finance = calculate_batch_finance(
        invoice_total_currency=Decimal("3600.00"),
        total_paid_currency=Decimal("3600.00"),
        total_paid_rub=Decimal("324000.00"),
        exchange_rate=Decimal("90"),
    )
    assert finance.remaining_payment_currency == Decimal("0.00")
    assert finance.final_cost_rub == Decimal("324000.00")


def test_partial_payment_remaining_valued_at_rate() -> None:
    """Оплачено 40000 из 87400, курс 1 → остаток 47400, итог 87400 (вектор erp_v_2)."""
    finance = calculate_batch_finance(
        invoice_total_currency=Decimal("87400.00"),
        total_paid_currency=Decimal("40000.00"),
        total_paid_rub=Decimal("40000.00"),
        exchange_rate=Decimal("1"),
    )
    assert finance.remaining_payment_currency == Decimal("47400.00")
    assert finance.final_cost_rub == Decimal("87400.00")


def test_unpaid_invoice_valued_at_current_rate_plus_expenses() -> None:
    """Без оплат: инвойс 1000 USD по курсу 95 + расходы 5000 → 100000 руб."""
    finance = calculate_batch_finance(
        invoice_total_currency=Decimal("1000.00"),
        additional_expenses_rub=Decimal("5000.00"),
        exchange_rate=Decimal("95"),
    )
    assert finance.remaining_payment_currency == Decimal("1000.00")
    assert finance.final_cost_rub == Decimal("100000.00")


def test_overpayment_does_not_create_negative_remaining() -> None:
    """Переплата не даёт отрицательный остаток и не уменьшает себестоимость."""
    finance = calculate_batch_finance(
        invoice_total_currency=Decimal("100.00"),
        total_paid_currency=Decimal("150.00"),
        total_paid_rub=Decimal("150.00"),
    )
    assert finance.remaining_payment_currency == Decimal("0.00")
    assert finance.final_cost_rub == Decimal("150.00")


def test_unit_cost_distributes_batch_expenses_by_invoice_share() -> None:
    """Доп.расходы раскладываются пропорционально инвойсной стоимости строк."""
    batch_invoice = Decimal("1000.00")
    finance = calculate_batch_finance(
        invoice_total_currency=batch_invoice,
        additional_expenses_rub=Decimal("500.00"),
        exchange_rate=Decimal("1"),
    )
    assert finance.final_cost_rub == Decimal("1500.00")

    # Строка 1: 600 из 1000 → 900 руб на 10 шт = 90 руб/шт.
    item_total_1, unit_1 = calculate_item_cost(
        finance, item_invoice_currency=Decimal("600.00"), item_quantity=Decimal("10")
    )
    assert item_total_1 == Decimal("900.00")
    assert unit_1 == Decimal("90.00")

    # Строка 2: 400 из 1000 → 600 руб на 5 шт = 120 руб/шт.
    item_total_2, unit_2 = calculate_item_cost(
        finance, item_invoice_currency=Decimal("400.00"), item_quantity=Decimal("5")
    )
    assert item_total_2 == Decimal("600.00")
    assert unit_2 == Decimal("120.00")


def test_zero_invoice_and_zero_quantity_are_safe() -> None:
    """Нулевой инвойс или нулевое количество не делят на ноль."""
    empty = calculate_batch_finance(invoice_total_currency=Decimal("0.00"))
    assert empty.final_cost_rub == Decimal("0.00")
    assert calculate_item_cost(
        empty, item_invoice_currency=Decimal("0.00"), item_quantity=Decimal("1")
    ) == (Decimal("0.00"), Decimal("0.00"))

    finance = calculate_batch_finance(
        invoice_total_currency=Decimal("100.00"), exchange_rate=Decimal("1")
    )
    assert calculate_item_cost(
        finance, item_invoice_currency=Decimal("100.00"), item_quantity=Decimal("0")
    ) == (Decimal("0.00"), Decimal("0.00"))
