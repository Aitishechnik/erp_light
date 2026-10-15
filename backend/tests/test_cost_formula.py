"""Проверка формулы оперативной себестоимости партии.

Числовые векторы первых тестов взяты из тестов custom_erp (erp_v_2), чтобы доказать,
что перенос не изменил результат для простого случая (только инвойс, без надбавок):

  * tests/test_supplier_payment_cycle.py — полная/частичная оплата RUB и USD;
  * tests/test_purchase_receipt_service.py — курс и доп.расходы.

Остальные тесты — новая формула: пошлина, НДС, Risk и категории валютных платежей
(см. docs/data-contract-receipts.md §3).
"""

from decimal import Decimal

from app.services.cost import (
    CategoryPayments,
    ItemInput,
    calculate_finance,
)


def test_fully_paid_rub_keeps_invoice_amount() -> None:
    """Оплачено 87400 из 87400 → остаток 0, себестоимость 87400 (вектор erp_v_2)."""
    finance = calculate_finance(
        [ItemInput(unit_price_currency=Decimal("87400.00"), quantity=Decimal("1"))],
        cbr_rate=Decimal("1"),
        invoice=CategoryPayments(paid_currency=Decimal("87400.00"), paid_rub=Decimal("87400.00")),
    )
    assert finance.invoice.remaining_currency == Decimal("0.00")
    assert finance.final_cost_rub == Decimal("87400.00")


def test_fully_paid_usd_uses_payment_rate() -> None:
    """3600 USD оплачено по курсу 90 → 324000 руб, остатка нет (вектор erp_v_2)."""
    finance = calculate_finance(
        [ItemInput(unit_price_currency=Decimal("3600.00"), quantity=Decimal("1"))],
        cbr_rate=Decimal("90"),
        invoice=CategoryPayments(paid_currency=Decimal("3600.00"), paid_rub=Decimal("324000.00")),
    )
    assert finance.invoice.remaining_currency == Decimal("0.00")
    assert finance.invoice.rate == Decimal("90.000000")
    assert finance.final_cost_rub == Decimal("324000.00")


def test_partial_payment_remaining_valued_at_rate() -> None:
    """Оплачено 40000 из 87400, курс 1 → остаток 47400, итог 87400 (вектор erp_v_2)."""
    finance = calculate_finance(
        [ItemInput(unit_price_currency=Decimal("87400.00"), quantity=Decimal("1"))],
        cbr_rate=Decimal("1"),
        invoice=CategoryPayments(paid_currency=Decimal("40000.00"), paid_rub=Decimal("40000.00")),
    )
    assert finance.invoice.remaining_currency == Decimal("47400.00")
    assert finance.final_cost_rub == Decimal("87400.00")


def test_unpaid_invoice_valued_at_current_rate_plus_expenses() -> None:
    """Без оплат: инвойс 1000 USD по курсу 95 + расходы 5000 → 100000 руб."""
    finance = calculate_finance(
        [ItemInput(unit_price_currency=Decimal("1000.00"), quantity=Decimal("1"))],
        cbr_rate=Decimal("95"),
        expenses_rub=Decimal("5000.00"),
    )
    assert finance.invoice.remaining_currency == Decimal("1000.00")
    assert finance.final_cost_rub == Decimal("100000.00")


def test_overpayment_does_not_create_negative_remaining() -> None:
    """Переплата не даёт отрицательный остаток и не уменьшает себестоимость."""
    finance = calculate_finance(
        [ItemInput(unit_price_currency=Decimal("100.00"), quantity=Decimal("1"))],
        cbr_rate=Decimal("1"),
        invoice=CategoryPayments(paid_currency=Decimal("150.00"), paid_rub=Decimal("150.00")),
    )
    assert finance.invoice.remaining_currency == Decimal("0.00")
    assert finance.final_cost_rub == Decimal("150.00")


