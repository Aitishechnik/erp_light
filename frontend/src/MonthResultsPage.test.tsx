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
  without_reason: 3,
  reason_options: [
    { code: 'return', title: 'Возврат клиента' },
    { code: 'quality', title: 'Качество продукции' },
    { code: 'other', title: 'Другое' },
  ],
  fact_amount: '10000.00',
  status: 'open',
  closed_by_name: null,
  closed_at: null,
  reopen_reason: null,
  decision: null,
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
      without_reason: 0,
      fact_amount: '0.00',
    })
    expect(await screen.findByTestId('month-empty')).toHaveTextContent(
      'Загрузите выгрузку «Продажи за месяц»',
    )
  })
})

describe('Причины отклонений', () => {
  const WITH_REASON = {
    ...RESULT,
    rows: RESULT.rows.map((row, index) =>
      index === 0
        ? {
            ...row,
            reason: {
              code: 'quality',
              title: 'Качество продукции',
              comment: 'горчит',
              author_name: 'Коммерческий директор',
              updated_at: '2026-10-26T10:00:00Z',
            },
          }
        : row,
    ),
    without_reason: 2,
  }

  it('ставит причину из редактора строки', async () => {
    const user = userEvent.setup()
    setup()
    await screen.findByTestId('month-table')

    const [addReason] = screen.getAllByRole('button', { name: '+ причина' })
    if (!addReason) throw new Error('нет кнопки «+ причина»')
    await user.click(addReason)
    const editor = screen.getByLabelText('Причина отклонения')
    await user.selectOptions(editor, 'quality')
    await user.type(screen.getByLabelText('Комментарий к причине'), 'горчит')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(([, init]) => (init?.method ?? 'GET').toUpperCase() === 'PUT')
      expect(call).toBeTruthy()
      const body = JSON.parse(String(call?.[1]?.body)) as Record<string, string>
      expect(body.reason).toBe('quality')
      expect(body.comment).toBe('горчит')
      expect(body.client_id).toBe('c1')
    })
  })

  it('показывает причину и снимает её', async () => {
    const user = userEvent.setup()
    setup(WITH_REASON)
    const table = await screen.findByTestId('month-table')
    expect(within(table).getByText('Качество продукции')).toBeInTheDocument()

    await user.click(within(table).getByRole('button', { name: 'Качество продукции' }))
    await user.click(screen.getByRole('button', { name: 'Убрать' }))

    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(
          ([url, init]) =>
            (init?.method ?? 'GET').toUpperCase() === 'DELETE' &&
            String(url).includes('/month-results/') &&
            String(url).includes('client_id=c1'),
        )
      expect(call).toBeTruthy()
    })
  })

  it('закупки не ставят причину, но видят её', async () => {
    setup(WITH_REASON, PURCHASE)
    const table = await screen.findByTestId('month-table')
    expect(within(table).getByText('Качество продукции')).toBeInTheDocument()
    expect(within(table).queryByRole('button', { name: '+ причина' })).toBeNull()
    expect(within(table).getByRole('button', { name: 'Качество продукции' })).toBeDisabled()
  })

  it('фильтр «без причины» оставляет только строки с отклонением без объяснения', async () => {
    const user = userEvent.setup()
    setup(WITH_REASON)
    await screen.findByTestId('month-table')
    const checkbox = screen.getByLabelText('без причины')
    await user.click(checkbox)
    expect(checkbox).toBeChecked()
    const table = screen.getByTestId('month-table')
    expect(within(table).queryByText('Качество продукции')).toBeNull()
    expect(within(table).getAllByRole('button', { name: '+ причина' })).toHaveLength(2)
  })
})

describe('Закрытие месяца и решение', () => {
  function setupState(result: MonthResult, user: SessionUser = COMMERCIAL) {
    mockApi({
      'POST /api/v1/month-results/': { body: result },
      'PUT /api/v1/month-results/': { body: result },
      'month-results': { body: result },
      '/api/v1/products': { body: PRODUCTS },
    })
    return render(<MonthResultsPage user={user} />)
  }

  const CLOSED: MonthResult = {
    ...RESULT,
    status: 'closed',
    closed_by_name: 'Коммерческий директор (демо)',
    closed_at: '2026-10-26T10:00:00Z',
  }

  it('закрывает месяц через подтверждение', async () => {
    const user = userEvent.setup()
    setupState(RESULT)
    const state = await screen.findByTestId('month-state')
    expect(state).toHaveTextContent('месяц открыт')

    await user.click(screen.getByRole('button', { name: 'Закрыть месяц' }))
    const confirm = screen.getByTestId('close-confirm')
    expect(confirm).toHaveTextContent('без причины: 3')

    await user.click(within(confirm).getByRole('button', { name: 'Закрыть месяц' }))
    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(
          ([url, init]) =>
            (init?.method ?? 'GET').toUpperCase() === 'POST' && String(url).includes('/close'),
        )
      expect(call).toBeTruthy()
    })
  })

  it('закрытый месяц только читается, открывается с причиной', async () => {
    const user = userEvent.setup()
    setupState(CLOSED)
    const state = await screen.findByTestId('month-state')
    expect(state).toHaveTextContent('месяц закрыт')
    expect(screen.queryByRole('button', { name: 'Закрыть месяц' })).toBeNull()
    expect(screen.getByText(/Снимок зафиксирован/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Открыть заново' }))
    const form = screen.getByTestId('reopen-form')
    const submit = within(form).getByRole('button', { name: 'Открыть заново' })
    expect(submit).toBeDisabled()

    await user.type(within(form).getByLabelText('Причина повторного открытия'), 'ошибка выгрузки')
    await user.click(submit)
    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(
          ([url, init]) =>
            (init?.method ?? 'GET').toUpperCase() === 'POST' && String(url).includes('/reopen'),
        )
      expect(call).toBeTruthy()
      expect(String(call?.[1]?.body)).toContain('ошибка выгрузки')
    })
  })

  it('сохраняет решение с месяцем переноса', async () => {
    const user = userEvent.setup()
    setupState(RESULT)
    await screen.findByTestId('month-decision')

    await user.selectOptions(screen.getByLabelText('Решение месяца'), 'transfer_sales')
    await user.selectOptions(screen.getByLabelText('Месяц переноса'), '2026-12')
    await user.type(screen.getByLabelText('Комментарий к решению'), 'перенести на декабрь')
    await user.click(screen.getByRole('button', { name: 'Сохранить решение' }))

    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(
          ([url, init]) =>
            (init?.method ?? 'GET').toUpperCase() === 'PUT' && String(url).includes('/decision'),
        )
      expect(call).toBeTruthy()
      const body = JSON.parse(String(call?.[1]?.body)) as Record<string, unknown>
      expect(body.decision).toBe('transfer_sales')
      expect(body.target_year).toBe(2026)
      expect(body.target_month).toBe(12)
      expect(body.comment).toBe('перенести на декабрь')
    })
  })

  it('закупки не закрывают месяц и не решают за продажи', async () => {
    setupState(RESULT, PURCHASE)
    await screen.findByTestId('month-state')
    expect(screen.queryByRole('button', { name: 'Закрыть месяц' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Сохранить решение' })).toBeNull()
  })
})
