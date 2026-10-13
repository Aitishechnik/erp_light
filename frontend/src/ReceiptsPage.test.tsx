import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Batch, Counterparty, Product } from './api'
import { mockApi } from './apiMock'
import { ReceiptsPage } from './ReceiptsPage'

const SUPPLIERS: Counterparty[] = [
  {
    id: 's1',
    name: 'Импорт Трейд',
    inn: null,
    note: null,
    is_customer: false,
    is_local_supplier: false,
    is_import_supplier: true,
    source: '1c',
    is_active: true,
  },
]

const PRODUCTS: Product[] = [
  {
    id: 'p1',
    code: 'ТОВ1',
    name: 'Арахис в глазури',
    kind: 'finished',
    unit: 'кг',
    source: '1c',
    is_active: true,
  },
]

/** Сегодняшняя дата по локальному календарю — на неё открывается страница. */
const TODAY = (() => {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const date = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${date}`
})()

function batch(overrides: Partial<Batch> = {}): Batch {
  return {
    id: 'b1',
    batch_number: 'P-100',
    batch_type: 'purchase',
    batch_date: TODAY,
    currency: 'USD',
    supplier_id: 's1',
    supplier: 'Импорт Трейд',
    source: 'manual',
    comment: null,
    created_at: '2026-10-08T10:00:00Z',
    finance: {
      invoice_total_currency: '1000.00',
      total_paid_currency: '600.00',
      total_paid_rub: '48000.00',
      additional_expenses_rub: '0.00',
      remaining_payment_currency: '400.00',
      exchange_rate: '90',
      rate_date: '2026-10-08',
      rate_updated_at: '2026-10-08T10:00:00Z',
      planned_payments_currency: '0.00',
      planned_payments_rub: '0.00',
      planned_expenses_rub: '0.00',
      effective_rate: '84.000000',
      final_cost_rub: '84000.00',
    },
    payments: [
      {
        id: 'pay1',
        payment_date: TODAY,
        amount_currency: '600.00',
        exchange_rate: '80',
        amount_rub: '48000.00',
        comment: null,
      },
    ],
    expenses: [],
    items: [
      {
        id: 'i1',
        product_code: 'ТОВ1',
        product_name: 'Арахис в глазури',
        product_kind: 'finished',
        unit: 'кг',
        quantity: '10.000',
        total_invoice_currency: '1000.00',
        item_total_rub: '84000.00',
        unit_cost: '8400.00',
        quantity_on_hand: '10.000',
      },
    ],
    ...overrides,
  }
}

function routes(extra: Record<string, { status?: number; body?: unknown }> = {}) {
  return {
    '/api/v1/batches': { body: [batch()] },
    '/api/v1/counterparties': { body: SUPPLIERS },
    '/api/v1/products': { body: PRODUCTS },
    ...extra,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function bodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) =>
    String((call[1] as { body?: unknown } | undefined)?.body ?? ''),
  )
}

describe('ReceiptsPage', () => {
  it('показывает поступления в календаре и списком за день', async () => {
    mockApi(routes())
    render(<ReceiptsPage />)

    expect(await screen.findByTestId('receipts-calendar')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId(`day-${TODAY}`)).toHaveTextContent('поступлений: 1')
    })
    expect(screen.getByTestId(`day-${TODAY}`)).toHaveTextContent('84 000,00 ₽')
    const list = await screen.findByTestId('day-receipts')
    expect(list).toHaveTextContent('P-100')
    expect(list).toHaveTextContent('Импорт Трейд')
  })

  it('пересчитывает остаток по курсу, но не трогает зафиксированный платёж', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<ReceiptsPage />)

    await waitFor(() => {
      expect(screen.getByTestId(`day-${TODAY}`)).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: 'Открыть' }))

    // 600 $ закрыты по курсу платежа 80 (48 000 ₽), остаток 400 $ по 90 = 36 000 ₽.
    expect(screen.getByTestId('receipt-paid')).toHaveTextContent('600,00')
    expect(screen.getByTestId('receipt-remaining')).toHaveTextContent('400,00')
    expect(screen.getByTestId('payment-rub-p0')).toHaveTextContent('48 000,00')
    expect(screen.getByTestId('receipt-total')).toHaveTextContent('84 000,00')
    expect(screen.getByTestId('unit-cost-i0')).toHaveTextContent('8 400,00')

    const rate = screen.getByLabelText('Курс')
    await user.clear(rate)
    await user.type(rate, '100')

    // Переоценилась только незакрытая часть: 48 000 + 400 × 100 = 88 000 ₽.
    expect(screen.getByTestId('receipt-total')).toHaveTextContent('88 000,00')
    expect(screen.getByTestId('unit-cost-i0')).toHaveTextContent('8 800,00')
    expect(screen.getByTestId('payment-rub-p0')).toHaveTextContent('48 000,00')
  })

  it('создаёт поступление и отправляет строки с товаром', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [batch()] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await user.click(screen.getByRole('button', { name: 'Добавить поступление' }))

    await user.type(screen.getByLabelText('Номер поступления'), 'P-200')
    await user.selectOptions(screen.getByLabelText('Поставщик'), 's1')
    await user.clear(screen.getByLabelText('Валюта'))
    await user.type(screen.getByLabelText('Валюта'), 'USD')
    await user.type(screen.getByLabelText('Товар i0'), 'ТОВ1')
    await user.type(screen.getByLabelText('Количество i0'), '5')
    await user.type(screen.getByLabelText('Сумма i0'), '500')
    await user.clear(screen.getByLabelText('Курс'))
    await user.type(screen.getByLabelText('Курс'), '95')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(bodies().some((body) => body.includes('"product_code":"ТОВ1"'))).toBe(true)
    })
    const sent = bodies().find((body) => body.includes('P-200')) ?? ''
    expect(sent).toContain('"supplier_id":"s1"')
    expect(sent).toContain('"current_exchange_rate":"95"')
    expect(sent).toContain('"quantity":"5"')
  })

  it('показывает ошибку сервера при сохранении', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        '/api/v1/batches': { status: 409, body: { detail: 'Поступление «P-100» уже существует' } },
      }),
    )
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await user.click(screen.getByRole('button', { name: 'Добавить поступление' }))
    await user.type(screen.getByLabelText('Номер поступления'), 'P-100')
    await user.type(screen.getByLabelText('Товар i0'), 'ТОВ1')
    await user.type(screen.getByLabelText('Количество i0'), '1')
    await user.type(screen.getByLabelText('Сумма i0'), '10')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('уже существует')
  })

  it('запрашивает курс ЦБ по кнопке', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        '/api/v1/rates/USD': {
          body: {
            code: 'USD',
            rate_date: '2026-10-08',
            rate: '91.2500',
            nominal: 1,
            source: 'cbr',
          },
        },
      }),
    )
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await user.click(screen.getByRole('button', { name: 'Добавить поступление' }))
    await user.clear(screen.getByLabelText('Валюта'))
    await user.type(screen.getByLabelText('Валюта'), 'USD')
    await user.click(screen.getByRole('button', { name: 'Обновить курс ЦБ' }))

    await waitFor(() => {
      expect(screen.getByLabelText('Курс')).toHaveValue('91.2500')
    })
    expect(screen.getByText(/Курс ЦБ/)).toBeInTheDocument()
  })
})

describe('ReceiptsPage — план и лимит', () => {
  const FUTURE = '2099-01-01'

  it('будущий платёж — план: в себестоимость не входит', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await user.click(screen.getByRole('button', { name: 'Добавить поступление' }))
    await user.clear(screen.getByLabelText('Валюта'))
    await user.type(screen.getByLabelText('Валюта'), 'USD')
    await user.type(screen.getByLabelText('Товар i0'), 'ТОВ1')
    await user.type(screen.getByLabelText('Количество i0'), '10')
    await user.type(screen.getByLabelText('Сумма i0'), '1000')
    await user.clear(screen.getByLabelText('Курс'))
    await user.type(screen.getByLabelText('Курс'), '90')

    await user.click(screen.getByRole('button', { name: 'Добавить валютный платёж' }))
    const pay = screen.getByTestId('receipt-payments').querySelector('tbody tr')
    expect(pay).not.toBeNull()
    await user.clear(screen.getByLabelText('Дата платежа pnew1'))
    await user.type(screen.getByLabelText('Дата платежа pnew1'), FUTURE)
    await user.type(screen.getByLabelText('Сумма платежа pnew1'), '400')
    await user.type(screen.getByLabelText('Курс платежа pnew1'), '80')

    // Платёж виден как план, но факт и себестоимость считаются без него.
    expect(screen.getByTestId('receipt-planned')).toHaveTextContent('400,00')
    expect(screen.getByTestId('receipt-paid')).toHaveTextContent('0,00')
    expect(screen.getByTestId('receipt-remaining')).toHaveTextContent('1 000,00')
    expect(screen.getByTestId('receipt-total')).toHaveTextContent('90 000,00 ₽')
  })

  it('платёж больше стоимости товаров — предупреждение и блокировка сохранения', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await user.click(screen.getByRole('button', { name: 'Добавить поступление' }))
    await user.type(screen.getByLabelText('Товар i0'), 'ТОВ1')
    await user.type(screen.getByLabelText('Количество i0'), '10')
    await user.type(screen.getByLabelText('Сумма i0'), '1000')
    await user.click(screen.getByRole('button', { name: 'Добавить валютный платёж' }))
    await user.type(screen.getByLabelText('Сумма платежа pnew1'), '1500')
    await user.type(screen.getByLabelText('Курс платежа pnew1'), '80')

    expect(screen.getByTestId('receipt-limit-error')).toHaveTextContent('больше')
    expect(screen.getByTestId('receipt-limit')).toHaveTextContent('0,00')
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
  })

  it('черновик из 1С помечен в календаре и сохраняется без позиций', async () => {
    const user = userEvent.setup()
    const draft = batch({
      id: 'd1',
      batch_number: 'ИТ-00000388',
      source: '1c',
      currency: 'RUB',
      comment: 'Фундук 145600 + сбор 32980',
      items: [],
      payments: [],
      finance: {
        ...batch().finance,
        invoice_total_currency: '0.00',
        total_paid_currency: '0.00',
        total_paid_rub: '0.00',
        remaining_payment_currency: '0.00',
        exchange_rate: '1',
        effective_rate: '0.000000',
        final_cost_rub: '0.00',
      },
    })
    mockApi(routes({ '/api/v1/batches': { body: [draft] } }))
    render(<ReceiptsPage />)

    const badge = await screen.findByTestId('draft-badge')
    expect(badge).toHaveTextContent('черновик')
    const row = screen.getByTestId('day-receipt-d1')
    // У черновика нет ни курса, ни себестоимости — вместо нулей прочерк.
    expect(row).toHaveTextContent('—')
    expect(row).not.toHaveTextContent('0,00')

    await user.click(within(row).getByRole('button', { name: 'Открыть' }))
    expect(screen.getByTestId('draft-hint')).toHaveTextContent('Черновик из выгрузки 1С')
    // Сохраняем черновик, не добавляя ни одной позиции.
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(screen.queryByTestId('receipt-form')).toBeNull()
    })
    const sent = bodies().find((body) => body.includes('ИТ-00000388')) ?? ''
    expect(sent).toContain('"items":[]')
    expect(sent).toContain('Фундук 145600')
  })

  it('в списке за день показывается фактический курс партии', async () => {
    mockApi(
      routes({
        '/api/v1/batches': {
          body: [
            batch({
              finance: {
                ...batch().finance,
                exchange_rate: '85',
                effective_rate: '100.500000',
              },
            }),
          ],
        },
      }),
    )
    render(<ReceiptsPage />)

    const list = await screen.findByTestId('day-receipts')
    expect(list).toHaveTextContent('100.5')
    expect(list).not.toHaveTextContent('85')
  })
})
