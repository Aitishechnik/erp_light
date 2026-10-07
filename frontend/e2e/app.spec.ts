import { expect, type Page, test } from '@playwright/test'

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

const MANAGER = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Иван Петров',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

const YEAR = new Date().getFullYear()
const ALL_MONTHS = Array.from({ length: 12 }, (_, index) => index + 1)

function plan(overrides: Record<string, unknown> = {}) {
  return {
    id: 'plan-1',
    year: YEAR,
    manager_id: 'sm-1',
    manager_name: 'Иван Петров',
    created_by_name: 'Иван Петров',
    status: 'filling',
    status_title: 'Заполняется',
    notes: null,
    created_at: '2026-10-06T10:00:00Z',
    updated_at: '2026-10-06T10:00:00Z',
    editable_months: ALL_MONTHS,
    total_amount: '0.00',
    items: [],
    ...overrides,
  }
}

async function mockSession(page: Page, user: Record<string, unknown> = MANAGER): Promise<void> {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ json: user }))
}

test('экран входа показывается без сессии, а вход открывает разделы', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({ status: 401, json: { detail: 'Требуется вход' } }),
  )
  await page.route('**/api/v1/auth/login', (route) => route.fulfill({ json: MANAGER }))
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))

  await page.goto('/')
  await expect(page.getByLabel('Логин')).toBeVisible()

  await page.getByLabel('Логин').fill('sales')
  await page.getByLabel('Пароль').fill('secret')
  await page.getByRole('button', { name: 'Войти' }).click()

  await expect(page.getByRole('button', { name: 'Планирование продаж' })).toBeVisible()
  await expect(page.getByText('Иван Петров')).toBeVisible()
})

test('остатки по партиям отображаются с себестоимостью', async ({ page }) => {
  await mockSession(page)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: STOCK }))
  await page.goto('/')

  await expect(page.getByRole('heading', { level: 1, name: 'Партии и остатки' })).toBeVisible()
  const table = page.getByTestId('stock-table')
  await expect(table).toBeVisible()
  await expect(table.getByText('SKU-1')).toBeVisible()
  await expect(table.getByText('Материал', { exact: true })).toBeVisible()
  await expect(page.getByTestId('total-value')).toHaveText('1 500,00 ₽')
})

test('разделы переключаются', async ({ page }) => {
  await mockSession(page)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.goto('/')

  await page.getByRole('button', { name: 'PnL / Cashflow' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'PnL / Cashflow' })).toBeVisible()
  await expect(page.getByText('Модуль ещё не реализован.')).toBeVisible()
})

test('пустой список показывает подсказку', async ({ page }) => {
  await mockSession(page)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByTestId('empty-state')).toBeVisible()
})

test('менеджер заполняет план продаж и отправляет его на проверку', async ({ page }) => {
  let submitted = false
  await mockSession(page)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) =>
    route.fulfill({
      json: [
        { id: 'p-1', code: 'SKU-1', name: 'Товар 1', kind: 'goods', unit: 'шт', is_active: true },
      ],
    }),
  )
  await page.route('**/api/v1/sales-plans/*/submit', (route) => {
    submitted = true
    return route.fulfill({ json: plan({ status: 'on_review', status_title: 'На проверке' }) })
  })
  await page.route('**/api/v1/sales-plans/*/items', (route) => {
    const body = route.request().postDataJSON() as { items: { quantity: string }[] }
    return route.fulfill({
      json: plan({
        items: body.items.map((item, index) => ({
          id: `item-${index}`,
          product_id: 'p-1',
          product_code: 'SKU-1',
          product_name: 'Товар 1',
          product_kind: 'goods',
          unit: 'шт',
          month: index + 1,
          quantity: item.quantity,
          price: '100.00',
          amount: '1000.00',
          notes: null,
        })),
        total_amount: '12000.00',
      }),
    })
  })
  await page.route('**/api/v1/sales-plans', (route) =>
    route.fulfill({
      json: submitted ? [plan({ status: 'on_review', status_title: 'На проверке' })] : [plan()],
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'Планирование продаж' }).click()

  await expect(page.getByTestId('plan-table')).toBeVisible()
  await expect(page.getByTestId('plan-empty')).toBeVisible()

  await page.getByLabel('Добавить товар').selectOption('p-1')
  await page.getByRole('button', { name: 'Добавить строку' }).click()
  await page.getByLabel('Цена SKU-1').fill('100.00')
  await page.getByLabel('SKU-1 Декабрь').fill('10')

  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByTestId('plan-total')).toHaveText('1 000,00 ₽')

  await page.getByRole('button', { name: 'Отправить на проверку' }).click()
  await expect(page.getByText('На проверке')).toBeVisible()
})
