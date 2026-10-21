import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AnnualSalesPlanPage } from './AnnualSalesPlanPage'
import type { AnnualSalesPlan, SessionUser } from './api'
import { mockApi } from './apiMock'

const YEAR = new Date().getFullYear()

const COMMERCIAL: SessionUser = {
  id: 'cd-1',
  login: 'commercial',
  full_name: 'Коммерческий директор',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
}

const EXECUTIVE: SessionUser = {
  id: 'ed-1',
  login: 'executive',
  full_name: 'Ольга Директорова',
  role: 'executive_director',
  role_title: 'Исполнительный директор',
}

const SALES: SessionUser = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Иван Петров',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

function annual(overrides: Partial<AnnualSalesPlan> = {}): AnnualSalesPlan {
  return {
    year: YEAR,
    status: 'draft',
    status_title: 'Не отправлен',
    submitted_by_name: null,
    submitted_at: null,
    approved_by_name: null,
    approved_at: null,
    notes: null,
    is_stale: false,
    all_approved: true,
    missing_managers: [],
    managers: [
      {
        manager_id: 'sm-1',
        manager_name: 'Иван Петров',
        plan_id: 'plan-1',
        plan_status: 'approved',
        plan_status_title: 'Утверждён',
        approved: true,
        positions: 2,
        clients: 1,
      },
    ],
    items: [
      {
        manager_id: 'sm-1',
        manager_name: 'Иван Петров',
        client_id: 'client-1',
        client_name: 'ООО Ромашка',
        product_id: 'p-1',
        product_code: 'SKU-1',
        product_name: 'Товар 1',
        unit: 'шт',
        month: 12,
        quantity: '10.000',
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

describe('AnnualSalesPlanPage', () => {
  it('коммерческий директор отправляет годовой план на финальное согласование', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST **/annual-sales-plans': { body: annual({ status: 'on_review' }) },
      '/annual-sales-plans': { body: annual() },
    })
    render(<AnnualSalesPlanPage user={COMMERCIAL} />)

    expect(await screen.findByTestId('annual-status')).toHaveTextContent('Не отправлен')
    expect(screen.getByTestId('annual-managers')).toHaveTextContent('Иван Петров')
    expect(screen.getByTestId('annual-items')).toHaveTextContent('SKU-1')
    await user.click(screen.getByRole('button', { name: 'Отправить на финальное согласование' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/annual-sales-plans/'))).toBe(true)
    })
  })

  it('генеральный директор финально согласует план', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST **/annual-sales-plans': { body: annual({ status: 'approved' }) },
      '/annual-sales-plans': {
        body: annual({ status: 'on_review', status_title: 'На финальном согласовании' }),
      },
    })
    render(<AnnualSalesPlanPage user={EXECUTIVE} />)

    expect(await screen.findByTestId('annual-status')).toHaveTextContent(
      'На финальном согласовании',
    )
    await user.click(screen.getByRole('button', { name: 'Утвердить' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/annual-sales-plans/'))).toBe(true)
    })
  })

  it('показывает, что нет плана у менеджера и отправка недоступна', async () => {
    mockApi({
      '/annual-sales-plans': {
        body: annual({
          all_approved: false,
          missing_managers: ['Менеджер по продажам 3 (демо)'],
        }),
      },
    })
    render(<AnnualSalesPlanPage user={COMMERCIAL} />)

    expect(await screen.findByTestId('annual-missing')).toHaveTextContent('Менеджер по продажам 3')
    expect(screen.queryByRole('button', { name: 'Отправить на финальное согласование' })).toBeNull()
  })

  it('менеджер и закупки видят план только на чтение', async () => {
    mockApi({
      '/annual-sales-plans': {
        body: annual({ status: 'approved', status_title: 'Финально согласован' }),
      },
    })
    render(<AnnualSalesPlanPage user={SALES} />)

    expect(await screen.findByTestId('annual-status')).toHaveTextContent('Финально согласован')
    expect(screen.queryByRole('button', { name: 'Утвердить' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Отправить на финальное согласование' })).toBeNull()
    expect(screen.getByTestId('annual-items')).toBeInTheDocument()
  })

  it('показывает предупреждение об изменении состава планов', async () => {
    mockApi({
      '/annual-sales-plans': {
        body: annual({
          status: 'approved',
          status_title: 'Финально согласован',
          is_stale: true,
        }),
      },
    })
    render(<AnnualSalesPlanPage user={EXECUTIVE} />)

    expect(await screen.findByTestId('annual-stale')).toHaveTextContent('нужно повторное финальное')
    expect(screen.getByRole('button', { name: 'Вернуть в работу' })).toBeInTheDocument()
  })
})
