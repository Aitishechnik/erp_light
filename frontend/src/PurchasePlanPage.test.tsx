import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  Counterparty,
  Country,
  Product,
  PurchasePlan,
  PurchasePlanPosition,
  SessionUser,
} from './api'
import { mockApi } from './apiMock'
import { PurchasePlanPage } from './PurchasePlanPage'

const YEAR = new Date().getFullYear()

const DIRECTOR: SessionUser = {
  id: 'pd-1',
  login: 'purchase',
  full_name: 'Пётр Закупщиков',
  role: 'purchase_director',
  role_title: 'Директор по закупкам',
}

const EXECUTIVE: SessionUser = {
  id: 'ed-1',
  login: 'executive',
  full_name: 'Ольга Директорова',
  role: 'executive_director',
  role_title: 'Исполнительный директор',
}

const PRODUCTS: Product[] = [
  {
    id: 'raw-1',
    code: 'RAW-1',
    name: 'Орех грецкий, вес',
    kind: 'raw',
    unit: 'кг',
    source: '1c',
    is_active: true,
  },
  {
    id: 'raw-2',
    code: 'RAW-2',
    name: 'Кокосовая стружка',
    kind: 'raw',
    unit: 'кг',
    source: '1c',
    is_active: true,
  },
]

const SUPPLIERS: Counterparty[] = [
  {
    id: 'sup-1',
    name: 'ООО Импорт',
    inn: null,
    note: null,
    is_customer: false,
    is_local_supplier: false,
    is_import_supplier: true,
    source: '1c',
    is_active: true,
  },
]

const COUNTRIES: Country[] = [
  { id: 'th-1', name: 'Таиланд', delivery_days: 90, is_active: true, source: 'manual' },
  { id: 'cn-1', name: 'Китай', delivery_days: 65, is_active: true, source: 'manual' },
]

const POSITION: PurchasePlanPosition = {
  product_id: 'fin-1',
  code: 'FIN-1',
  name: 'Смесь ореховая, 100 гр',
  unit: 'шт',
  total: '300.000',
  months: [
    { month: 1, quantity: '100.000' },
    { month: 2, quantity: '200.000' },
  ],
  decomposed: true,
  status: 'ok',
  changed: false,
}

function plan(overrides: Partial<PurchasePlan> = {}): PurchasePlan {
  return {
    id: 'plan-1',
    year: YEAR,
    status: 'draft',
    status_title: 'Черновик',
    created_by_name: 'Директор по закупкам',
    approved_by_name: null,
    approved_at: null,
    notes: null,
    created_at: '2026-10-21T10:00:00Z',
    updated_at: '2026-10-21T10:00:00Z',
    editable_months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    source: {
      state: 'ok',
      title: 'План продаж не менялся с момента составления плана закупок',
      annual_status_title: 'Финально согласован',
      annual_approved_at: '2026-10-21T18:00:00Z',
      snapshot_at: '2026-10-21T18:10:00Z',
      acknowledged_at: '2026-10-21T18:10:00Z',
      changes: [],
      history: [],
      revision_requested_at: null,
      revision_requested_by_name: null,
    },
    positions: [POSITION],
    items: [
      {
        id: 'item-1',
        sales_product_id: 'fin-1',
        product_id: 'raw-1',
        product_code: 'RAW-1',
        product_name: 'Орех грецкий, вес',
        product_kind: 'raw',
        unit: 'кг',
        country_id: 'th-1',
        country_name: 'Таиланд',
        delivery_days: 90,
        quantity: '30.000',
        price_rub: '500.00',
        supplier_id: 'sup-1',
        supplier_name: 'ООО Импорт',
        notes: null,
        schedule: [
          {
            month: 1,
            quantity: '10.000',
            order_year: YEAR - 1,
            order_month: 10,
            overdue: false,
          },
          {
            month: 2,
            quantity: '20.000',
            order_year: YEAR - 1,
            order_month: 11,
            overdue: false,
          },
        ],
      },
    ],
    ...overrides,
  }
}

function routes(
  planBody: PurchasePlan[] = [plan()],
  extra: Record<string, { status?: number; body?: unknown }> = {},
) {
  // Метод-специфичные маршруты идут раньше общего списка, иначе PUT/approve
  // перехватит маршрут «/api/v1/purchase-plans» без метода.
  return {
    ...extra,
    '/api/v1/products': { body: PRODUCTS },
    '/api/v1/counterparties': { body: SUPPLIERS },
    '/api/v1/countries': { body: COUNTRIES },
    '/api/v1/purchase-plans': { body: planBody },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function calls(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) => String(call[0]))
}

function bodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) => JSON.stringify(call[1] ?? {}))
}

function postBodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: [string, RequestInit?][] } }
  return mock.mock.calls
    .filter(([, init]) => init?.method === 'POST')
    .map(([, init]) => String(init?.body ?? ''))
}

function putBodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: [string, RequestInit?][] } }
  return mock.mock.calls
    .filter(([, init]) => init?.method === 'PUT')
    .map(([, init]) => String(init?.body ?? ''))
}

describe('PurchasePlanPage', () => {
  it('показывает потребность из плана продаж и сохраняет строку сырья', async () => {
    const user = userEvent.setup()
    mockApi(routes([plan()], { 'PUT /api/v1/purchase-plans/plan-1/items': { body: plan() } }))
    render(<PurchasePlanPage user={DIRECTOR} />)

    expect(await screen.findByTestId('purchase-status')).toHaveTextContent('Черновик')
    expect(screen.getByTestId('position-FIN-1')).toHaveTextContent('300')
    expect(screen.getByTestId('position-FIN-1')).toHaveTextContent('FIN-1 · Смесь ореховая')
    expect(screen.getByTestId('position-FIN-1')).toHaveTextContent('разложено')
    expect(await screen.findByLabelText('Количество FIN-1 1')).toHaveValue('30')
    expect(screen.getByTestId('purchase-plan-card')).toHaveTextContent(/15\s*000,00/)
    // График: 10 кг на январь и 20 кг на февраль, заказ за 90 дней до потребности.
    const table = screen.getByTestId('purchase-table')
    expect(table).toHaveTextContent('янв 10')
    expect(table).toHaveTextContent('фев 20')

    await user.click(screen.getByRole('button', { name: 'Добавить сырьё FIN-1' }))
    await user.selectOptions(screen.getByLabelText('Сырьё FIN-1 2'), 'raw-2')
    await user.selectOptions(screen.getByLabelText('Страна FIN-1 2'), 'cn-1')
    await user.type(screen.getByLabelText('Количество FIN-1 2'), '12,5')
    await user.type(screen.getByLabelText('Цена FIN-1 2'), '300.25')
    await user.selectOptions(screen.getByLabelText('Поставщик FIN-1 2'), 'sup-1')

    await user.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/purchase-plans/plan-1/items'))).toBe(true)
    })
    const sent = putBodies().find((body) => body.includes('"items"'))
    expect(sent).toBeDefined()
    expect(sent).toContain('"sales_product_id":"fin-1"')
    expect(sent).toContain('"product_id":"raw-2"')
    expect(sent).toContain('"country_id":"cn-1"')
    expect(sent).toContain('"quantity":"12.5"')
    expect(sent).toContain('"price_rub":"300.25"')
    expect(await screen.findByTestId('purchase-saved')).toHaveTextContent('План сохранён')
  })

  it('показывает diff пересмотренного плана продаж и принимает его к сведению', async () => {
    const user = userEvent.setup()
    const changed = plan({
      positions: [
        {
          ...POSITION,
          changed: true,
          total: '350.000',
          months: [
            { month: 1, quantity: '150.000' },
            { month: 2, quantity: '200.000' },
          ],
        },
      ],
      source: {
        ...plan().source,
        state: 'changed',
        title: 'План продаж пересмотрен после составления плана закупок',
        changes: [
          {
            product_id: 'fin-1',
            code: 'FIN-1',
            name: 'Смесь ореховая, 100 гр',
            unit: 'шт',
            month: 1,
            was: '100.000',
            now: '150.000',
            kind: 'changed',
          },
        ],
      },
    })
    mockApi(
      routes([changed], {
        'POST /api/v1/purchase-plans/plan-1/acknowledge-source': { body: changed },
      }),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    expect(await screen.findByTestId('source-alert')).toHaveTextContent('План продаж пересмотрен')
    expect(screen.getByTestId('position-FIN-1')).toHaveTextContent('изменено')
    expect(screen.getByRole('button', { name: 'Отправить на согласование' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Показать изменения' }))
    expect(screen.getByTestId('source-changes')).toHaveTextContent('150')
    expect(screen.getByTestId('source-changes')).toHaveTextContent('+50')

    await user.click(screen.getByTestId('source-ack'))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/acknowledge-source'))).toBe(true)
    })
    expect(await screen.findByTestId('purchase-saved')).toHaveTextContent(
      'Изменения плана продаж приняты к сведению',
    )
  })

  it('исполнительный директор утверждает план на проверке', async () => {
    const user = userEvent.setup()
    mockApi(
      routes([plan({ status: 'on_review', status_title: 'На проверке' })], {
        'POST /api/v1/purchase-plans/plan-1/approve': { body: plan({ status: 'approved' }) },
      }),
    )
    render(<PurchasePlanPage user={EXECUTIVE} />)

    expect(await screen.findByTestId('purchase-status')).toHaveTextContent('На проверке')
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Утвердить' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/purchase-plans/plan-1/approve'))).toBe(true)
    })
  })

  it('на черновике исполнительный директор только смотрит', async () => {
    mockApi(routes())
    render(<PurchasePlanPage user={EXECUTIVE} />)

    expect(await screen.findByTestId('purchase-status')).toHaveTextContent('Черновик')
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Добавить сырьё FIN-1' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Количество FIN-1 1')).not.toBeInTheDocument()
  })

  it('создаёт план на год, если его ещё нет', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/products': { body: PRODUCTS },
      '/api/v1/counterparties': { body: SUPPLIERS },
      '/api/v1/countries': { body: COUNTRIES },
      'POST /api/v1/purchase-plans': { body: plan() },
      '/api/v1/purchase-plans': { body: [] },
    })
    render(<PurchasePlanPage user={DIRECTOR} />)

    expect(await screen.findByTestId('purchase-no-plan')).toHaveTextContent(
      'плана закупок сырья нет',
    )
    await user.click(screen.getByRole('button', { name: `Создать план на ${YEAR}` }))
    await waitFor(() => {
      expect(postBodies().some((body) => body.includes(`"year":${YEAR}`))).toBe(true)
    })
    expect(await screen.findByTestId('purchase-saved')).toHaveTextContent('План создан')
  })

  it('за прошлый год план только для чтения', async () => {
    mockApi(routes([plan({ editable_months: [] })]))
    render(<PurchasePlanPage user={DIRECTOR} />)

    expect(await screen.findByTestId('purchase-status')).toHaveTextContent('Черновик')
    expect(screen.queryByLabelText('Количество FIN-1 1')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Добавить сырьё FIN-1' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()
  })

  it('показывает ошибку, если сервер отклонил сохранение', async () => {
    const user = userEvent.setup()
    mockApi(
      routes([plan()], {
        'PUT /api/v1/purchase-plans/plan-1/items': {
          status: 409,
          body: { detail: 'Год прошёл — план закупок доступен только для чтения' },
        },
      }),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    await screen.findByTestId('purchase-status')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Год прошёл')
  })

  it('возвращает план на доработку с причиной', async () => {
    const user = userEvent.setup()
    mockApi(
      routes([plan({ status: 'on_review', status_title: 'На проверке' })], {
        'POST /api/v1/purchase-plans/plan-1/reject': { body: plan() },
      }),
    )
    render(<PurchasePlanPage user={EXECUTIVE} />)

    await screen.findByTestId('purchase-status')
    await user.type(screen.getByLabelText('Причина'), 'уточнить цены')
    await user.click(screen.getByRole('button', { name: 'Вернуть на доработку' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/purchase-plans/plan-1/reject'))).toBe(true)
    })
    expect(bodies().find((body) => body.includes('уточнить цены'))).toBeDefined()
  })

  it('запрашивает пересмотр утверждённого плана, ГД видит просьбу', async () => {
    const user = userEvent.setup()
    const approved = plan({
      status: 'approved',
      status_title: 'Утверждён',
      approved_by_name: 'Ольга Директорова',
      source: {
        ...plan().source,
        state: 'changed',
        title: 'План продаж пересмотрен после составления плана закупок',
        changes: [
          {
            product_id: 'fin-1',
            code: 'FIN-1',
            name: 'Смесь ореховая, 100 гр',
            unit: 'шт',
            month: 1,
            was: '100.000',
            now: '150.000',
            kind: 'changed',
          },
        ],
      },
    })
    mockApi(
      routes([approved], {
        'POST /api/v1/purchase-plans/plan-1/request-revision': { body: approved },
      }),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    await screen.findByTestId('purchase-status')
    expect(screen.getByText('План утверждён — правки недоступны')).toBeInTheDocument()
    await user.click(screen.getByTestId('source-request-revision'))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/request-revision'))).toBe(true)
    })
    expect(await screen.findByTestId('purchase-saved')).toHaveTextContent(
      'Запрос на пересмотр отправлен',
    )
  })
})
