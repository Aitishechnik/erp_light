import { render, screen, waitFor } from '@testing-library/react'
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

function batch(overrides: Partial<Batch> = {}): Batch {
  return {
    id: 'b1',
    batch_number: 'P-100',
    batch_type: 'purchase',
    batch_date: '2026-10-08',
    currency: 'USD',
    supplier_id: 's1',
    supplier: 'Импорт Трейд',
    source: 'manual',
    comment: null,
    created_at: '2026-10-08T10:00:00Z',
    finance: {
      invoice_total_currency: '1000.00',
      total_paid_currency: '0.00',
      total_paid_rub: '0.00',
      additional_expenses_rub: '0.00',
      remaining_payment_currency: '1000.00',
      exchange_rate: '90',
      final_cost_rub: '90000.00',
    },
    items: [
      {
        id: 'i1',
        product_code: 'ТОВ1',
        product_name: 'Арахис в глазури',
        product_kind: 'finished',
        unit: 'кг',
        quantity: '10.000',
        total_invoice_currency: '1000.00',
        item_total_rub: '90000.00',
        unit_cost: '9000.00',
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
      expect(screen.getByTestId('day-2026-10-08')).toHaveTextContent('поступлений: 1')
    })
    expect(screen.getByTestId('day-2026-10-08')).toHaveTextContent('90 000,00 ₽')
    const list = await screen.findByTestId('day-receipts')
    expect(list).toHaveTextContent('P-100')
    expect(list).toHaveTextContent('Импорт Трейд')
  })

  it('пересчитывает себестоимость при смене курса без запроса к серверу', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<ReceiptsPage />)

    await waitFor(() => {
      expect(screen.getByTestId('day-2026-10-08')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: 'Открыть' }))

    expect(screen.getByTestId('receipt-total')).toHaveTextContent('90 000,00')
    expect(screen.getByTestId('unit-cost-i0')).toHaveTextContent('9 000,00')

    const rate = screen.getByLabelText('Курс')
    await user.clear(rate)
    await user.type(rate, '100')

    expect(screen.getByTestId('receipt-total')).toHaveTextContent('100 000,00')
    expect(screen.getByTestId('unit-cost-i0')).toHaveTextContent('10 000,00')
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
    await user.click(screen.getByRole('button', { name: 'Курс ЦБ' }))

    await waitFor(() => {
      expect(screen.getByLabelText('Курс')).toHaveValue('91.2500')
    })
    expect(screen.getByText(/Курс ЦБ на/)).toBeInTheDocument()
  })
})
