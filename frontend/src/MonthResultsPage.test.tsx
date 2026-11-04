import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MonthHistoryItem, MonthResult, MonthRow, Product, SessionUser } from './api'
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
const ADMIN: SessionUser = {
  ...COMMERCIAL,
  id: 'u3',
  role: 'executive_director',
  role_title: 'Исполнительный директор',
}

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

  it('администратор ставит причину по любой строке', async () => {
    const user = userEvent.setup()
    setup(RESULT, ADMIN)
    const table = await screen.findByTestId('month-table')

    const [addReason] = within(table).getAllByRole('button', { name: '+ причина' })
    if (!addReason) throw new Error('нет кнопки «+ причина»')
    await user.click(addReason)
    await user.selectOptions(screen.getByLabelText('Причина отклонения'), 'quality')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(([, init]) => (init?.method ?? 'GET').toUpperCase() === 'PUT')
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

  it('на закрытом месяце причину не поменять', async () => {
    const user = userEvent.setup()
    setup({
      ...WITH_REASON,
      status: 'closed',
      closed_by_name: 'Коммерческий директор (демо)',
      closed_at: '2026-10-26T10:00:00Z',
    })
    const table = await screen.findByTestId('month-table')
    const chip = within(table).getByRole('button', { name: 'Качество продукции' })
    expect(chip).toBeDisabled()
    await user.click(chip)
    expect(screen.queryByLabelText('Причина отклонения')).toBeNull()
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

  it('объясняет отказ закрыть месяц и убирает подтверждение', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /api/v1/month-results/': {
        status: 409,
        body: { detail: 'За этот месяц нет факта продаж' },
      },
      'month-results': { body: RESULT },
      '/api/v1/products': { body: PRODUCTS },
    })
    render(<MonthResultsPage user={COMMERCIAL} />)

    await user.click(await screen.findByRole('button', { name: 'Закрыть месяц' }))
    const confirm = screen.getByTestId('close-confirm')
    await user.click(within(confirm).getByRole('button', { name: 'Закрыть месяц' }))

    expect(await screen.findByText(/нет факта продаж/)).toBeInTheDocument()
    expect(screen.queryByTestId('close-confirm')).toBeNull()
  })

  it('смена месяца убирает сообщение прошлого месяца', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /api/v1/month-results/': {
        status: 409,
        body: { detail: 'За этот месяц нет факта продаж' },
      },
      'month-results': { body: RESULT },
      '/api/v1/products': { body: PRODUCTS },
    })
    render(<MonthResultsPage user={COMMERCIAL} />)

    await user.click(await screen.findByRole('button', { name: 'Закрыть месяц' }))
    await user.click(
      within(screen.getByTestId('close-confirm')).getByRole('button', { name: 'Закрыть месяц' }),
    )
    expect(await screen.findByText(/нет факта продаж/)).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Месяц итогов'), '9')
    await waitFor(() => expect(screen.queryByText(/нет факта продаж/)).toBeNull())
  })

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

  it('создаёт черновики корректировок из решения о переносе', async () => {
    const user = userEvent.setup()
    const closedTransfer: MonthResult = {
      ...RESULT,
      status: 'closed',
      closed_by_name: 'Коммерческий директор (демо)',
      closed_at: '2026-10-26T10:00:00Z',
      decision: {
        code: 'transfer_sales',
        title: 'Перенести в план продаж',
        comment: null,
        target_year: 2026,
        target_month: 11,
        author_name: 'Коммерческий директор (демо)',
        at: '2026-10-26T10:00:00Z',
      },
    }
    mockApi({
      'POST /api/v1/month-results/': {
        body: {
          created: [
            {
              manager_name: 'Менеджер по продажам (демо)',
              plan_id: 'plan-1',
              correction_id: 'corr-1',
              lines: 2,
              quantity: '120.000',
            },
          ],
          skipped: [
            {
              manager_name: 'Менеджер по продажам 2 (демо)',
              reason: 'уже есть открытая корректировка',
            },
          ],
        },
      },
      'month-results': { body: closedTransfer },
      '/api/v1/products': { body: PRODUCTS },
    })
    render(<MonthResultsPage user={COMMERCIAL} />)

    await user.click(await screen.findByRole('button', { name: 'Создать корректировки' }))
    const result = await screen.findByTestId('transfer-result')
    expect(result).toHaveTextContent('Менеджер по продажам (демо) — 2 стр., 120 ед.')
    expect(result).toHaveTextContent('уже есть открытая корректировка')

    const call = vi
      .mocked(fetch)
      .mock.calls.find(
        ([url, init]) =>
          (init?.method ?? 'GET').toUpperCase() === 'POST' &&
          String(url).includes('/transfer-draft'),
      )
    expect(call).toBeTruthy()
  })

  it('закупки не закрывают месяц и не решают за продажи', async () => {
    setupState(RESULT, PURCHASE)
    await screen.findByTestId('month-state')
    expect(screen.queryByRole('button', { name: 'Закрыть месяц' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Сохранить решение' })).toBeNull()
  })
})

describe('Загрузка продаж с экрана отчёта', () => {
  const SESSION = {
    id: 's-1',
    kind: 'sales',
    kind_title: 'Продажи за месяц',
    file_name: 'Продажи_Окт.xlsx',
    status: 'ok',
    rows_total: 2,
    rows_created: 2,
    rows_updated: 0,
    rows_skipped: 0,
    rows_failed: 0,
    message: null,
    created_at: '2026-10-26T10:00:00Z',
  }

  function setupUpload(result: MonthResult = RESULT, user: SessionUser = COMMERCIAL) {
    mockApi({
      'POST /api/v1/imports/sales': { body: SESSION },
      'month-results': { body: result },
      '/api/v1/products': { body: PRODUCTS },
    })
    return render(<MonthResultsPage user={user} />)
  }

  function file(): File {
    return new File(['xlsx'], 'Продажи_Окт.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
  }

  it('грузят только коммерческий и исполнительный директор', async () => {
    const { unmount } = setupUpload()
    expect(await screen.findByRole('button', { name: 'Загрузить продажи' })).toBeInTheDocument()
    unmount()

    setupUpload(RESULT, PURCHASE)
    await screen.findByTestId('month-state')
    expect(screen.queryByRole('button', { name: 'Загрузить продажи' })).toBeNull()
  })

  it('загружает файл с уточнённым периодом и обновляет отчёт', async () => {
    const user = userEvent.setup()
    setupUpload()
    await user.click(await screen.findByRole('button', { name: 'Загрузить продажи' }))

    const form = screen.getByTestId('upload-form')
    await user.upload(within(form).getByLabelText('Файл продаж за месяц'), file())
    await user.type(within(form).getByLabelText('Год в файле'), '2026')
    await user.type(within(form).getByLabelText('Месяц в файле'), '11')
    await user.click(within(form).getByRole('button', { name: 'Загрузить' }))

    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(
          ([url, init]) =>
            (init?.method ?? 'GET').toUpperCase() === 'POST' &&
            String(url).includes('/imports/sales'),
        )
      expect(call).toBeTruthy()
      expect(String(call?.[0])).toContain('?year=2026&month=11')
    })
    expect(await screen.findByText(/Выгрузка принята: строк 2/)).toBeInTheDocument()
    expect(screen.queryByTestId('upload-form')).toBeNull()
  })

  it('не отправляет файл, если уточнён только один параметр периода', async () => {
    const user = userEvent.setup()
    setupUpload()
    await user.click(await screen.findByRole('button', { name: 'Загрузить продажи' }))

    const form = screen.getByTestId('upload-form')
    await user.upload(within(form).getByLabelText('Файл продаж за месяц'), file())
    await user.type(within(form).getByLabelText('Год в файле'), '2026')
    await user.click(within(form).getByRole('button', { name: 'Загрузить' }))

    expect(await screen.findByText(/Укажите и год, и месяц/)).toBeInTheDocument()
    const uploaded = vi
      .mocked(fetch)
      .mock.calls.some(
        ([url, init]) =>
          (init?.method ?? 'GET').toUpperCase() === 'POST' &&
          String(url).includes('/imports/sales'),
      )
    expect(uploaded).toBe(false)
  })

  it('на закрытом месяце поясняет, что загрузка недоступна', async () => {
    setupUpload({
      ...RESULT,
      status: 'closed',
      closed_by_name: 'Коммерческий директор (демо)',
      closed_at: '2026-10-26T10:00:00Z',
    })
    expect(await screen.findByText(/Месяц закрыт — выгрузку продаж не принять/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Загрузить продажи' })).toBeNull()
  })
})

describe('Сводка по менеджерам', () => {
  it('считает строки, отклонения, причины и деньги по менеджеру', async () => {
    setup()
    const row = await screen.findByTestId('manager-row-m1')
    const cells = within(row).getAllByRole('cell')
    expect(cells[1]).toHaveTextContent('3')
    expect(cells[2]).toHaveTextContent('3')
    expect(cells[3]).toHaveTextContent('1')
    expect(cells[4]).toHaveTextContent('1')
    expect(cells[5]).toHaveTextContent('3')
    expect(cells[6]).toHaveTextContent(/10\s?000,00/)
  })

  it('раскрывается до клиента и позиций', async () => {
    const user = userEvent.setup()
    setup()
    const summary = await screen.findByTestId('manager-summary')
    expect(within(summary).queryByTestId('client-row-m1:c1')).toBeNull()

    await user.click(within(summary).getByTestId('manager-toggle-m1'))
    const clientRow = screen.getByTestId('client-row-m1:c1')
    expect(clientRow).toHaveTextContent('Азбука Вкуса')

    await user.click(within(clientRow).getByTestId('client-toggle-m1:c1'))
    const products = screen.getByTestId('summary-products-m1:c1')
    expect(within(products).getByText('Финики')).toBeInTheDocument()
    expect(within(products).getByText('-20')).toBeInTheDocument()
    expect(within(products).getByText('80,0 %')).toBeInTheDocument()
  })

  it('фильтр по группе оставляет строки одного вида', async () => {
    const user = userEvent.setup()
    setup()
    const table = await screen.findByTestId('month-table')

    await user.selectOptions(screen.getByLabelText('Группа'), 'short')
    expect(within(table).getByText('Курага')).toBeInTheDocument()
    expect(within(table).queryByText('Финики')).toBeNull()
    expect(within(table).queryByText('Арахис')).toBeNull()

    await user.selectOptions(screen.getByLabelText('Группа'), 'extra')
    expect(within(table).getByText('Арахис')).toBeInTheDocument()
    expect(within(table).queryByText('Курага')).toBeNull()
  })
})

const SALES_MANAGER: SessionUser = {
  ...COMMERCIAL,
  id: 'u4',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

const HISTORY: MonthHistoryItem[] = [
  {
    version: 1,
    closed_at: '2026-10-26T10:00:00Z',
    closed_by_name: 'Коммерческий директор (демо)',
    totals: {
      lines: 3,
      deviation_lines: 3,
      extra_lines: 1,
      short_lines: 1,
      without_reason: 3,
      fact_amount: '10000.00',
    },
    decision: null,
  },
  {
    version: 2,
    closed_at: '2026-10-27T10:00:00Z',
    closed_by_name: 'Исполнительный директор (демо)',
    totals: {
      lines: 3,
      deviation_lines: 2,
      extra_lines: 1,
      short_lines: 1,
      without_reason: 1,
      fact_amount: '9000.00',
    },
    decision: {
      code: 'transfer_sales',
      title: 'Перенести в план продаж',
      target_year: 2026,
      target_month: 11,
      author_name: 'Коммерческий директор (демо)',
      at: '2026-10-27T09:00:00Z',
    },
  },
]

describe('История закрытий', () => {
  const CLOSED: MonthResult = {
    ...RESULT,
    status: 'closed',
    closed_by_name: 'Коммерческий директор (демо)',
    closed_at: '2026-10-26T10:00:00Z',
  }

  function setupHistory(
    result: MonthResult = CLOSED,
    user: SessionUser = COMMERCIAL,
    items: MonthHistoryItem[] = HISTORY,
  ) {
    mockApi({
      'GET /history': { body: items },
      'month-results': { body: result },
      '/api/v1/products': { body: PRODUCTS },
    })
    return render(<MonthResultsPage user={user} />)
  }

  it('показывает версии снимков и решение месяца', async () => {
    const user = userEvent.setup()
    setupHistory()
    await user.click(await screen.findByRole('button', { name: 'История закрытий' }))

    const table = await screen.findByTestId('history-table')
    await waitFor(() => expect(within(table).getByText('Версия')).toBeInTheDocument())
    expect(within(table).getByTestId('history-version-1')).toHaveTextContent('—')
    const second = within(table).getByTestId('history-version-2')
    expect(second).toHaveTextContent('Перенести в план продаж → Ноябрь 2026')
    expect(second).toHaveTextContent(/9\s?000,00/)
  })

  it('смена месяца закрывает историю и запрашивает её заново', async () => {
    const user = userEvent.setup()
    setupHistory()
    await user.click(await screen.findByRole('button', { name: 'История закрытий' }))
    await screen.findByTestId('history-table')

    await user.selectOptions(screen.getByLabelText('Месяц итогов'), '9')
    await waitFor(() => expect(screen.queryByTestId('history-table')).toBeNull())
    expect(screen.getByRole('button', { name: 'История закрытий' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'История закрытий' }))
    expect(await screen.findByTestId('history-table')).toBeInTheDocument()
  })

  it('менеджеру продаж историю не показывает', async () => {
    setupHistory(CLOSED, SALES_MANAGER)
    await screen.findByTestId('month-state')
    expect(screen.queryByRole('button', { name: 'История закрытий' })).toBeNull()
  })

  it('закупки видят историю, пустая история объясняется', async () => {
    setupHistory(CLOSED, PURCHASE, [])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'История закрытий' }))
    expect(await screen.findByText('Закрытий ещё не было.')).toBeInTheDocument()
  })
})
