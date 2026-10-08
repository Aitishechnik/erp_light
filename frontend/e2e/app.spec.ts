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

const CLIENT = {
  id: 'client-1',
  name: 'ООО Ромашка',
  inn: '7701234567',
  note: null,
  is_active: true,
}

const PRODUCTS = [
  { id: 'p-1', code: 'SKU-1', name: 'Товар 1', kind: 'goods', unit: 'шт', is_active: true },
]

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
    items: [],
    ...overrides,
  }
}

async function mockSession(page: Page, user: Record<string, unknown> = MANAGER): Promise<void> {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ json: user }))
}

/** Меню сгруппировано: сначала раскрываем категорию, потом жмём раздел. */
async function openSection(page: Page, group: string, section: string): Promise<void> {
  const item = page.getByRole('button', { name: section, exact: true })
  if ((await item.count()) === 0) {
    await page.getByRole('button', { name: group, exact: true }).click()
  }
  await item.click()
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
  await page.getByLabel('Пароль').fill('123')
  await page.getByRole('button', { name: 'Войти' }).click()

  await page.getByRole('button', { name: 'Планирование', exact: true }).click()
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

  await openSection(page, 'Отчёты', 'PnL / Cashflow')
  await expect(page.getByRole('heading', { level: 1, name: 'PnL / Cashflow' })).toBeVisible()
  await expect(page.getByText('Модуль ещё не реализован.')).toBeVisible()
})

test('пустой список показывает подсказку', async ({ page }) => {
  await mockSession(page)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByTestId('empty-state')).toBeVisible()
})

test('контрагент заводится в справочнике с признаком покупателя', async ({ page }) => {
  let rows: unknown[] = []
  await mockSession(page)
  await page.route('**/api/v1/counterparties**', (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { name: string; is_customer: boolean }
      rows = [{ ...CLIENT, name: body.name, is_customer: body.is_customer }]
      return route.fulfill({ status: 201, json: rows[0] })
    }
    return route.fulfill({ json: rows })
  })

  await page.goto('/')
  await openSection(page, 'Справочники', 'Контрагенты')
  await expect(page.getByTestId('counterparties-table')).toContainText('Контрагентов не найдено')

  await page.getByLabel('Наименование контрагента').fill('ООО Ромашка')
  await page.getByLabel('ИНН').fill('7701234567')
  await page.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.getByTestId('counterparties-table')).toContainText('ООО Ромашка')
  await expect(page.getByTestId('counterparties-table')).toContainText('Покупатель')
  await expect(page.getByTestId('counterparties-count')).toHaveText('1')
})

test('файл выгрузки загружается на странице «Загрузка данных»', async ({ page }) => {
  await mockSession(page)
  await page.route('**/api/v1/imports/kinds', (route) =>
    route.fulfill({
      json: [
        {
          kind: 'customers',
          title: 'Покупатели',
          entity: 'counterparties',
          columns: ['Наименование'],
        },
      ],
    }),
  )
  await page.route('**/api/v1/imports?limit=20', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/imports/customers', (route) =>
    route.fulfill({
      json: {
        id: 's1',
        kind: 'customers',
        kind_title: 'Покупатели',
        file_name: 'Покупатели.xlsx',
        status: 'ok',
        rows_total: 789,
        rows_created: 775,
        rows_updated: 4,
        rows_skipped: 10,
        rows_failed: 0,
        message: null,
        created_at: '2026-10-08T01:00:00Z',
      },
    }),
  )

  await page.goto('/')
  await openSection(page, 'Администрирование', 'Загрузка данных')
  await expect(page.getByTestId('import-card-customers')).toContainText('Покупатели')

  await page.getByLabel('Файл: Покупатели').setInputFiles({
    name: 'Покупатели.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('test'),
  })
  await page.getByTestId('import-card-customers').getByRole('button', { name: 'Загрузить' }).click()

  await expect(page.getByTestId('import-result-customers')).toContainText('Создано: 775')
  await expect(page.getByTestId('import-result-customers')).toContainText('пропущено дублей: 10')
})

test('менеджер заполняет план продаж по клиенту и отправляет его на проверку', async ({ page }) => {
  let submitted = false
  await mockSession(page)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  await page.route('**/api/v1/counterparties**', (route) => route.fulfill({ json: [CLIENT] }))
  await page.route('**/api/v1/sales-plans/*/submit', (route) => {
    submitted = true
    return route.fulfill({ json: plan({ status: 'on_review', status_title: 'На проверке' }) })
  })
  await page.route('**/api/v1/sales-plans/*/items', (route) => {
    const body = route.request().postDataJSON() as {
      items: { quantity: string; client_id: string }[]
    }
    return route.fulfill({
      json: plan({
        items: body.items.map((item, index) => ({
          id: `item-${index}`,
          client_id: item.client_id,
          client_name: CLIENT.name,
          product_id: 'p-1',
          product_code: 'SKU-1',
          product_name: 'Товар 1',
          product_kind: 'goods',
          unit: 'шт',
          month: index + 1,
          quantity: item.quantity,
          notes: null,
        })),
      }),
    })
  })
  await page.route('**/api/v1/sales-plans', (route) =>
    route.fulfill({
      json: submitted ? [plan({ status: 'on_review', status_title: 'На проверке' })] : [plan()],
    }),
  )

  await page.goto('/')
  await openSection(page, 'Планирование', 'Планирование продаж')

  // Сначала в план добавляется клиент, потом строка товара.
  await expect(page.getByTestId('plan-no-clients')).toBeVisible()
  await page.getByLabel('Добавить клиента').selectOption('client-1')
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()
  await expect(page.getByTestId('current-client')).toContainText('ООО Ромашка')

  await page.getByLabel('Добавить товар').selectOption('p-1')
  await page.getByRole('button', { name: 'Добавить строку' }).click()
  await page.getByLabel('SKU-1 Декабрь').fill('10')

  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByTestId('row-total-SKU-1')).toHaveText('10 шт')

  await page.getByRole('button', { name: 'Отправить на проверку' }).click()
  await expect(page.getByText('На проверке')).toBeVisible()
})
