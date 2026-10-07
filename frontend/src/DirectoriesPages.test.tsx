import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Client, Product } from './api'
import { mockApi } from './apiMock'
import { ClientsPage } from './ClientsPage'
import { NomenclaturePage } from './NomenclaturePage'

const CLIENTS: Client[] = [
  { id: 'c1', name: 'ООО Ромашка', inn: '7701234567', note: null, is_active: true },
  { id: 'c2', name: 'ООО Вектор', inn: null, note: 'Старый клиент', is_active: false },
]

const PRODUCTS: Product[] = [
  { id: 'p1', code: 'SKU-100', name: 'Краска белая', kind: 'goods', unit: 'шт', is_active: true },
  {
    id: 'p2',
    code: 'SKU-200',
    name: 'Растворитель',
    kind: 'material',
    unit: 'кг',
    is_active: false,
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ClientsPage', () => {
  it('показывает клиентов и их состояние', async () => {
    mockApi({ '/api/v1/clients': { body: CLIENTS } })
    render(<ClientsPage />)

    expect(await screen.findByTestId('clients-table')).toHaveTextContent('ООО Ромашка')
    expect(screen.getByText('7701234567')).toBeInTheDocument()
    expect(screen.getByText('Отключён')).toBeInTheDocument()
    expect(screen.getByTestId('clients-count')).toHaveTextContent('1')
  })

  it('добавляет клиента и перечитывает список', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/clients': { body: CLIENTS },
      '/api/v1/clients/c1': { body: { ...CLIENTS[0], is_active: false } },
    })
    render(<ClientsPage />)

    await screen.findByTestId('clients-table')
    await user.type(screen.getByLabelText('Наименование клиента'), 'ООО Новый')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    const posted = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.some((call) =>
      JSON.stringify(call[1] ?? {}).includes('ООО Новый'),
    )
    expect(posted).toBe(true)
  })

  it('показывает ошибку, если клиент уже есть', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/clients': { status: 409, body: { detail: 'Клиент «ООО Ромашка» уже есть' } },
    })
    render(<ClientsPage />)

    await screen.findByTestId('clients-table')
    await user.type(screen.getByLabelText('Наименование клиента'), 'ООО Ромашка')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('уже есть')
  })
})

describe('NomenclaturePage', () => {
  it('показывает номенклатуру и фильтрует по виду', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/products': { body: PRODUCTS } })
    render(<NomenclaturePage />)

    expect(await screen.findByTestId('products-table')).toHaveTextContent('Краска белая')
    expect(screen.getByTestId('products-count')).toHaveTextContent('2')

    await user.selectOptions(screen.getByLabelText('Фильтр по виду'), 'material')
    expect(screen.getByTestId('products-count')).toHaveTextContent('1')
    expect(screen.getByText('Растворитель')).toBeInTheDocument()
    expect(screen.queryByText('Краска белая')).not.toBeInTheDocument()
  })

  it('заводит позицию номенклатуры', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/products': { body: PRODUCTS } })
    render(<NomenclaturePage />)

    await screen.findByTestId('products-table')
    await user.type(screen.getByLabelText('Код'), 'SKU-300')
    await user.type(screen.getByLabelText('Наименование'), 'Грунтовка')
    await user.type(screen.getByLabelText('Единица'), 'л')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    const posted = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.some((call) =>
      JSON.stringify(call[1] ?? {}).includes('SKU-300'),
    )
    expect(posted).toBe(true)
  })

  it('показывает ошибку при дубле кода', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/products': {
        status: 409,
        body: { detail: 'Номенклатура с кодом «SKU-100» уже есть' },
      },
    })
    render(<NomenclaturePage />)

    await screen.findByTestId('products-table')
    await user.type(screen.getByLabelText('Код'), 'SKU-100')
    await user.type(screen.getByLabelText('Наименование'), 'Дубль')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('уже есть')
  })
})
