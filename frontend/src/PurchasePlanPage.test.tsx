import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  Country,
  Product,
  PurchasePlan,
  PurchasePlanItem,
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
        alternative_of_id: null,
        sales_product_id: 'fin-1',
        sales_product_name: 'Смесь ореховая',
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
        notes: null,
        fact_quantity: '10.000',
        fact_share: '33.3',
        fact_months: [{ month: 1, quantity: '10.000' }],
        used_quantity: '0',
        used_months: [],
        carry_forward: '0',
        schedule: [
          {
            month: 1,
            quantity: '10.000',
            covered: '10.000',
            remaining: '0',
            carry: '0',
            share: '100.0',
            order_year: YEAR - 1,
            order_month: 10,
            overdue: false,
          },
          {
            month: 2,
            quantity: '20.000',
            covered: '0',
            remaining: '20.000',
            carry: '0',
            share: '0.0',
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

function planItem(overrides: Partial<PurchasePlanItem> = {}): PurchasePlanItem {
  const [first] = plan().items
  if (!first) throw new Error('в фикстуре нет строки плана')
  return { ...first, ...overrides }
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
    // Приход 10 кг из 30 виден по покрытию: январь закрыт.
    // График по умолчанию — одна строка «ближайший заказ», январь уже перекрыт приходом.
    const table = screen.getByTestId('purchase-table')
    expect(table).toHaveTextContent(
      'Ближайший заказ: к 01.11.2025 — 20 кг (потребность — февраль 2026)',
    )

    // Кнопка у позиции одна: раскрывает таблицу месяцев с заказом и фактом.
    expect(screen.getAllByRole('button', { name: 'Показать таблицей' })).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: 'Показать таблицей' }))
    const detail = await screen.findByTestId('schedule-table')
    expect(detail).toHaveTextContent('январь 2026')
    expect(detail).toHaveTextContent('Нужно, кг')
    expect(detail).toHaveTextContent('Перекрыто')
    expect(detail).toHaveTextContent('Докупить, кг')
    expect(detail).toHaveTextContent('100 %')
    // Кнопка в строке одна: после раскрытия она же называется «Скрыть таблицу».
    expect(screen.getByRole('button', { name: 'Скрыть таблицу' })).toBeInTheDocument()

    // Видов графика два: «кратко» и «кварталы»; вид «полосой» убран.
    expect(screen.queryByRole('button', { name: 'полосой' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'кварталы' }))
    expect(screen.getByTestId('schedule-quarters')).toHaveTextContent('I квартал 2026')
    expect(screen.queryByTestId('schedule-bars')).not.toBeInTheDocument()
    // В кварталах кнопка та же и там же — в строке сырья.
    expect(screen.getByRole('button', { name: 'Скрыть таблицу' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Добавить сырьё FIN-1' }))
    await user.selectOptions(screen.getByLabelText('Сырьё FIN-1 2'), 'raw-2')
    await user.selectOptions(screen.getByLabelText('Страна FIN-1 2'), 'cn-1')
    await user.type(screen.getByLabelText('Количество FIN-1 2'), '12,5')
    await user.type(screen.getByLabelText('Цена FIN-1 2'), '300.25')

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
    // Сохранённая строка уходит со своим id — ссылки поступлений не теряются.
    expect(sent).toContain('"id":"item-1"')
  })

  it('приход перекрывает следующие месяцы и не даёт больше 100 %', async () => {
    mockApi(
      routes([
        plan({
          items: [
            planItem({
              fact_months: [{ month: 1, quantity: '25.000' }],
            }),
          ],
        }),
      ]),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    await screen.findByTestId('purchase-row-item-1')
    const table = screen.getByTestId('purchase-table')
    // Январь закрыт полностью, остаток 15 кг пошёл на февраль: докупить 5 кг.
    expect(table).toHaveTextContent(
      'Ближайший заказ: к 01.11.2025 — 5 кг (потребность — февраль 2026)',
    )

    await userEvent.setup().click(screen.getByRole('button', { name: 'Показать таблицей' }))
    const detail = await screen.findByTestId('schedule-table')
    // Январь перекрыт полностью (100 %), февраль — на 15 из 20 кг: докупить 5.
    expect(detail).toHaveTextContent('январь 2026')
    expect(detail).toHaveTextContent('100 %')
    expect(detail).toHaveTextContent('75 %')

    // Та же кнопка скрывает таблицу: отдельной «Скрыть график» больше нет.
    await userEvent.setup().click(screen.getByRole('button', { name: 'Скрыть таблицу' }))
    expect(screen.queryByTestId('schedule-table')).not.toBeInTheDocument()
  })

  it('таблица раскрывается у выбранной позиции и не трогает соседние', async () => {
    const user = userEvent.setup()
    mockApi(
      routes([
        plan({
          items: [
            planItem(),
            planItem({
              id: 'item-2',
              product_id: 'raw-2',
              product_code: 'RAW-2',
              product_name: 'Кокосовая стружка',
            }),
          ],
        }),
      ]),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    await screen.findByTestId('purchase-row-item-1')
    const toggles = screen.getAllByRole('button', { name: 'Показать таблицей' })
    expect(toggles).toHaveLength(2)

    const [firstToggle] = toggles
    if (!firstToggle) throw new Error('нет кнопки таблицы у первой позиции')
    await user.click(firstToggle)
    expect(screen.getAllByTestId('schedule-table')).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Скрыть таблицу' })).toHaveLength(1)
    // У второй позиции кнопка по-прежнему «Показать таблицей» — своя на строку.
    expect(screen.getAllByRole('button', { name: 'Показать таблицей' })).toHaveLength(1)
  })

  it('когда потребность закрыта целиком, показывает перенос излишка на следующий год', async () => {
    mockApi(
      routes([
        plan({
          items: [
            planItem({
              fact_months: [{ month: 1, quantity: '42.000' }],
              carry_forward: '12.000',
            }),
          ],
        }),
      ]),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    await screen.findByTestId('purchase-row-item-1')
    const table = screen.getByTestId('purchase-table')
    expect(screen.getByLabelText('Количество FIN-1 1')).toHaveValue('30')
    expect(table).toHaveTextContent('Потребность закрыта до конца года')
    expect(table).toHaveTextContent('излишек после февраль 2026 — 12 кг, переносим на 2027 год')
  })

  it('одно сырьё на две позиции: приход считаем общим котлом', async () => {
    mockApi(
      routes([
        plan({
          positions: [
            POSITION,
            {
              ...POSITION,
              product_id: 'fin-2',
              code: 'FIN-2',
              name: 'Финики',
              total: '50.000',
              months: [{ month: 1, quantity: '50.000' }],
            },
          ],
          items: [
            planItem({
              fact_quantity: '40.000',
              fact_months: [{ month: 1, quantity: '40.000' }],
            }),
            planItem({
              id: 'item-2',
              sales_product_id: 'fin-2',
              sales_product_name: 'Финики',
              quantity: '15.000',
              fact_quantity: '0',
              fact_months: [],
            }),
          ],
        }),
      ]),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    // Приход связан только с первой строкой, но считается общим по сырью.
    await screen.findByTestId('purchase-row-item-1')
    const table = screen.getByTestId('purchase-table')
    expect(screen.getAllByTestId('schedule-group')).toHaveLength(2)
    // Нужно 45 кг, пришло 40: обе строки закрыты пропорционально, докупить 5.
    expect(table).toHaveTextContent('перекрыто 40 из 45 кг (88,9 %)')
    expect(table).toHaveTextContent('докупить 5 кг')
    expect(table).toHaveTextContent(
      'Ближайший заказ: к 01.11.2025 — 5 кг (потребность — февраль 2026)',
    )
  })

  it('альтернативное сырьё закрывает потребность основной строки', async () => {
    mockApi(
      routes([
        plan({
          items: [
            planItem({ fact_quantity: '0', fact_months: [] }),
            planItem({
              id: 'item-2',
              alternative_of_id: 'item-1',
              product_id: 'raw-2',
              product_code: 'RAW-2',
              product_name: 'Кокосовая стружка',
              quantity: '15.000',
              fact_quantity: '12.000',
              fact_months: [{ month: 1, quantity: '12.000' }],
            }),
          ],
        }),
      ]),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    // Альтернатива — под основной строкой, со своей пометкой и расходом.
    const badge = await screen.findByTestId('alt-badge-item-2')
    expect(badge).toHaveTextContent('альтернатива')
    expect(screen.getByTestId('alt-item-2')).toHaveTextContent('план 15 · пришло 12')
    expect(screen.getByTestId('alt-item-2')).toHaveTextContent('на покрытие 12')
    expect(
      screen.getByRole('button', { name: 'Добавить альтернативу FIN-1 1' }),
    ).toBeInTheDocument()

    // Январь закрыт альтернативой, февраль — на 2 из 20: докупить 18.
    const table = screen.getByTestId('purchase-table')
    expect(table).toHaveTextContent('перекрыто 12 из 30 кг (40 %)')
    expect(table).toHaveTextContent(
      'Ближайший заказ: к 01.11.2025 — 18 кг (потребность — февраль 2026)',
    )
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
  })

  it('не отправляет план без цены и объясняет почему', async () => {
    const user = userEvent.setup()
    const baseItem = plan().items[0]
    if (!baseItem) throw new Error('в плане нет строки')
    const noPrice = plan({ items: [{ ...baseItem, price_rub: null }] })
    mockApi(routes([noPrice]))
    render(<PurchasePlanPage user={DIRECTOR} />)

    await screen.findByTestId('purchase-status')
    await screen.findByLabelText('Количество FIN-1 1')
    await user.click(screen.getByRole('button', { name: 'Отправить на согласование' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Укажите цену у всех строк')
  })
})
