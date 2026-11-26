import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Counterparty, SalesPlan, SalesPlanCorrection, SessionUser } from './api'
import { mockApi } from './apiMock'
import { SalesPlansPage } from './SalesPlansPage'
import { PERMISSIONS } from './testPermissions'

const YEAR = new Date().getFullYear()

const COMMERCIAL: SessionUser = {
  id: 'cd-1',
  login: 'commercial',
  full_name: 'Коммерческий директор',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
  permissions: PERMISSIONS['commercial_director'],
}

const MANAGER: SessionUser = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Иван Петров',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
  permissions: PERMISSIONS['sales_manager'],
}

const EXECUTIVE: SessionUser = {
  id: 'ed-1',
  login: 'executive',
  full_name: 'Исполнительный директор',
  role: 'executive_director',
  role_title: 'Исполнительный директор',
  permissions: PERMISSIONS['executive_director'],
}

const PURCHASE: SessionUser = {
  id: 'pd-1',
  login: 'purchase',
  full_name: 'Пётр Закупщиков',
  role: 'purchase_director',
  role_title: 'Директор по закупкам',
  permissions: PERMISSIONS['purchase_director'],
}

const CLIENTS: Counterparty[] = [
  {
    id: 'client-1',
    name: 'ООО Ромашка',
    inn: '7701234567',
    note: null,
    is_customer: true,
    is_local_supplier: false,
    is_import_supplier: false,
    source: '1c',
    is_active: true,
  },
  {
    id: 'client-2',
    name: 'ООО Вектор',
    inn: null,
    note: null,
    is_customer: true,
    is_local_supplier: false,
    is_import_supplier: false,
    source: '1c',
    is_active: true,
  },
]

const PRODUCTS = [
  {
    id: 'product-1',
    code: 'SKU-1',
    name: 'Товар 1',
    kind: 'finished',
    unit: 'шт',
    is_active: true,
  },
  {
    id: 'product-2',
    code: 'SKU-2',
    name: 'Товар 2',
    kind: 'finished',
    unit: 'шт',
    is_active: true,
  },
]

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
    items: [
      {
        id: 'item-1',
        client_id: 'client-1',
        client_name: 'ООО Ромашка',
        product_id: 'product-1',
        product_code: 'SKU-1',
        product_name: 'Товар 1',
        product_kind: 'finished',
        unit: 'шт',
        month: 12,
        quantity: '10.000',
        notes: null,
      },
    ],
    ...overrides,
  }
}

function correction(overrides: Partial<SalesPlanCorrection> = {}): SalesPlanCorrection {
  return {
    id: 'corr-1',
    plan_id: 'plan-1',
    status: 'draft',
    status_title: 'Черновик корректировки',
    created_by_name: 'Менеджер по продажам',
    reviewed_by_name: null,
    reviewed_at: null,
    reason: null,
    review_reason: null,
    created_at: '2026-10-21T10:00:00Z',
    updated_at: '2026-10-21T10:00:00Z',
    annual_needs_reapproval: false,
    items: [
      {
        id: 'ci-1',
        client_id: 'client-1',
        client_name: 'ООО Ромашка',
        product_id: 'product-1',
        product_code: 'SKU-1',
        product_name: 'Товар 1',
        unit: 'шт',
        month: 12,
        quantity: '20.000',
        current_quantity: '10.000',
        notes: null,
      },
    ],
    ...overrides,
  }
}

function routes(extra: Record<string, { status?: number; body?: unknown }> = {}) {
  return {
    '/api/v1/counterparties': { body: CLIENTS },
    '/api/v1/products': { body: PRODUCTS },
    '/api/v1/users': { body: [MANAGER] },
    ...extra,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function calls(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) => String(call[0]))
}

function bodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) => JSON.stringify(call[1] ?? {}))
}

/** Тела PUT/POST-запросов: из init достаём строку body и разбираем её. */
function sentPayloads(): Record<string, unknown>[] {
  return bodies().flatMap((raw) => {
    const init = JSON.parse(raw) as { body?: string }
    if (!init.body) return []
    try {
      return [JSON.parse(init.body) as Record<string, unknown>]
    } catch {
      return []
    }
  })
}