def test_unit_cost_distributes_batch_expenses_by_invoice_share() -> None:
    """Доп.расходы раскладываются пропорционально валютной стоимости строк."""
    finance = calculate_finance(
        [
            ItemInput(unit_price_currency=Decimal("60.00"), quantity=Decimal("10")),
            ItemInput(unit_price_currency=Decimal("80.00"), quantity=Decimal("5")),
        ],
        cbr_rate=Decimal("1"),
        expenses_rub=Decimal("500.00"),
    )
    assert finance.invoice_total_currency == Decimal("1000.00")
    assert finance.final_cost_rub == Decimal("1500.00")

    # Строка 1: 600 из 1000 → 900 руб на 10 шт = 90 руб/шт.
    assert finance.items[0].item_total_rub == Decimal("900.00")
    assert finance.items[0].unit_cost == Decimal("90.00")
    # Строка 2: 400 из 1000 → 600 руб на 5 шт = 120 руб/шт.
    assert finance.items[1].item_total_rub == Decimal("600.00")
    assert finance.items[1].unit_cost == Decimal("120.00")


def test_zero_invoice_and_zero_quantity_are_safe() -> None:
    """Нулевой инвойс или нулевое количество не делят на ноль."""
    empty = calculate_finance([], cbr_rate=Decimal("1"))
    assert empty.final_cost_rub == Decimal("0.00")
    assert empty.items == ()

    finance = calculate_finance(
        [ItemInput(unit_price_currency=Decimal("100.00"), quantity=Decimal("0"))],
        cbr_rate=Decimal("1"),
    )
    assert finance.items[0].item_total_rub == Decimal("0.00")
    assert finance.items[0].unit_cost == Decimal("0.00")


def test_duty_vat_and_risk_are_counted_in_currency() -> None:
    """Пример согласованной формулы: пошлина и НДС в валюте, Risk отдельной строкой.

    100 шт по 10 $, пошлина 5 %, НДС 22 %, Risk 1 $/шт, курс 90, расходы 50 000 ₽:
    (10 + 0,5 + 2,31) × 90 + 1 × 90 = 1242,90 ₽ за единицу, 124 290 ₽ + 50 000 ₽.
    """
    finance = calculate_finance(
        [
            ItemInput(
                unit_price_currency=Decimal("10"),
                quantity=Decimal("100"),
                duty_percent=Decimal("5"),
                vat_percent=Decimal("22"),
                risk_unit_currency=Decimal("1"),
            )
        ],
        cbr_rate=Decimal("90"),
        expenses_rub=Decimal("50000.00"),
    )
    assert finance.invoice_total_currency == Decimal("1000.00")
    assert finance.risk_total_currency == Decimal("100.00")
    assert finance.duty_rub == Decimal("4500.00")  # 0,5 $ × 100 шт × 90
    assert finance.vat_rub == Decimal("20790.00")  # 2,31 $ × 100 шт × 90
    assert finance.items[0].item_total_rub == Decimal("174290.00")
    assert finance.items[0].unit_cost == Decimal("1742.90")
    assert finance.final_cost_rub == Decimal("174290.00")


def test_invoice_and_risk_are_paid_separately() -> None:
    """Инвойс 40 000 $ и Risk 10 000 $: платёж 20 000 $ по 115, остальное по ЦБ 90."""
    items = [
        ItemInput(
            unit_price_currency=Decimal("200"),
            quantity=Decimal("100"),
            risk_unit_currency=Decimal("50"),
        ),
        ItemInput(
            unit_price_currency=Decimal("200"),
            quantity=Decimal("100"),
            risk_unit_currency=Decimal("50"),
        ),
    ]
    finance = calculate_finance(
        items,
        cbr_rate=Decimal("90"),
        invoice=CategoryPayments(paid_currency=Decimal("20000"), paid_rub=Decimal("2300000")),
    )
    assert finance.invoice_total_currency == Decimal("40000.00")
    assert finance.risk_total_currency == Decimal("10000.00")
    # (20 000 × 115 + 20 000 × 90) ÷ 40 000 = 102,50; Risk целиком по курсу ЦБ.
    assert finance.invoice.rate == Decimal("102.500000")
    assert finance.risk.rate == Decimal("90.000000")
    assert finance.invoice.remaining_currency == Decimal("20000.00")
    # 40 000 × 102,5 + 10 000 × 90 = 4 100 000 + 900 000.
    assert finance.final_cost_rub == Decimal("5000000.00")
    assert finance.items[0].unit_cost == Decimal("25000.00")
    assert finance.items[0].risk_rub == Decimal("450000.00")  # 50 $ × 100 шт × 90


