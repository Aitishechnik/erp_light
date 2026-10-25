import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MonthResult, MonthRow, Product, SessionUser } from './api'
import { mockApi } from './apiMock'
import { MonthResultsPage } from './MonthResultsPage'

const COMMERCIAL: SessionUser = {
  id: 'u1',
  login: 'commercial',
  full_name: 'Коммерческий директор (демо)',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
}

const PURCHASE: SessionUser = { ...COMMERCIAL, id: 'u2', role: 'purchase_director' }

const PRODUCTS: Product[] = [
  {
    id: 'p9',
    code: 'ТОВ1',
    name: 'Загадочный товар, вес',
    kind: 'finished',
    unit: 'кг',
    source: '1c',
    is_active: true,
  },
]

const RESULT: MonthResult = {
  year: 2026,
  month: 10,
  plan_approved: true,
  rows: [
    {
      client_id: 'c1',
      client_name: 'Азбука Вкуса',
      manager_id: 'm1',
      manager_name: 'Менеджер по продажам (демо)',
      product_id: 'p1',
      product_name: 'Финики',
      unit: 'кг',
      plan_quantity: '100.000',
      fact_quantity: '80.000',
      fact_amount: '8000.00',
      deviation: '-20.000',
      group: 'plan',
      manager_mismatch: false,
    },
    {
      client_id: 'c1',
      client_name: 'Азбука Вкуса',
      manager_id: 'm1',
      manager_name: 'Менеджер по продажам (демо)',
      product_id: 'p2',
      product_name: 'Курага',
      unit: 'кг',
      plan_quantity: '5.000',
      fact_quantity: '0.000',
      fact_amount: '0.00',
      deviation: '-5.000',
      group: 'short',
      manager_mismatch: false,
    },
    {
      client_id: 'c1',
      client_name: 'Азбука Вкуса',
      manager_id: 'm1',
      manager_name: 'Менеджер по продажам (демо)',
      product_id: 'p3',
      product_name: 'Арахис',
      unit: 'кг',
      plan_quantity: '0.000',
      fact_quantity: '20.000',
      fact_amount: '2000.00',
      deviation: '20.000',
      group: 'extra',
      manager_mismatch: false,
    },
  ],
  unmatched: [
    {
      id: 'u-1',
      source_name: 'Загадочный товар',
      client_name: 'Азбука Вкуса',
      quantity: '1.000',
      amount_rub: '10.00',
    },
  ],
  lines: 3,
  deviation_lines: 3,
  extra_lines: 1,
  short_lines: 1,
  fact_amount: '10000.00',
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function setup(result: MonthResult = RESULT, user: SessionUser = COMMERCIAL) {
  mockApi({
    'month-results': { body: result },
    '/api/v1/products': { body: PRODUCTS },
    'POST /api/v1/month-results/': { body: { matched: 1, remaining: 0 } },
  })
  return render(<MonthResultsPage user={user} />)
}

describe('Итоги месяца', () => {
  it('показывает план, факт, отклонение и группы', async () => {
    setup()
    await screen.findByTestId('month-table')

    expect(screen.getByTestId('month-summary')).toHaveTextContent('Строк: 3')
    expect(screen.getByTestId('month-summary')).toHaveTextContent('вне плана: 1')
    expect(screen.getByTestId('month-summary')).toHaveTextContent('не продано: 1')

    const table = screen.getByTestId('month-table')
    expect(within(table).getByText('Финики')).toBeInTheDocument()
    expect(within(table).getByText('-20')).toBeInTheDocument()
    expect(within(table).getByText('80,0 %')).toBeInTheDocument()
    expect(within(table).getByText('вне плана')).toBeInTheDocument()
    expect(within(table).getByText('не продано')).toBeInTheDocument()
  })

  it('показывает сводку по менеджерам, когда их несколько', async () => {
    const second: MonthRow = {
      client_id: 'c2',
      client_name: 'Вкус Вилл',
      manager_id: 'm2',
      manager_name: 'Менеджер по продажам 2 (демо)',
      product_id: 'p4',
      product_name: 'Изюм',
      unit: 'кг',
      plan_quantity: '10.000',
      fact_quantity: '10.000',
      fact_amount: '1000.00',
      deviation: '0.000',
      group: 'plan',
      manager_mismatch: false,
    }
    setup({ ...RESULT, rows: [...RESULT.rows, second], lines: 4, deviation_lines: 4 })
    const managers = await screen.findByTestId('manager-summary')
    expect(within(managers).getByText('Менеджер по продажам (демо)')).toBeInTheDocument()
    expect(within(managers).getByText('Менеджер по продажам 2 (демо)')).toBeInTheDocument()
  })

  it('сопоставляет неопознанную строку с номенклатурой', async () => {
    const user = userEvent.setup()
    setup()
    const box = await screen.findByTestId('unmatched-box')
    expect(box).toHaveTextContent('Не сопоставлено с номенклатурой: 1')

    await user.selectOptions(within(box).getByRole('combobox'), 'p9')
    await user.click(within(box).getByRole('button', { name: 'Сопоставить' }))

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls
      const matchCall = calls.find(
        ([url, init]) =>
          String(url).includes('/month-results/') &&
          (init?.method ?? 'GET').toUpperCase() === 'POST',
      )
      expect(matchCall).toBeTruthy()
      expect(String(matchCall?.[1]?.body)).toContain('"product_id":"p9"')
      expect(String(matchCall?.[1]?.body)).toContain('"unmatched_id":"u-1"')
    })
  })

  it('не даёт закупкам ставить сопоставление', async () => {
    setup(RESULT, PURCHASE)
    const box = await screen.findByTestId('unmatched-box')
    expect(within(box).getByRole('button', { name: 'Сопоставить' })).toBeDisabled()
  })

  it('предупреждает, если плана на год нет', async () => {
    setup({ ...RESULT, plan_approved: false })
    expect(await screen.findByText(/нет утверждённого плана продаж/)).toBeInTheDocument()
  })

  it('подсказывает загрузить выгрузку, когда строк нет', async () => {
    setup({
      ...RESULT,
      rows: [],
      unmatched: [],
      lines: 0,
      deviation_lines: 0,
      extra_lines: 0,
      short_lines: 0,
      fact_amount: '0.00',
    })
    expect(await screen.findByTestId('month-empty')).toHaveTextContent(
      'Загрузите выгрузку «Продажи за месяц»',
    )
  })
})
