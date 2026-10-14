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

const IMPORTER = {
  id: 'im-1',
  login: 'import',
  full_name: 'Шахидул Ислам',
  role: 'import_manager',
  role_title: 'Менеджер по закупкам (импорт)',
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

const RECEIPT = {
  id: 'b1',
  batch_number: 'P-500',
  batch_type: 'purchase',
  batch_date: '2026-10-08',
  currency: 'USD',
  supplier_id: null,
  supplier: null,
  source: 'manual',
  comment: null,
  created_at: '2026-10-08T10:00:00Z',
  finance: {
    invoice_total_currency: '1000.00',
    total_paid_currency: '0.00',
    total_paid_rub: '0.00',
    additional_expenses_rub: '0.00',
    remaining_payment_currency: '1000.00',
    exchange_rate: '90',
    rate_date: '2026-10-08',
    rate_updated_at: '2026-10-08T10:00:00Z',
    planned_payments_currency: '0.00',
    planned_payments_rub: '0.00',
    planned_expenses_rub: '0.00',
    effective_rate: '90.000000',
    final_cost_rub: '90000.00',
  },
  payments: [],
  expenses: [],
  items: [
    {
      id: 'i1',
      product_code: 'SKU-1',
      product_name: 'Товар 1',
      product_kind: 'goods',
      unit: 'шт',
      quantity: '10.000',
      total_invoice_currency: '1000.00',
      item_total_rub: '90000.00',
      unit_cost: '9000.00',
      quantity_on_hand: '10.000',
    },
  ],
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

test('закупщик видит на «Загрузке данных» только импортные поступления', async ({ page }) => {
  await mockSession(page, IMPORTER)
  await page.route('**/api/v1/imports/kinds', (route) =>
    route.fulfill({
      json: [
        {
          kind: 'customers',
          title: 'Покупатели',
          entity: 'counterparties',
          columns: ['Наименование'],
          roles: ['sales_manager', 'commercial_director', 'purchase_director'],
          note: null,
        },
        {
          kind: 'import_receipts',
          title: 'Импортные поступления',
          entity: 'batches',
          columns: ['Номер', 'Дата', 'Контрагент', 'Комментарий'],
          roles: ['purchase_director', 'import_manager'],
          note: 'Создаёт черновики поступлений для календаря',
        },
      ],
    }),
  )
  await page.route('**/api/v1/imports?limit=20', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/imports/import_receipts', (route) =>
    route.fulfill({
      json: {
        id: 's2',
        kind: 'import_receipts',
        kind_title: 'Импортные поступления',
        file_name: 'ИмпортныеПоступления.xlsx',
        status: 'ok',
        rows_total: 15,
        rows_created: 15,
        rows_updated: 0,
        rows_skipped: 0,
        rows_failed: 0,
        message: null,
        created_at: '2026-10-13T12:00:00Z',
      },
    }),
  )

  await page.goto('/')
  await openSection(page, 'Администрирование', 'Загрузка данных')
  await expect(page.getByTestId('import-card-import_receipts')).toContainText(
    'Номер, Дата, Контрагент, Комментарий',
  )
  await expect(page.getByTestId('import-card-customers')).toHaveCount(0)

  await page.getByLabel('Файл: Импортные поступления').setInputFiles({
    name: 'ИмпортныеПоступления.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('xlsx'),
  })
  await page
    .getByTestId('import-card-import_receipts')
    .getByRole('button', { name: 'Загрузить' })
    .click()
  await expect(page.getByTestId('import-result-import_receipts')).toContainText('Создано: 15')
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
          roles: ['sales_manager', 'commercial_director', 'purchase_director'],
          note: null,
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

test('поступление заводится в календаре, себестоимость считается сразу', async ({ page }) => {
  await mockSession(page)
  await page.route('**/api/v1/batches**', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 201, json: RECEIPT })
      : route.fulfill({ json: [] }),
  )
  await page.route('**/api/v1/counterparties**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))

  await page.goto('/')
  await openSection(page, 'Закупки', 'Поступления')
  await expect(page.getByTestId('receipts-calendar')).toBeVisible()

  await page.getByRole('button', { name: 'Добавить поступление' }).click()
  await page.getByLabel('Номер поступления').fill('P-500')
  await page.getByLabel('Валюта').fill('USD')
  await page.getByLabel('Курс').fill('90')
  await page.getByLabel('Товар i0').fill('SKU-1')
  await page.getByLabel('Количество i0').fill('10')
  await page.getByLabel('Сумма i0').fill('1000')

  // Живой пересчёт: 1000 $ × 90 = 90 000 ₽, за единицу — 9 000 ₽.
  await expect(page.getByTestId('receipt-total')).toHaveText('90 000,00 ₽')
  await expect(page.getByTestId('unit-cost-i0')).toHaveText('9 000,00')

  // Валютный платёж закрывает часть инвойса по своему курсу и не переоценивается.
  await page.getByRole('button', { name: 'Добавить валютный платёж' }).click()
  await page.getByLabel('Сумма платежа pnew1').fill('600')
  await page.getByLabel('Курс платежа pnew1').fill('80')
  await expect(page.getByTestId('payment-rub-pnew1')).toHaveText('48 000,00')
  await expect(page.getByTestId('receipt-remaining')).toContainText('400,00')
  await expect(page.getByTestId('receipt-total')).toHaveText('84 000,00 ₽')
  await page.getByLabel('Курс', { exact: true }).fill('100')
  await expect(page.getByTestId('receipt-total')).toHaveText('88 000,00 ₽')
  await expect(page.getByTestId('payment-rub-pnew1')).toHaveText('48 000,00')

  // Платёж с будущей датой — только план, в себестоимость не входит.
  await page
    .locator('[data-testid="receipt-payments"] tbody tr')
    .first()
    .getByLabel(/Дата платежа/)
    .fill('2099-01-01')
  await expect(page.getByTestId('receipt-planned')).toContainText('600,00')
  await expect(page.getByTestId('receipt-paid')).toContainText('0,00')
  await expect(page.getByTestId('receipt-total')).toHaveText('100 000,00 ₽')

  // Платёж больше стоимости товаров — сохранение заблокировано.
  await page
    .locator('[data-testid="receipt-payments"] tbody tr')
    .first()
    .getByLabel(/Сумма платежа/)
    .fill('2000')
  await expect(page.getByTestId('receipt-limit-error')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Сохранить' })).toBeDisabled()

  // Возвращаем платёж в сегодняшнюю дату и сумму 600 — сохраняем.
  await page
    .locator('[data-testid="receipt-payments"] tbody tr')
    .first()
    .getByLabel(/Сумма платежа/)
    .fill('600')
  await page
    .locator('[data-testid="receipt-payments"] tbody tr')
    .first()
    .getByLabel(/Дата платежа/)
    .fill(new Date().toISOString().slice(0, 10))
  await expect(page.getByTestId('receipt-total')).toHaveText('88 000,00 ₽')

  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByTestId('receipt-form')).toHaveCount(0)
})

test('закупщик грузит позиции партии из файла 1С в черновик', async ({ page }) => {
  const today = new Date().toISOString().slice(0, 10)
  const draft = {
    ...RECEIPT,
    batch_date: today,
    source: '1c',
    comment: 'Грецкий орех 104 340 + сбор 30 065',
    items: [],
    payments: [],
    finance: {
      ...RECEIPT.finance,
      invoice_total_currency: '0.00',
      remaining_payment_currency: '0.00',
      effective_rate: '0.000000',
      final_cost_rub: '0.00',
    },
  }
  const loaded = {
    ...draft,
    items: [
      {
        id: 'i1',
        product_code: 'ТОВ395561',
        product_name: 'Грецкий орех сушеный, вес',
        product_kind: 'raw',
        unit: 'кг',
        quantity: '20000.000',
        total_invoice_currency: '0.00',
        item_total_rub: '0.00',
        unit_cost: '0.00',
        quantity_on_hand: '20000.000',
      },
    ],
  }
  const report = {
    id: 'r1',
    kind: 'batch_items',
    kind_title: 'Позиции партии',
    file_name: 'Партия.xlsx',
    status: 'ok',
    rows_total: 1,
    rows_created: 1,
    rows_updated: 0,
    rows_skipped: 0,
    rows_failed: 0,
    message: 'поступление P-500: загружено строк 1',
    created_at: '2026-10-14T10:00:00Z',
  }

  await mockSession(page, IMPORTER)
  await page.route('**/api/v1/batches**', (route) =>
    route.request().url().includes('/import-items')
      ? route.fulfill({ json: { batch: loaded, report } })
      : route.fulfill({ json: [draft] }),
  )
  await page.route('**/api/v1/counterparties**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))

  await page.goto('/')
  await openSection(page, 'Закупки', 'Поступления')
  await expect(page.getByTestId('receipts-calendar')).toBeVisible()

  await page.getByTestId(`day-receipt-b1`).getByRole('button', { name: 'Открыть' }).click()
  await expect(page.getByTestId('draft-hint')).toContainText('файл «Партия» из 1С')

  await page.getByLabel('Файл партии из 1С').setInputFiles({
    name: 'Партия.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('xlsx'),
  })
  const request = page.waitForRequest(
    (item) => item.url().includes('/import-items') && item.method() === 'POST',
  )
  await page.getByRole('button', { name: 'Загрузить позиции из 1С' }).click()
  expect((await request).url()).toContain('/api/v1/batches/b1/import-items')

  await expect(page.getByTestId('batch-items-hint')).toContainText('загружено строк: 1')
  await expect(page.getByLabel('Товар i0')).toHaveValue('ТОВ395561')
  await expect(page.getByLabel('Количество i0')).toHaveValue('20000')
  await expect(page.getByTestId('draft-hint')).toHaveCount(0)
})
