import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { SessionUser, StockRow } from './api'
import { mockApi } from './apiMock'

const MANAGER: SessionUser = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Иван Петров',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

const PURCHASE_DIRECTOR: SessionUser = {
  id: 'pd-1',
  login: 'purchase',
  full_name: 'Пётр Закупщиков',
  role: 'purchase_director',
  role_title: 'Директор по закупкам',
}

const STOCK: StockRow[] = [
  {
    batch_item_id: 'item-1',
    batch_number: 'P-001',
    batch_date: '2026-10-01',
    product_code: 'SKU-1',
    product_name: 'Товар 1',
    product_kind: 'goods',
    unit: 'шт',
    quantity_on_hand: '10.000',
    unit_cost: '90.00',
    value_rub: '900.00',
    snapshot_date: null,
  },
  {
    batch_item_id: 'item-2',
    batch_number: 'P-001',
    batch_date: '2026-10-01',
    product_code: 'SKU-2',
    product_name: 'Материал 2',
    product_kind: 'material',
    unit: 'кг',
    quantity_on_hand: '5.000',
    unit_cost: '120.00',
    value_rub: '600.00',
    snapshot_date: null,
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('без сессии показывает экран входа', async () => {
    mockApi({ '/api/v1/auth/me': { status: 401, body: { detail: 'Требуется вход' } } })
    render(<App />)

    expect(await screen.findByLabelText('Логин')).toBeInTheDocument()
    expect(screen.getByLabelText('Пароль')).toBeInTheDocument()
  })

  it('входит по логину и показывает разделы и остатки', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/auth/login': { body: MANAGER },
      '/api/v1/auth/me': { status: 401, body: { detail: 'Требуется вход' } },
      '/api/v1/stock': { body: STOCK },
    })
    render(<App />)

    await user.type(await screen.findByLabelText('Логин'), 'sales')
    await user.type(screen.getByLabelText('Пароль'), 'secret')
    await user.click(screen.getByRole('button', { name: 'Войти' }))

    expect(await screen.findByText('Иван Петров')).toBeInTheDocument()
    const table = await screen.findByTestId('stock-table')
    expect(table).toHaveTextContent('SKU-1')
    expect(screen.getByTestId('total-value')).toHaveTextContent('1 500,00')
  })

  it('менеджеру не показывает закупочные разделы и заглушку модуля', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/auth/me': { body: MANAGER },
      '/api/v1/stock': { body: [] },
      '/api/v1/sales-plans': { body: [] },
      '/api/v1/products': { body: [] },
    })
    render(<App />)

    // Меню сгруппировано: сначала раскрываем категорию «Планирование».
    await user.click(await screen.findByRole('button', { name: 'Планирование' }))
    expect(screen.getByRole('button', { name: 'Планирование продаж' })).toBeInTheDocument()

    // Планирование закупок живёт в «Планировании», но менеджеру продаж недоступно.
    expect(screen.queryByRole('button', { name: 'Планирование закупок' })).not.toBeInTheDocument()

    // Закупочные разделы менеджеру продаж недоступны.
    await user.click(screen.getByRole('button', { name: 'Закупки' }))
    expect(screen.getByRole('button', { name: 'Поступления' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Планирование закупок' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Поступления' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Поступления' }),
    ).toBeInTheDocument()
  })

  it('планирование закупок живёт в категории «Планирование»', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/auth/me': { body: PURCHASE_DIRECTOR }, '/api/v1/stock': { body: [] } })
    render(<App />)

    const planning = (await screen.findByRole('button', { name: 'Планирование' })).closest(
      '.nav-group',
    ) as HTMLElement
    await user.click(within(planning).getByRole('button', { name: 'Планирование' }))

    // Директору по закупкам планирование продаж недоступно, а планирование закупок — здесь.
    expect(within(planning).queryByRole('button', { name: 'Планирование продаж' })).toBeNull()
    expect(
      within(planning).getByRole('button', { name: 'Планирование закупок' }),
    ).toBeInTheDocument()
    expect(within(planning).queryByRole('button', { name: 'Поступления' })).toBeNull()

    // В категории «Закупки» планирования закупок больше нет.
    const purchases = screen
      .getByRole('button', { name: 'Закупки' })
      .closest('.nav-group') as HTMLElement
    await user.click(within(purchases).getByRole('button', { name: 'Закупки' }))
    expect(within(purchases).getByRole('button', { name: 'Поступления' })).toBeInTheDocument()
    expect(within(purchases).queryByRole('button', { name: 'Планирование закупок' })).toBeNull()
  })

  it('категория меню раскрывается и сворачивается по стрелке', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/auth/me': { body: MANAGER }, '/api/v1/stock': { body: [] } })
    render(<App />)

    const catalogs = await screen.findByRole('button', { name: 'Справочники' })
    expect(screen.queryByRole('button', { name: 'Номенклатура' })).not.toBeInTheDocument()
    expect(catalogs).toHaveAttribute('aria-expanded', 'false')

    await user.click(catalogs)
    expect(screen.getByRole('button', { name: 'Номенклатура' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Контрагенты' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Валюты' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Справочники' }))
    expect(screen.queryByRole('button', { name: 'Номенклатура' })).not.toBeInTheDocument()
  })

  it('показывает пустое состояние, когда остатков нет', async () => {
    mockApi({ '/api/v1/auth/me': { body: MANAGER }, '/api/v1/stock': { body: [] } })
    render(<App />)

    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
  })

  it('показывает ошибку, если API остатков недоступен', async () => {
    mockApi({
      '/api/v1/auth/me': { body: MANAGER },
      '/api/v1/stock': { status: 500, body: { detail: 'Ошибка сервера' } },
    })
    render(<App />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Ошибка сервера')
  })

  it('выход возвращает на экран входа', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/auth/logout': { status: 204 },
      '/api/v1/auth/me': { body: MANAGER },
      '/api/v1/stock': { body: [] },
    })
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Выйти' }))
    expect(await screen.findByLabelText('Логин')).toBeInTheDocument()
  })
})
