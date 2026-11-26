import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FutureProduct, Product, SessionUser } from './api'
import { mockApi } from './apiMock'
import { FutureProductsPage } from './FutureProductsPage'
import { PERMISSIONS } from './testPermissions'

const COMMERCIAL: SessionUser = {
  id: 'cd-1',
  login: 'commercial',
  full_name: 'Коммерческий директор',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
  permissions: PERMISSIONS['commercial_director'],
}

/** Как на живом стенде: справочник только на чтение, но планы — все. */
const COMMERCIAL_NO_DIRS: SessionUser = {
  ...COMMERCIAL,
  permissions: {
    ...PERMISSIONS['commercial_director'],
    directories: { actions: ['view'], scope: 'all' },
  },
}

const USED: FutureProduct = {
  id: 'future-1',
  name: 'Сок яблочный',
  unit: 'л',
  kind: 'finished',
  created_at: '2026-11-26T10:00:00Z',
  plans_count: 1,
  rows_count: 2,
  other_documents: 0,
  years: [2027],
  delete_allowed: false,
}

const UNUSED: FutureProduct = {
  id: 'future-2',
  name: 'Сок вишнёвый',
  unit: 'л',
  kind: 'finished',
  created_at: '2026-11-26T10:00:00Z',
  plans_count: 0,
  rows_count: 0,
  other_documents: 0,
  years: [],
  delete_allowed: true,
}

const REAL: Product = {
  id: 'p-1',
  code: 'SKU-1',
  name: 'Сок яблочный 1 л',
  kind: 'finished',
  unit: 'л',
  source: '1c',
  is_active: true,
  is_future: false,
}

function calls(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) => String(call[0]))
}

function sentPayloads(): Record<string, unknown>[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.flatMap((call) => {
    const init = call[1] as RequestInit | undefined
    if (typeof init?.body !== 'string') return []
    try {
      return [JSON.parse(init.body) as Record<string, unknown>]
    } catch {
      return []
    }
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function baseRoutes(extra: Record<string, { status?: number; body?: unknown }> = {}) {
  return {
    'POST /api/v1/future-products/future-1/bind': {
      body: {
        product_id: 'p-1',
        product_code: 'SKU-1',
        product_name: 'Сок яблочный 1 л',
        plan_rows: 2,
        plans: 1,
        other_rows: 0,
        years: [2027],
      },
    },
    'DELETE /api/v1/future-products/future-2': { status: 204 },
    'POST /api/v1/future-products': {
      status: 201,
      body: {
        id: 'future-3',
        code: 'БУД-NEW001',
        name: 'Сок вишнёвый',
        kind: 'finished',
        unit: 'л',
        source: 'manual',
        is_active: true,
        is_future: true,
      },
    },
    '/api/v1/future-products': { body: [USED, UNUSED] },
    '/api/v1/products': { body: [REAL] },
    ...extra,
  }
}

describe('FutureProductsPage', () => {
  it('ведёт будущие позиции, даже если справочник только на чтение', async () => {
    mockApi(baseRoutes())
    render(<FutureProductsPage user={COMMERCIAL_NO_DIRS} />)

    expect(await screen.findByLabelText('Название будущей позиции')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeVisible()
    expect(screen.getAllByRole('button', { name: 'Привязать' }).length).toBeGreaterThan(0)
  })

  it('показывает использование и привязывает позицию к номенклатуре 1С', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockApi(baseRoutes())
    render(<FutureProductsPage user={COMMERCIAL} />)

    expect(await screen.findByText('Сок яблочный')).toBeInTheDocument()
    expect(screen.getByText('планов: 1, строк: 2 · 2027')).toBeInTheDocument()
    expect(screen.getByText('не используется')).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Привязать' })[0] as HTMLElement)
    const panel = await screen.findByTestId('future-bind-panel')
    expect(panel).toHaveTextContent('Привязка «Сок яблочный»')

    const picker = within(panel).getByLabelText('Реальная позиция из 1С')
    await user.click(picker)
    await user.type(picker, 'Сок')
    await user.click(await screen.findByRole('option', { name: /SKU-1/ }))
    await user.click(within(panel).getByRole('button', { name: 'Привязать' }))

    await waitFor(() => {
      expect(calls().some((url) => url.includes('/future-products/future-1/bind'))).toBe(true)
    })
    expect(sentPayloads().some((body) => body.product_id === 'p-1')).toBe(true)
    await waitFor(() => {
      expect(screen.getByTestId('future-notice')).toHaveTextContent('заменена на «SKU-1')
    })
  })

  it('заводит позицию по названию без кода', async () => {
    const user = userEvent.setup()
    mockApi(baseRoutes())
    render(<FutureProductsPage user={COMMERCIAL} />)

    await user.type(await screen.findByLabelText('Название будущей позиции'), 'Сок вишнёвый')
    await user.clear(screen.getByLabelText('Единица будущей позиции'))
    await user.type(screen.getByLabelText('Единица будущей позиции'), 'л')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    await waitFor(() => {
      expect(sentPayloads().some((body) => body.name === 'Сок вишнёвый')).toBe(true)
    })
    expect(sentPayloads().find((body) => body.name === 'Сок вишнёвый')?.unit).toBe('л')
    await waitFor(() => {
      expect(screen.getByTestId('future-notice')).toHaveTextContent('добавлена')
    })
  })

  it('удаляет только неиспользованную позицию', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockApi(baseRoutes())
    render(<FutureProductsPage user={COMMERCIAL} />)

    await screen.findByText('Сок яблочный')
    const rows = screen.getAllByRole('row')
    const usedRow = rows.find((row) => row.textContent?.includes('Сок яблочный'))
    const unusedRow = rows.find((row) => row.textContent?.includes('Сок вишнёвый'))
    expect(usedRow).toBeDefined()
    expect(unusedRow).toBeDefined()

    expect(within(usedRow as HTMLElement).getByRole('button', { name: 'Удалить' })).toBeDisabled()
    await user.click(within(unusedRow as HTMLElement).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => {
      expect(calls().some((url) => url.includes('/future-products/future-2'))).toBe(true)
    })
    await waitFor(() => {
      expect(screen.getByTestId('future-notice')).toHaveTextContent('удалена')
    })
  })
})
