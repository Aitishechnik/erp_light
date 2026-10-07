import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SalesPlan, SessionUser } from './api'
import { mockApi } from './apiMock'
import { SalesPlansPage } from './SalesPlansPage'

const YEAR = new Date().getFullYear()

const COMMERCIAL: SessionUser = {
  id: 'cd-1',
  login: 'commercial',
  full_name: 'Коммерческий директор',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
}

const MANAGER: SessionUser = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Иван Петров',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

function plan(overrides: Partial<SalesPlan> = {}): SalesPlan {
  return {
    id: 'plan-1',
    year: YEAR,
    manager_id: 'sm-1',
    manager_name: 'Менеджер по продажам',
    created_by_name: 'Менеджер по продажам',
    status: 'on_review',
    status_title: 'На проверке',
    notes: null,
    created_at: '2026-10-06T10:00:00Z',
    updated_at: '2026-10-06T10:00:00Z',
    editable_months: [12],
    total_amount: '1000.00',
    items: [
      {
        id: 'item-1',
        product_id: 'product-1',
        product_code: 'SKU-1',
        product_name: 'Товар 1',
        product_kind: 'goods',
        unit: 'шт',
        month: 12,
        quantity: '10.000',
        price: '100.00',
        amount: '1000.00',
        notes: null,
      },
    ],
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function calls(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) => String(call[0]))
}

describe('SalesPlansPage', () => {
  it('показывает план и утверждает его по кнопке', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/sales-plans/plan-1/approve': { body: plan({ status: 'approved' }) },
      '/api/v1/sales-plans': { body: [plan()] },
      '/api/v1/users': { body: [MANAGER] },
      '/api/v1/products': { body: [] },
    })
    render(<SalesPlansPage user={COMMERCIAL} />)

    expect(await screen.findByText('Менеджер по продажам')).toBeInTheDocument()
    expect(screen.getByText('На проверке')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('plan-total')).toHaveTextContent('1 000,00')
    })
    // Строка плана видна в матрице, замороженный январь недоступен для правки.
    expect(screen.getByLabelText('SKU-1 Декабрь')).toHaveValue('10.000')
    expect(screen.getByLabelText('SKU-1 Январь')).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Утвердить' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plans/plan-1/approve'))).toBe(true)
    })
  })

  it('менеджер отправляет свой план на проверку', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/sales-plans/plan-1/submit': { body: plan({ status: 'on_review' }) },
      '/api/v1/sales-plans': { body: [plan({ status: 'filling', status_title: 'Заполняется' })] },
      '/api/v1/products': {
        body: [
          {
            id: 'product-2',
            code: 'SKU-2',
            name: 'Товар 2',
            kind: 'goods',
            unit: 'шт',
            is_active: true,
          },
        ],
      },
    })
    render(<SalesPlansPage user={MANAGER} />)

    await screen.findByText('Заполняется')
    expect(screen.queryByRole('button', { name: 'Утвердить' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Отправить на проверку' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plans/plan-1/submit'))).toBe(true)
    })
  })

  it('показывает ошибку, если сохранение отклонено', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/sales-plans/plan-1/items': {
        status: 409,
        body: { detail: 'Замороженные месяцы менять нельзя: 1' },
      },
      '/api/v1/sales-plans': { body: [plan({ status: 'filling', status_title: 'Заполняется' })] },
      '/api/v1/users': { body: [MANAGER] },
      '/api/v1/products': { body: [] },
    })
    render(<SalesPlansPage user={COMMERCIAL} />)

    await screen.findByText('Заполняется')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Замороженные месяцы менять нельзя')
  })
})
