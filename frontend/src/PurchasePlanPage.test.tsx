import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Counterparty, Product, PurchasePlan, SessionUser, StockRow } from './api'
import { MONTH_TITLES } from './api'
import { mockApi } from './apiMock'
import { PurchasePlanPage } from './PurchasePlanPage'

const YEAR = new Date().getFullYear()
const MONTH = new Date().getMonth() + 1
const MONTH_TITLE = MONTH_TITLES[MONTH - 1]

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
    id: 'mat-1',
    code: 'MAT-1',
    name: 'Банка 500 г',
    kind: 'material',
    unit: 'шт',
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

const STOCK: StockRow[] = [
  {
    batch_item_id: 'bi-1',
    batch_number: 'ИТ-0000001',
    batch_date: '2026-10-10',
    product_code: 'RAW-1',
    product_name: 'Орех грецкий, вес',
    product_kind: 'raw',
    unit: 'кг',
    quantity_on_hand: '50.000',
    unit_cost: '100.00',
    value_rub: '5000.00',
    snapshot_date: null,
  },
]

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
    editable_months: [MONTH],
    items: [
      {
        id: 'item-1',
        product_id: 'raw-1',
        product_code: 'RAW-1',
        product_name: 'Орех грецкий, вес',
        product_kind: 'raw',
        unit: 'кг',
        month: MONTH,
        quantity: '10.000',
        price_rub: '250.50',
        supplier_id: 'sup-1',
        supplier_name: 'ООО Импорт',
        delivery_days: 30,
        order_month: Math.max(1, MONTH - 1),
        notes: null,
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
    '/api/v1/stock': { body: STOCK },
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
  it('закупщик добавляет строку сырья и сохраняет её с ценой', async () => {
    const user = userEvent.setup()
    mockApi(
      routes([plan()], {
        'PUT /api/v1/purchase-plans/plan-1/items': { body: plan() },
      }),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    expect(await screen.findByTestId('purchase-status')).toHaveTextContent('Черновик')
    // Ждём, пока строки плана разложатся в черновики страницы.
    await screen.findByLabelText(`Количество RAW-1 ${MONTH_TITLE}`)
    expect(screen.getByTestId('purchase-plan-card')).toHaveTextContent(/2\s*505,00/)
    // Остаток сырья — справочно, из партий.
    expect(screen.getByTestId('purchase-table')).toHaveTextContent('50 кг')

    await user.selectOptions(screen.getByLabelText('Товар новой строки'), 'raw-1')
    await user.type(screen.getByLabelText('Количество новой строки'), '12,5')
    await user.type(screen.getByLabelText('Цена новой строки'), '300.25')
    await user.selectOptions(screen.getByLabelText('Поставщик новой строки'), 'sup-1')
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }))

    const quantities = screen.getAllByLabelText(`Количество RAW-1 ${MONTH_TITLE}`)
    expect(quantities).toHaveLength(2)
    expect(quantities[1]).toHaveValue('12.5')

    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(calls().some((url) => url.includes('/purchase-plans/plan-1/items'))).toBe(true)
    })
    const sent = putBodies().find((body) => body.includes('"items"'))
    expect(sent).toBeDefined()
    expect(sent).toContain('"quantity":"12.5"')
    expect(sent).toContain('"price_rub":"300.25"')
    expect(sent).toContain('"supplier_id":"sup-1"')
    expect(sent).toContain('"delivery_days":30')
    expect(await screen.findByTestId('purchase-saved')).toHaveTextContent('План сохранён')
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
    expect(screen.queryByRole('button', { name: 'Добавить строку' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Утвердить' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(`Количество RAW-1 ${MONTH_TITLE}`)).not.toBeInTheDocument()
  })

  it('создаёт план на год, если его ещё нет', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/products': { body: PRODUCTS },
      '/api/v1/counterparties': { body: SUPPLIERS },
      '/api/v1/stock': { body: STOCK },
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

  it('замороженная строка только для чтения, добавить в неё нельзя', async () => {
    mockApi(routes([plan({ editable_months: [] })]))
    render(<PurchasePlanPage user={DIRECTOR} />)

    expect(await screen.findByTestId('purchase-status')).toHaveTextContent('Черновик')
    expect(screen.queryByLabelText(`Количество RAW-1 ${MONTH_TITLE}`)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Убрать/ })).not.toBeInTheDocument()
    // Кнопка добавления есть, но месяцев для выбора нет — она заблокирована.
    expect(screen.getByRole('button', { name: 'Добавить строку' })).toBeDisabled()
  })

  it('показывает ошибку, если сервер отклонил сохранение', async () => {
    const user = userEvent.setup()
    mockApi(
      routes([plan()], {
        'PUT /api/v1/purchase-plans/plan-1/items': {
          status: 409,
          body: { detail: 'Замороженные месяцы менять нельзя: 1' },
        },
      }),
    )
    render(<PurchasePlanPage user={DIRECTOR} />)

    await screen.findByTestId('purchase-status')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Замороженные месяцы менять нельзя')
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
    const sent = bodies().find((body) => body.includes('уточнить цены'))
    expect(sent).toBeDefined()
  })
})
