import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Country, SessionUser } from './api'
import { mockApi } from './apiMock'
import { CountriesPage } from './CountriesPage'

const DIRECTOR: SessionUser = {
  id: 'pd-1',
  login: 'purchase',
  full_name: 'Пётр Закупщиков',
  role: 'purchase_director',
  role_title: 'Директор по закупкам',
}

const IMPORTER: SessionUser = {
  id: 'im-1',
  login: 'import',
  full_name: 'Шахидул Ислам',
  role: 'import_manager',
  role_title: 'Менеджер по закупкам (импорт)',
}

const ADMIN: SessionUser = {
  id: 'ed-1',
  login: 'executive',
  full_name: 'Ольга Директорова',
  role: 'executive_director',
  role_title: 'Исполнительный директор',
}

const COUNTRIES: Country[] = [
  { id: 'th-1', name: 'Таиланд', delivery_days: 90, is_active: true, source: 'manual' },
  { id: 'cn-1', name: 'Китай', delivery_days: 65, is_active: false, source: 'manual' },
]

function routes(extra: Record<string, { status?: number; body?: unknown }> = {}) {
  return {
    ...extra,
    '/api/v1/countries': { body: COUNTRIES },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function patchBodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: [string, RequestInit?][] } }
  return mock.mock.calls
    .filter(([, init]) => init?.method === 'PATCH')
    .map(([, init]) => String(init?.body ?? ''))
}

function postBodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: [string, RequestInit?][] } }
  return mock.mock.calls
    .filter(([, init]) => init?.method === 'POST')
    .map(([, init]) => String(init?.body ?? ''))
}

describe('CountriesPage', () => {
  it('сортирует по сроку доставки по возрастанию и убыванию', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<CountriesPage user={DIRECTOR} />)

    const table = await screen.findByTestId('countries-table')
    // По умолчанию — по названию: Китай, Таиланд.
    const names = () =>
      within(table)
        .getAllByRole('row')
        .slice(1)
        .map((row) => within(row).getAllByRole('cell')[0]?.textContent ?? '')
    expect(names()).toEqual(['Китай', 'Таиланд'])

    const header = screen.getByRole('columnheader', { name: 'Срок доставки' })
    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    expect(names()).toEqual(['Китай', 'Таиланд'])

    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    expect(names()).toEqual(['Таиланд', 'Китай'])
  })

  it('директор по закупкам заводит страну со сроком доставки', async () => {
    const user = userEvent.setup()
    mockApi(routes({ 'POST /api/v1/countries': { body: COUNTRIES[0] } }))
    render(<CountriesPage user={DIRECTOR} />)

    expect(await screen.findByTestId('countries-table')).toHaveTextContent('Таиланд')
    expect(screen.getByTestId('countries-table')).toHaveTextContent('90 дн')

    await user.type(screen.getByLabelText('Название страны'), 'Вьетнам')
    await user.clear(screen.getByLabelText('Срок доставки, дней'))
    await user.type(screen.getByLabelText('Срок доставки, дней'), '45')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    await waitFor(() => {
      expect(postBodies().some((body) => body.includes('Вьетнам'))).toBe(true)
    })
    expect(postBodies().find((body) => body.includes('Вьетнам'))).toContain('"delivery_days":45')
  })

  it('правит название и срок доставки, отключает страну', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'PATCH /api/v1/countries/th-1': { body: { ...COUNTRIES[0], delivery_days: 100 } },
      }),
    )
    render(<CountriesPage user={DIRECTOR} />)

    const row = await screen.findByTestId('country-row-th-1')
    await user.click(within(row).getByRole('button', { name: 'Изменить' }))
    await user.clear(screen.getByLabelText('Срок доставки Таиланд'))
    await user.type(screen.getByLabelText('Срок доставки Таиланд'), '100')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(patchBodies().some((body) => body.includes('"delivery_days":100'))).toBe(true)
    })

    await user.click(within(row).getByRole('button', { name: 'Отключить' }))
    await waitFor(() => {
      expect(patchBodies().some((body) => body.includes('"is_active":false'))).toBe(true)
    })
  })

  it('показывает ошибку сервера, если страна уже есть', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'POST /api/v1/countries': {
          status: 409,
          body: { detail: 'Страна «Таиланд» уже есть в справочнике' },
        },
      }),
    )
    render(<CountriesPage user={DIRECTOR} />)

    await screen.findByTestId('countries-table')
    await user.type(screen.getByLabelText('Название страны'), 'Таиланд')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('уже есть в справочнике')
  })

  it('администратор заводит и правит страны', async () => {
    const user = userEvent.setup()
    mockApi(routes({ 'POST /api/v1/countries': { body: COUNTRIES[0] } }))
    render(<CountriesPage user={ADMIN} />)

    expect(await screen.findByTestId('countries-table')).toHaveTextContent('Таиланд')
    await user.type(screen.getByLabelText('Название страны'), 'Вьетнам')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))
    await waitFor(() => {
      expect(postBodies().some((body) => body.includes('Вьетнам'))).toBe(true)
    })
    expect(screen.queryByText('Только просмотр')).not.toBeInTheDocument()
  })

  it('импорт-менеджер видит справочник только для чтения', async () => {
    mockApi(routes())
    render(<CountriesPage user={IMPORTER} />)

    expect(await screen.findByTestId('countries-table')).toHaveTextContent('Таиланд')
    expect(screen.queryByLabelText('Название страны')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Изменить' })).not.toBeInTheDocument()
    expect(screen.getByText('Только просмотр')).toBeInTheDocument()
  })
})