describe('SalesPlansPage', () => {
  it('показывает план по клиенту и утверждает его по кнопке', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        '/api/v1/sales-plans/plan-1/approve': { body: plan() },
        '/api/v1/sales-plans': { body: [plan()] },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    expect(await screen.findByText('Менеджер по продажам')).toBeInTheDocument()
    expect(screen.getByText('На проверке')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('row-total-SKU-1')).toHaveTextContent('10 шт')
    })
    // Строка клиента ООО Ромашка видна, замороженный январь недоступен для правки.
    expect(screen.getByTestId('current-client')).toHaveTextContent('ООО Ромашка')
    expect(screen.getByLabelText('SKU-1 Декабрь')).toHaveValue('10')
    expect(screen.getByLabelText('SKU-1 Январь')).toBeDisabled()
    // Цен в плане продаж нет — только количество.
    expect(screen.queryByLabelText('Цена SKU-1')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Утвердить' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plans/plan-1/approve'))).toBe(true)
    })
  })

  it('администратор правит и утверждает план, а не только смотрит', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        '/api/v1/sales-plans/plan-1/approve': { body: plan({ status: 'approved' }) },
        '/api/v1/sales-plans': { body: [plan()] },
        '/api/v1/sales-plan-corrections': { body: [] },
      }),
    )
    render(<SalesPlansPage user={EXECUTIVE} />)

    expect(await screen.findByRole('button', { name: 'Сохранить' })).toBeInTheDocument()
    expect(screen.queryByText('Только просмотр')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Утвердить' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plans/plan-1/approve'))).toBe(true)
    })
  })

  it('закупщик видит план только на просмотр', async () => {
    mockApi(
      routes({
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={PURCHASE} />)

    expect(await screen.findByText('Утверждён')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('row-total-SKU-1')).toHaveTextContent('10 шт')
    })
    expect(screen.getByLabelText('SKU-1 Декабрь')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Утвердить' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Отправить на проверку' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Создать .*план/ })).not.toBeInTheDocument()
  })

  it('утверждённый план не правится напрямую, только через корректировку', async () => {
    mockApi(
      routes({
        '/api/v1/sales-plan-corrections': { body: [] },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    expect(
      await screen.findByRole('button', { name: 'Исправить утверждённый план' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()
    await screen.findByTestId('plan-table')
    expect(screen.getByLabelText('SKU-1 Декабрь')).toBeDisabled()
  })

  it('сохраняет строки с клиентом, товаром и количеством', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        '/api/v1/sales-plans/plan-1/items': { body: plan() },
        '/api/v1/sales-plans': { body: [plan({ status: 'filling', status_title: 'Заполняется' })] },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    await screen.findByText('Заполняется')
    await screen.findByTestId('plan-table')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plans/plan-1/items'))).toBe(true)
    })
    const sent = bodies().find((body) => body.includes('client_id'))
    expect(sent).toBeDefined()
    expect(sent).toContain('client-1')
    expect(sent).toContain('product-1')
    expect(sent).not.toContain('price')
  })

  it('добавляет к плану второго клиента', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'PUT /api/v1/sales-plans/plan-1/items': {
          body: plan({ status: 'filling', status_title: 'Заполняется' }),
        },
        '/api/v1/sales-plans': { body: [plan({ status: 'filling', status_title: 'Заполняется' })] },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    await screen.findByText('Заполняется')
    const picker = screen.getByLabelText('Добавить клиента')
    await user.click(picker)
    await user.type(picker, 'Вектор')
    await user.click(await screen.findByRole('option', { name: 'ООО Вектор' }))
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    expect(screen.getByTestId('current-client')).toHaveTextContent('ООО Вектор')
    expect(screen.getByTestId('plan-empty')).toBeInTheDocument()
    // Оба клиента видны как вкладки.
    expect(screen.getByRole('button', { name: 'ООО Ромашка' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ООО Вектор' })).toBeInTheDocument()
  })

  it('автосохраняет клиента и позицию, даже пока количества не заполнены', async () => {
    const user = userEvent.setup()
    const empty = plan({ status: 'filling', status_title: 'Заполняется', items: [] })
    mockApi(
      routes({
        'PUT /api/v1/sales-plans/plan-1/items': { body: empty },
        '/api/v1/sales-plans': { body: [empty] },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    await screen.findByText('Заполняется')
    await screen.findByTestId('plan-table')
    const clientPicker = screen.getByLabelText('Добавить клиента')
    await user.click(clientPicker)
    await user.type(clientPicker, 'Вектор')
    await user.click(await screen.findByRole('option', { name: 'ООО Вектор' }))
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    const productPicker = screen.getByLabelText('Добавить товар')
    await user.click(productPicker)
    await user.type(productPicker, 'Товар 1')
    await user.click(await screen.findByRole('option', { name: /SKU-1/ }))
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }))

    await waitFor(
      () => {
        const saved = sentPayloads().find((payload) => {
          const rows = payload.rows as { client_id: string; product_id: string }[] | undefined
          return rows?.some((row) => row.client_id === 'client-2' && row.product_id === 'product-1')
        })
        expect(saved).toBeDefined()
        expect(saved?.items).toEqual([])
        expect(saved?.rows).toEqual([{ client_id: 'client-2', product_id: 'product-1' }])
        expect(saved?.clients).toEqual([{ client_id: 'client-2' }])
      },
      { timeout: 2000 },
    )
  })

  it('автосохраняет введённое количество без кнопки «Сохранить»', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'PUT /api/v1/sales-plans/plan-1/items': {
          body: plan({ status: 'filling', status_title: 'Заполняется' }),
        },
        '/api/v1/sales-plans': { body: [plan({ status: 'filling', status_title: 'Заполняется' })] },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    await screen.findByText('Заполняется')
    await screen.findByTestId('plan-table')
    const december = screen.getByLabelText('SKU-1 Декабрь')
    await user.clear(december)
    await user.type(december, '7')

    await waitFor(
      () => {
        const saved = sentPayloads().find((payload) => {
          const items = payload.items as { product_id: string; quantity: string }[] | undefined
          return items?.some((item) => item.product_id === 'product-1' && item.quantity === '7')
        })
        expect(saved).toBeDefined()
      },
      { timeout: 2500 },
    )
  })

  it('менеджер отправляет свой план на проверку', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        '/api/v1/sales-plans/plan-1/submit': { body: plan({ status: 'on_review' }) },
        '/api/v1/sales-plans': { body: [plan({ status: 'filling', status_title: 'Заполняется' })] },
      }),
    )
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
    mockApi(
      routes({
        '/api/v1/sales-plans/plan-1/items': {
          status: 409,
          body: { detail: 'Замороженные месяцы менять нельзя: 1' },
        },
        '/api/v1/sales-plans': { body: [plan({ status: 'filling', status_title: 'Заполняется' })] },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    await screen.findByText('Заполняется')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Замороженные месяцы менять нельзя')
  })

  it('менеджер отправляет корректировку утверждённого плана коммерческому директору', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'PUT /api/v1/sales-plan-corrections/corr-1/items': { body: correction() },
        'POST /api/v1/sales-plan-corrections/corr-1/submit': {
          body: correction({ status: 'on_review', status_title: 'Корректировка на утверждении' }),
        },
        '/api/v1/sales-plan-corrections': { body: [correction()] },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    await screen.findByTestId('correction-box')
    await waitFor(() => {
      expect(screen.getByTestId('correction-box')).toHaveTextContent('Черновик корректировки')
    })
    expect(screen.getByLabelText('Корректировка SKU-1 Декабрь')).toHaveValue('20')
    await user.click(screen.getByRole('button', { name: 'Отправить коммерческому директору' }))

    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plan-corrections/corr-1/items'))).toBe(true)
      expect(calls().some((url) => url.includes('/sales-plan-corrections/corr-1/submit'))).toBe(
        true,
      )
    })
  })

  it('менеджер создаёт черновик корректировки', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'POST /api/v1/sales-plan-corrections': { status: 201, body: correction() },
        '/api/v1/sales-plan-corrections': { body: [] },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    await user.click(await screen.findByRole('button', { name: 'Предложить корректировку' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plan-corrections'))).toBe(true)
    })
  })

  it('коммерческий директор утверждает корректировку', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'POST /api/v1/sales-plan-corrections/corr-1/approve': {
          body: correction({ status: 'approved', status_title: 'Корректировка утверждена' }),
        },
        '/api/v1/sales-plan-corrections': {
          body: [correction({ status: 'on_review', status_title: 'Корректировка на утверждении' })],
        },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    await screen.findByTestId('correction-box')
    await waitFor(() => {
      expect(screen.getByTestId('correction-box')).toHaveTextContent('Корректировка на утверждении')
    })
    await user.click(screen.getByRole('button', { name: 'Утвердить корректировку' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plan-corrections/corr-1/approve'))).toBe(
        true,
      )
    })
  })

  it('коммерческий директор открывает корректировку чужого утверждённого плана', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'POST /api/v1/sales-plan-corrections': { status: 201, body: correction() },
        '/api/v1/sales-plan-corrections': { body: [] },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    await user.click(await screen.findByRole('button', { name: 'Исправить утверждённый план' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plan-corrections'))).toBe(true)
    })
  })

  it('администратор исправляет утверждённый план через корректировку', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'POST /api/v1/sales-plan-corrections': { status: 201, body: correction() },
        '/api/v1/sales-plan-corrections': { body: [] },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={EXECUTIVE} />)

    await user.click(await screen.findByRole('button', { name: 'Исправить утверждённый план' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plan-corrections'))).toBe(true)
    })
  })

  it('в корректировке можно изменить объём и добавить позицию', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'PUT /api/v1/sales-plan-corrections/corr-1/items': { body: correction() },
        '/api/v1/sales-plan-corrections': { body: [correction()] },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    const december = await screen.findByLabelText('Корректировка SKU-1 Декабрь')
    await user.clear(december)
    await user.type(december, '25')
    const box = screen.getByTestId('correction-box')
    const picker = within(box).getByLabelText('Добавить товар в корректировку')
    await user.click(picker)
    await user.type(picker, 'Товар 2')
    await user.click(await screen.findByRole('option', { name: /SKU-2/ }))
    await user.click(within(box).getByRole('button', { name: 'Добавить строку' }))
    await user.type(screen.getByLabelText('Корректировка SKU-2 Декабрь'), '5')
    await user.click(within(box).getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(calls().some((url) => url.includes('/sales-plan-corrections/corr-1/items'))).toBe(true)
    })
    const sent = bodies().find((body) => body.includes('product-2'))
    expect(sent).toBeDefined()
    expect(sent).toContain('product-1')
    expect(sent).toContain('product-2')
    expect(sent).toContain('25')
    expect(sent).toContain('5')
  })

  it('коммерческий директор правит черновик корректировки менеджера', async () => {
    mockApi(
      routes({
        '/api/v1/sales-plan-corrections': { body: [correction()] },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={COMMERCIAL} />)

    expect(await screen.findByLabelText('Корректировка SKU-1 Декабрь')).toHaveValue('20')
    const box = screen.getByTestId('correction-box')
    expect(within(box).getByRole('button', { name: 'Сохранить' })).toBeInTheDocument()
  })

  it('напоминает о повторном согласовании, пока годовой план не согласован', async () => {
    mockApi(
      routes({
        '/api/v1/sales-plan-corrections': {
          body: [
            correction({
              status: 'approved',
              status_title: 'Корректировка утверждена',
              annual_needs_reapproval: true,
            }),
          ],
        },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    expect(
      await screen.findByText(/Годовой план отдела нужно отправить на финальное согласование/),
    ).toBeInTheDocument()
  })

  it('не напоминает о согласовании, когда годовой план уже согласован заново', async () => {
    mockApi(
      routes({
        '/api/v1/sales-plan-corrections': {
          body: [
            correction({
              status: 'approved',
              status_title: 'Корректировка утверждена',
              annual_needs_reapproval: false,
            }),
          ],
        },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    expect(await screen.findByText(/Изменения применены к плану/)).toBeInTheDocument()
    expect(
      screen.queryByText(/Годовой план отдела нужно отправить на финальное согласование/),
    ).not.toBeInTheDocument()
  })

  it('на утверждении показывает только изменённые строки', async () => {
    mockApi(
      routes({
        '/api/v1/sales-plan-corrections': {
          body: [correction({ status: 'on_review', status_title: 'Корректировка на утверждении' })],
        },
        '/api/v1/sales-plans': {
          body: [plan({ status: 'approved', status_title: 'Утверждён' })],
        },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    const table = await screen.findByTestId('correction-readonly')
    expect(table).toHaveTextContent('10 шт')
    expect(table).toHaveTextContent('20 шт')
    expect(table).not.toHaveTextContent('Изменений нет')
  })

  it('в плане менеджера нет материалов — только сырьё и готовая продукция', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        '/api/v1/products': {
          body: [
            ...PRODUCTS,
            {
              id: 'material-1',
              code: 'MAT-1',
              name: 'Крышка от коробки',
              kind: 'material',
              unit: 'шт',
              is_active: true,
            },
          ],
        },
        '/api/v1/sales-plan-corrections': { body: [] },
        '/api/v1/sales-plans': { body: [plan({ status: 'draft', status_title: 'Черновик' })] },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    const select = await screen.findByLabelText('Добавить товар')
    await waitFor(() => {
      expect(calls().some((url) => url.includes('kinds=raw,finished'))).toBe(true)
      expect(calls().some((url) => url.includes('include_future=true'))).toBe(true)
    })
    await user.click(select)
    await waitFor(() => {
      expect(screen.queryByRole('option', { name: /Крышка от коробки/ })).not.toBeInTheDocument()
      expect(screen.getByRole('option', { name: /Товар 2/ })).toBeInTheDocument()
    })
  })
})

const FUTURE_PRODUCT = {
  id: 'future-1',
  code: 'БУД-AAA111',
  name: 'Сок яблочный',
  kind: 'finished',
  unit: 'л',
  source: 'manual',
  is_active: true,
  is_future: true,
}

const draftPlan = () =>
  plan({
    status: 'draft',
    status_title: 'Черновик',
    items: [],
    draft_clients: [{ client_id: 'client-1', client_name: 'ООО Ромашка' }],
    draft_rows: [
      {
        client_id: 'client-1',
        client_name: 'ООО Ромашка',
        product_id: 'product-1',
        product_code: 'SKU-1',
        product_name: 'Товар 1',
        unit: 'шт',
      },
    ],
  })

describe('SalesPlansPage — удаление и будущие позиции', () => {
  it('убирает позицию и клиента из черновика', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockApi(
      routes({
        '/api/v1/sales-plans/plan-1/items': {
          body: plan({
            status: 'draft',
            status_title: 'Черновик',
            items: [],
            draft_clients: [],
            draft_rows: [],
          }),
        },
        '/api/v1/sales-plans': { body: [draftPlan()] },
        '/api/v1/sales-plan-corrections': { body: [] },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    await user.click(await screen.findByRole('button', { name: 'Убрать строку Товар 1' }))
    await waitFor(() => {
      expect(
        sentPayloads().some(
          (body) =>
            Array.isArray(body.items) &&
            body.items.length === 0 &&
            Array.isArray(body.rows) &&
            body.rows.length === 0,
        ),
      ).toBe(true)
    })

    await user.click(screen.getByRole('button', { name: 'Убрать клиента' }))
    await waitFor(() => {
      expect(
        sentPayloads().some((body) => Array.isArray(body.clients) && body.clients.length === 0),
      ).toBe(true)
    })
  })

  it('не даёт убрать строку с объёмом в замороженном месяце', async () => {
    const user = userEvent.setup()
    const frozen = plan({
      status: 'draft',
      status_title: 'Черновик',
      editable_months: [12],
      items: [
        {
          id: 'item-1',
          client_id: 'client-1',
          client_name: 'ООО Ромашка',
          product_id: 'product-1',
          product_code: 'SKU-1',
          product_name: 'Товар 1',
          product_kind: 'finished',
          unit: 'шт',
          month: 1,
          quantity: '5.000',
          notes: null,
        },
      ],
    })
    mockApi(
      routes({
        '/api/v1/sales-plans': { body: [frozen] },
        '/api/v1/sales-plan-corrections': { body: [] },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    await user.click(await screen.findByRole('button', { name: 'Убрать строку Товар 1' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('замороженных')
    expect(sentPayloads().filter((body) => Array.isArray(body.items)).length).toBe(0)
  })

  it('создаёт будущую позицию из плана и помечает её', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'POST /api/v1/future-products': { status: 201, body: FUTURE_PRODUCT },
        '/api/v1/sales-plans/plan-1/items': {
          body: plan({
            status: 'draft',
            status_title: 'Черновик',
            items: [],
            draft_clients: [{ client_id: 'client-1', client_name: 'ООО Ромашка' }],
            draft_rows: [
              {
                client_id: 'client-1',
                client_name: 'ООО Ромашка',
                product_id: 'future-1',
                product_code: 'БУД-AAA111',
                product_name: 'Сок яблочный',
                unit: 'л',
                product_is_future: true,
              },
            ],
          }),
        },
        '/api/v1/sales-plans': { body: [draftPlan()] },
        '/api/v1/sales-plan-corrections': { body: [] },
      }),
    )
    render(<SalesPlansPage user={MANAGER} />)

    await screen.findByTestId('current-client')
    await user.click(screen.getByRole('button', { name: /Будущая позиция/ }))
    await user.type(screen.getByLabelText('Название будущей позиции'), 'Сок яблочный')
    await user.click(screen.getByRole('button', { name: 'Создать и добавить' }))

    await waitFor(() => {
      expect(sentPayloads().some((body) => body.name === 'Сок яблочный')).toBe(true)
    })
    expect(await screen.findByText('Сок яблочный')).toBeInTheDocument()
    expect(screen.getByText('будущая')).toBeInTheDocument()
  })
})
