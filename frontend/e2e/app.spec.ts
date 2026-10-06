import { expect, test } from '@playwright/test'

const STOCK = [
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

test('остатки по партиям отображаются с себестоимостью', async ({ page }) => {
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: STOCK }))
  await page.goto('/')

  await expect(page.getByRole('heading', { level: 1, name: 'Партии и остатки' })).toBeVisible()
  const table = page.getByTestId('stock-table')
  await expect(table).toBeVisible()
  await expect(table.getByText('SKU-1')).toBeVisible()
  await expect(table.getByText('Материал')).toBeVisible()
  await expect(page.getByTestId('total-value')).toHaveText('1 500,00 ₽')
})

test('разделы переключаются', async ({ page }) => {
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.goto('/')

  await page.getByRole('button', { name: 'PnL / Cashflow' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'PnL / Cashflow' })).toBeVisible()
  await expect(page.getByText('Модуль ещё не реализован.')).toBeVisible()
})

test('пустой список показывает подсказку', async ({ page }) => {
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByTestId('empty-state')).toBeVisible()
})
