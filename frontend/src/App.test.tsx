import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { StockRow } from './api'

const ROWS: StockRow[] = [
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

function mockStock(rows: StockRow[]): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('показывает разделы и остатки по партиям', async () => {
    mockStock(ROWS)
    render(<App />)

    expect(screen.getByRole('heading', { level: 1, name: 'Партии и остатки' })).toBeInTheDocument()

    const table = await screen.findByTestId('stock-table')
    expect(table).toBeInTheDocument()
    expect(screen.getByText('SKU-1')).toBeInTheDocument()
    expect(screen.getByText('Материал')).toBeInTheDocument()
    expect(screen.getByText('120,00')).toBeInTheDocument()
    // Итоговая стоимость остатка: 900 + 600.
    expect(screen.getByTestId('total-value')).toHaveTextContent('1 500,00')
  })

  it('показывает пустое состояние, когда данных нет', async () => {
    mockStock([])
    render(<App />)
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
  })

  it('показывает ошибку, если API недоступен', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('', { status: 500 })),
    )
    render(<App />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('HTTP 500')
  })

  it('переключает разделы', async () => {
    mockStock(ROWS)
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Матрица цен' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: 'Матрица цен' })).toBeInTheDocument()
    })
    expect(screen.getByText('Модуль ещё не реализован.')).toBeInTheDocument()
  })
})
