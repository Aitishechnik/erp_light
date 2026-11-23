import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MonthlyPlan, SessionUser } from './api'
import { mockApi } from './apiMock'
import { MonthlyPlanTab } from './MonthlyPlanTab'

const SALES: SessionUser = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Менеджер по продажам',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

const PLAN: MonthlyPlan = {
  year: 2026,
  month: 12,
  manager_id: 'sm-1',
  manager_name: 'Менеджер по продажам',
  status: 'draft',
  status_title: 'Черновик',
  window_start: '2026-11-23',
  window_end: '2026-11-30',
  window_state: 'open',
  can_edit: true,
  can_approve: false,
  approved_at: null,
  approved_by_name: null,
  changed_lines: 0,
  items: [
    {
      client_id: 'c-1',
      client_name: 'ООО Ромашка',
      product_id: 'p-1',
      product_code: 'SKU-1',
      product_name: 'Изюм',
      unit: 'кг',
      annual_quantity: '100.000',
      quantity: '100.000',
      reason: null,
      is_new: false,
      is_removed: false,
      updated_at: '2026-11-23T10:00:00Z',
      updated_by_name: 'Менеджер по продажам',
    },
    {
      client_id: 'c-1',
      client_name: 'ООО Ромашка',
      product_id: 'p-2',
      product_code: 'SKU-2',
      product_name: 'Курага',
      unit: 'кг',
      annual_quantity: '50.000',
      quantity: '0.000',
      reason: 'Сеть вывела позицию из торговой матрицы',
      is_new: false,
      is_removed: true,
      updated_at: '2026-11-23T10:00:00Z',
      updated_by_name: 'Менеджер по продажам',
    },
  ],
}

function routes(extra: Record<string, { status?: number; body?: unknown }> = {}) {
  return {
    '/api/v1/monthly-sales-plans/2026/12/history': { body: [] },
    '/api/v1/monthly-sales-plans?year=2026': { body: PLAN },
    '/api/v1/counterparties': { body: [] },
    '/api/v1/products': { body: [] },
    ...extra,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function putBodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: [string, RequestInit?][] } }
  return mock.mock.calls
    .filter(([, init]) => init?.method === 'PUT')
    .map(([, init]) => String(init?.body ?? ''))
}

describe('MonthlyPlanTab', () => {
  it('показывает годовой и месячный план и требует причину при снижении', async () => {
    mockApi(routes())
    render(<MonthlyPlanTab user={SALES} year={2026} managers={[]} />)
    await userEvent.selectOptions(await screen.findByLabelText('Месяц плана'), '12')

    expect(await screen.findByLabelText('Количество Изюм')).toHaveValue('100')
    expect(screen.getByText('выведена')).toBeInTheDocument()

    const input = screen.getByLabelText('Количество Изюм')
    await userEvent.clear(input)
    await userEvent.type(input, '90')

    const reason = screen.getByLabelText('Причина Изюм')
    expect(reason).toBeEnabled()

    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Укажите причину')
    expect(putBodies()).toHaveLength(0)
  })

  it('повышение выше плана сохраняется без причины', async () => {
    mockApi(
      routes({
        'PUT /api/v1/monthly-sales-plans/2026/12': {
          body: {
            ...PLAN,
            changed_lines: 1,
            items: [{ ...PLAN.items[0], quantity: '110.000', reason: null }, PLAN.items[1]],
          },
        },
      }),
    )
    render(<MonthlyPlanTab user={SALES} year={2026} managers={[]} />)
    await userEvent.selectOptions(await screen.findByLabelText('Месяц плана'), '12')

    const input = await screen.findByLabelText('Количество Изюм')
    await userEvent.clear(input)
    await userEvent.type(input, '110')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(putBodies()).toHaveLength(1))
    const body = JSON.parse(putBodies()[0] ?? '{}') as { items: { reason: string | null }[] }
    expect(body.items[0]?.reason).toBeNull()
    expect(await screen.findByText('План месяца сохранён')).toBeInTheDocument()
  })

  it('сохраняет изменённую строку с причиной', async () => {
    mockApi(
      routes({
        'PUT /api/v1/monthly-sales-plans/2026/12': {
          body: {
            ...PLAN,
            changed_lines: 1,
            items: [
              { ...PLAN.items[0], quantity: '110.000', reason: 'Клиент подтвердил' },
              PLAN.items[1],
            ],
          },
        },
      }),
    )
    render(<MonthlyPlanTab user={SALES} year={2026} managers={[]} />)
    await userEvent.selectOptions(await screen.findByLabelText('Месяц плана'), '12')

    const input = await screen.findByLabelText('Количество Изюм')
    await userEvent.clear(input)
    await userEvent.type(input, '110')
    await userEvent.type(screen.getByLabelText('Причина Изюм'), 'Клиент подтвердил')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(putBodies()).toHaveLength(1))
    const body = JSON.parse(putBodies()[0] ?? '{}') as { items: { reason: string }[] }
    expect(body.items[0]?.reason).toBe('Клиент подтвердил')
    expect(await screen.findByText('План месяца сохранён')).toBeInTheDocument()
  })

  it('не открывает план до окна пересмотра', async () => {
    mockApi(
      routes({
        '/api/v1/monthly-sales-plans?year=2026': {
          status: 409,
          body: { detail: 'Окно пересмотра ещё не открылось' },
        },
      }),
    )
    render(<MonthlyPlanTab user={SALES} year={2026} managers={[]} />)
    expect(await screen.findByText('План месяца ещё не открыт.')).toBeInTheDocument()
    expect((await screen.findAllByText(/Окно пересмотра ещё не открылось/)).length).toBeGreaterThan(
      0,
    )
  })
})