def test_planned_payments_are_not_counted() -> None:
    """Платежи с будущей датой — план: они не меняют курс категории."""
    finance = calculate_finance(
        [ItemInput(unit_price_currency=Decimal("1000"), quantity=Decimal("1"))],
        cbr_rate=Decimal("90"),
        invoice=CategoryPayments(planned_currency=Decimal("600"), planned_rub=Decimal("48000")),
    )
    assert finance.invoice.rate == Decimal("90.000000")
    assert finance.invoice.planned_currency == Decimal("600.00")
    assert finance.invoice.planned_rub == Decimal("48000.00")
    assert finance.final_cost_rub == Decimal("90000.00")


def test_average_rate_weighs_invoice_and_risk() -> None:
    """Средний курс партии — по обеим категориям, а не только по инвойсу.

    Инвойс 124 000 $ закрыт по 88, Risk 60 000 $ — по 91:
    (124 000 × 88 + 60 000 × 91) ÷ 184 000 = 88,978261.
    """
    finance = calculate_finance(
        [
            ItemInput(
                unit_price_currency=Decimal("6.2"),
                quantity=Decimal("20000"),
                risk_unit_currency=Decimal("3"),
            )
        ],
        cbr_rate=Decimal("90"),
        invoice=CategoryPayments(paid_currency=Decimal("124000"), paid_rub=Decimal("10912000")),
        risk=CategoryPayments(paid_currency=Decimal("60000"), paid_rub=Decimal("5460000")),
    )
    assert finance.invoice.rate == Decimal("88.000000")
    assert finance.risk.rate == Decimal("91.000000")
    assert finance.average_rate == Decimal("88.978261")


def test_average_rate_without_debts_is_cbr_rate() -> None:
    """Пустая партия не делит на ноль, а без платежей средний курс равен курсу ЦБ."""
    empty = calculate_finance([], cbr_rate=Decimal("90"))
    assert empty.average_rate == Decimal("0.00")

    finance = calculate_finance(
        [
            ItemInput(
                unit_price_currency=Decimal("10"),
                quantity=Decimal("1"),
                risk_unit_currency=Decimal("1"),
            )
        ],
        cbr_rate=Decimal("90"),
    )
    assert finance.average_rate == Decimal("90.000000")


def test_expenses_are_shared_by_full_currency_value() -> None:
    """Общие расходы делятся по полной стоимости строки: инвойс + Risk."""
    finance = calculate_finance(
        [
            # Полная стоимость 1000 $ (инвойс 900 + risk 100).
            ItemInput(
                unit_price_currency=Decimal("90"),
                quantity=Decimal("10"),
                risk_unit_currency=Decimal("10"),
            ),
            # Полная стоимость 1000 $ (только инвойс).
            ItemInput(unit_price_currency=Decimal("100"), quantity=Decimal("10")),
        ],
        cbr_rate=Decimal("1"),
        expenses_rub=Decimal("2000.00"),
    )
    # Расходы поделены пополам — по 1000 ₽ на строку.
    assert finance.items[0].expenses_rub == Decimal("1000.00")
    assert finance.items[1].expenses_rub == Decimal("1000.00")
