import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { StockRow } from './api'
import { mockApi } from './apiMock'
import { StockPage } from './StockPage'

const ROWS: StockRow[] = [
  {
    batch_item_id: 'i-1',
    batch_number: 'ИТ-2027-0002',
    batch_date: '2026-11-01',
    product_code: 'ТОВ1',
    product_name: 'Арахис',
    product_kind: 'raw',
    unit: 'кг',
    quantity_on_hand: '10.000',
    unit_cost: '100.00',
    value_rub: '1000.00',
    snapshot_date: null,
  },
  {
    batch_item_id: 'i-2',
    batch_number: 'ИТ-2027-0001',
    batch_date: '2026-11-02',
    product_code: 'ТОВ2',
    product_name: 'Изюм',
    product_kind: 'raw',
    unit: 'кг',
    quantity_on_hand: '2.000',
    unit_cost: '900.00',
    value_rub: '1800.00',
    snapshot_date: null,
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

function batches(): string[] {
  return within(screen.getByTestId('stock-table'))
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0]?.textContent ?? '')
}

describe('StockPage', () => {
  it('сортирует по стоимости и по номеру партии', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/stock': { body: ROWS } })
    render(<StockPage />)

    await screen.findByTestId('stock-table')
    // По умолчанию — по номеру партии.
    expect(batches()).toEqual(['ИТ-2027-0001', 'ИТ-2027-0002'])

    const value = screen.getByRole('columnheader', { name: 'Стоимость, ₽' })
    await user.click(within(value).getByRole('button'))
    expect(value).toHaveAttribute('aria-sort', 'ascending')
    expect(batches()).toEqual(['ИТ-2027-0002', 'ИТ-2027-0001'])

    await user.click(within(value).getByRole('button'))
    expect(value).toHaveAttribute('aria-sort', 'descending')
    expect(batches()).toEqual(['ИТ-2027-0001', 'ИТ-2027-0002'])
  })
})
