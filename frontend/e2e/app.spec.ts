import { expect, type Page, test } from '@playwright/test'

const STOCK = [
  {
    batch_item_id: 'item-1',
    batch_number: 'P-001',
    batch_date: '2026-10-01',
    product_code: 'SKU-1',
    product_name: 'Товар 1',
    product_kind: 'finished',
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
  { id: 'p-1', code: 'SKU-1', name: 'Товар 1', kind: 'finished', unit: 'шт', is_active: true },
]

const PURCHASE_DIRECTOR = {
  id: 'pd-1',
  login: 'purchase',
  full_name: 'Пётр Закупщиков',
  role: 'purchase_director',
  role_title: 'Директор по закупкам',
}

const RAW_PRODUCTS = [
  {
    id: 'raw-1',
    code: 'RAW-1',
    name: 'Орех грецкий, вес',
    kind: 'raw',
    unit: 'кг',
    is_active: true,
  },
]

const RAW_SUPPLIER = {
  id: 'sup-1',
  name: 'ООО Импорт',
  inn: null,
  note: null,
  is_customer: false,
  is_local_supplier: false,
  is_import_supplier: true,
  source: '1c',
  is_active: true,
}

const COUNTRIES = [
  { id: 'th-1', name: 'Таиланд', delivery_days: 90, is_active: true, source: 'manual' },
  { id: 'cn-1', name: 'Китай', delivery_days: 65, is_active: true, source: 'manual' },
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
  customs_date: null,
  customs_rate: null,
  finance: {
    invoice_total_currency: '1000.00',
    risk_total_currency: '0.00',
    exchange_rate: '90',
    rate_date: '2026-10-08',
    rate_updated_at: '2026-10-08T10:00:00Z',
    invoice_paid_currency: '0.00',
    invoice_paid_rub: '0.00',
    invoice_remaining_currency: '1000.00',
    invoice_rate: '90.000000',
    risk_paid_currency: '0.00',
    risk_paid_rub: '0.00',
    risk_remaining_currency: '0.00',
    risk_rate: '0.000000',
    planned_invoice_currency: '0.00',
    planned_invoice_rub: '0.00',
    planned_risk_currency: '0.00',
    planned_risk_rub: '0.00',
    expenses_rub: '0.00',
    duty_rub: '0.00',
    vat_rub: '0.00',
    average_rate: '90.000000',
    final_cost_rub: '90000.00',
  },
  payments: [],
  expenses: [],
  items: [
    {
      id: 'i1',
      product_code: 'SKU-1',
      product_name: 'Товар 1',
      product_kind: 'finished',
      unit: 'шт',
      quantity: '10.000',
      unit_price_currency: '100.0000',
      duty_percent: '0.0000',
      vat_percent: '0.0000',
      risk_unit_currency: '0.0000',
      duty_fixed_rub: null,
      vat_fixed_rub: null,
      purchase_plan_item_id: null,
      purchase_plan_label: null,
      invoice_currency: '1000.00',
      risk_currency: '0.00',
      duty_rub: '0.00',
      vat_rub: '0.00',
      risk_rub: '0.00',
      expenses_rub: '0.00',
      item_total_rub: '90000.00',
      unit_cost: '9000.00',
      quantity_on_hand: '10.000',
    },
  ],
}

const YEAR = new Date().getFullYear()

/** Локальная дата ГГГГ-ММ-ДД: toISOString() даёт UTC и может сдвинуть день. */
function localToday(): string {
  return new Intl.DateTimeFormat('sv-SE').format(new Date())
}
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

const COMMERCIAL = {
  id: 'cd-1',
  login: 'commercial',
  full_name: 'Коммерческий директор',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
}

const CORRECTION = {
  id: 'corr-1',
  plan_id: 'plan-1',
  status: 'draft',
  status_title: 'Черновик корректировки',
  created_by_name: 'Иван Петров',
  reviewed_by_name: null,
  reviewed_at: null,
  reason: null,
  review_reason: null,
  created_at: '2026-10-21T10:00:00Z',
  updated_at: '2026-10-21T10:00:00Z',
  items: [
    {
      id: 'ci-1',
      client_id: 'client-1',
      client_name: 'ООО Ромашка',
      product_id: 'p-1',
      product_code: 'SKU-1',
      product_name: 'Товар 1',
      unit: 'шт',
      month: 10,
      quantity: '20.000',
      current_quantity: '10.000',
      notes: null,
    },
  ],
}

function annual(overrides: Record<string, unknown> = {}) {
  return {
    year: YEAR,
    status: 'draft',
    status_title: 'Не отправлен',
    submitted_by_name: null,
    submitted_at: null,
    approved_by_name: null,
    approved_at: null,
    notes: null,
    is_stale: false,
    all_approved: true,
    missing_managers: [],
    managers: [
      {
        manager_id: 'sm-1',
        manager_name: 'Иван Петров',
        plan_id: 'plan-1',
        plan_status: 'approved',
        plan_status_title: 'Утверждён',
        approved: true,
        positions: 1,
        clients: 1,
      },
    ],
    items: [
      {
        manager_id: 'sm-1',
        manager_name: 'Иван Петров',
        client_id: 'client-1',
        client_name: 'ООО Ромашка',
        product_id: 'p-1',
        product_code: 'SKU-1',
        product_name: 'Товар 1',
        unit: 'шт',
        month: 10,
        quantity: '10.000',
      },
    ],
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

test('подпункты меню стоят не левее заголовка раздела и не переносятся', async ({ page }) => {
  await mockSession(page)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.goto('/')

  const menuBoxes = (group: string) =>
    page
      .locator('.sidebar .nav-group')
      .filter({ has: page.getByRole('button', { name: group, exact: true }) })
      .evaluate((node) => {
        const textBox = (el: Element) => {
          const text = [...el.childNodes].find((child) => child.nodeType === Node.TEXT_NODE)
          const range = document.createRange()
          range.selectNodeContents(text ?? el)
          const rects = range.getClientRects()
          return { left: rects[0]?.left ?? 0, lines: rects.length }
        }
        const head = node.querySelector('.nav-group-head') as Element
        const items = [...node.querySelectorAll('.nav-sublist .nav-item')]
        return {
          head: textBox(head),
          items: items.map((item) => ({ title: item.textContent?.trim() ?? '', ...textBox(item) })),
        }
      })

  for (const group of ['Планирование', 'Администрирование']) {
    await page.getByRole('button', { name: group, exact: true }).click()
    const boxes = await menuBoxes(group)

    expect(boxes.items.length).toBeGreaterThan(0)
    for (const item of boxes.items) {
      expect(item.title).toBeTruthy()
      expect(item.left, `${group} / ${item.title}: левее заголовка`).toBeGreaterThanOrEqual(
        boxes.head.left,
      )
      expect(item.lines, `${group} / ${item.title}: перенос строки`).toBe(1)
    }
  }

  // Выделенный пункт становится жирным и шире — он тоже обязан помещаться в одну строку.
  await page.getByRole('button', { name: 'Настройки приложения', exact: true }).click()
  const active = await menuBoxes('Администрирование')
  const settings = active.items.find((item) => item.title === 'Настройки приложения')
  expect(settings?.lines, 'Настройки приложения: перенос строки в выделенном пункте').toBe(1)
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
          product_kind: 'finished',
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

  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(page.getByTestId('row-total-SKU-1')).toHaveText('10 шт')

  await page.getByRole('button', { name: 'Отправить на проверку' }).click()
  await expect(page.getByText('На проверке')).toBeVisible()
})

test('закупщик раскладывает потребность плана продаж на сырьё', async ({ page }) => {
  const year = new Date().getFullYear()
  const position = {
    product_id: 'fin-1',
    code: 'FIN-1',
    name: 'Смесь ореховая, 100 гр',
    unit: 'шт',
    total: '300.000',
    months: [
      { month: 1, quantity: '100.000' },
      { month: 2, quantity: '200.000' },
    ],
    decomposed: false,
    status: 'ok',
    changed: false,
  }
  const source = {
    state: 'ok',
    title: 'План продаж не менялся с момента составления плана закупок',
    annual_status_title: 'Финально согласован',
    annual_approved_at: '2026-10-21T18:00:00Z',
    snapshot_at: '2026-10-21T18:10:00Z',
    acknowledged_at: '2026-10-21T18:10:00Z',
    changes: [],
    history: [],
    revision_requested_at: null,
    revision_requested_by_name: null,
  }
  let items: Record<string, unknown>[] = []
  let planStatus: 'draft' | 'on_review' = 'draft'

  function purchasePlan(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
      id: 'pp-1',
      year,
      status: planStatus,
      status_title: planStatus === 'draft' ? 'Черновик' : 'На проверке',
      created_by_name: 'Директор по закупкам',
      approved_by_name: null,
      approved_at: null,
      notes: null,
      created_at: '2026-10-21T10:00:00Z',
      updated_at: '2026-10-21T10:00:00Z',
      editable_months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
      source,
      positions: [{ ...position, decomposed: items.length > 0 }],
      items,
      ...overrides,
    }
  }

  await mockSession(page, PURCHASE_DIRECTOR)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products**', (route) => route.fulfill({ json: RAW_PRODUCTS }))
  await page.route('**/api/v1/counterparties**', (route) => route.fulfill({ json: [RAW_SUPPLIER] }))
  await page.route('**/api/v1/countries**', (route) => route.fulfill({ json: COUNTRIES }))
  await page.route('**/api/v1/purchase-plans**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/items')) {
      const body = request.postDataJSON() as {
        items: {
          sales_product_id: string
          product_id: string
          country_id: string
          quantity: string
          price_rub: string | null
          alternative_of_id: string | null
        }[]
      }
      items = body.items.map((item, index) => ({
        id: `pi-${index}`,
        alternative_of_id: item.alternative_of_id ?? null,
        sales_product_id: item.sales_product_id,
        product_id: item.product_id,
        product_code: 'RAW-1',
        product_name: 'Орех грецкий, вес',
        product_kind: 'raw',
        unit: 'кг',
        country_id: item.country_id,
        country_name: 'Таиланд',
        delivery_days: 90,
        quantity: Number(item.quantity).toFixed(3),
        price_rub: item.price_rub === null ? null : Number(item.price_rub).toFixed(2),
        notes: null,
        fact_quantity: '0',
        fact_share: '0',
        fact_months: [],
        schedule: [
          {
            month: 1,
            quantity: '10.000',
            order_year: year - 1,
            order_month: 10,
            overdue: false,
          },
          {
            month: 2,
            quantity: '20.000',
            order_year: year - 1,
            order_month: 11,
            overdue: false,
          },
        ],
      }))
      return route.fulfill({ json: purchasePlan() })
    }
    if (path.endsWith('/submit')) {
      planStatus = 'on_review'
      return route.fulfill({ json: purchasePlan() })
    }
    return route.fulfill({ json: [purchasePlan()] })
  })

  await page.goto('/')
  await openSection(page, 'Планирование', 'План закупок сырья')
  await expect(page.getByTestId('purchase-status')).toHaveText('Черновик')
  await expect(page.getByTestId('position-FIN-1')).toContainText('300')
  await expect(page.getByTestId('empty-FIN-1')).toContainText('Сырьё не добавлено')

  await page.getByRole('button', { name: 'Добавить сырьё FIN-1' }).click()
  await page.getByLabel('Сырьё FIN-1 1').selectOption('raw-1')
  await page.getByLabel('Страна FIN-1 1').selectOption('th-1')
  await page.getByLabel('Количество FIN-1 1').fill('30')
  await page.getByLabel('Цена FIN-1 1').fill('500')
  await expect(page.getByTestId('purchase-table')).toContainText('Ближайший заказ')
  await expect(page.getByTestId('purchase-table')).toContainText('10 кг')
  // Видов графика два — «кратко» и «кварталы»; вид «полосой» убран.
  await expect(page.getByRole('button', { name: 'полосой' })).toHaveCount(0)
  await page.getByRole('button', { name: 'кварталы' }).click()
  await expect(page.getByTestId('schedule-quarters')).toContainText('I квартал')
  await expect(page.getByTestId('schedule-bars')).toHaveCount(0)
  // Кнопка таблицы — своя у каждой позиции и всегда в ячейке «График заказа».
  const toggles = page.getByRole('button', { name: 'Показать таблицей' })
  const toggleCount = await toggles.count()
  expect(toggleCount).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'кратко' }).click()
  await toggles.first().click()
  // Раскрылась одна позиция: у остальных кнопка по-прежнему «Показать таблицей».
  await expect(page.getByRole('button', { name: 'Скрыть таблицу' })).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Показать таблицей' })).toHaveCount(toggleCount - 1)
  const detail = page.getByTestId('schedule-table').first()
  await expect(detail).toBeVisible()
  await expect(detail).toContainText('Месяц потребности')

  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(page.getByTestId('purchase-table')).toContainText('Таиланд')
  await expect(page.getByTestId('position-FIN-1')).toContainText('разложено')

  // Альтернатива — под основной строкой: у неё своё сырьё и своя страна.
  await page.getByRole('button', { name: 'Добавить альтернативу FIN-1 1' }).click()
  await page.getByLabel('Сырьё FIN-1 2').selectOption('raw-1')
  await page.getByLabel('Страна FIN-1 2').selectOption('cn-1')
  await page.getByLabel('Количество FIN-1 2').fill('10')
  await page.getByLabel('Цена FIN-1 2').fill('450')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(page.getByTestId('alt-badge-pi-1')).toContainText('альтернатива')
  await expect(page.getByTestId('alt-pi-1')).toContainText('план 10')

  await page.getByRole('button', { name: 'Отправить на согласование' }).click()
  await expect(page.getByTestId('purchase-status')).toHaveText('На проверке')
})

test('страна со сроком доставки заводится в справочнике', async ({ page }) => {
  let rows: Record<string, unknown>[] = []
  await mockSession(page, PURCHASE_DIRECTOR)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/countries**', (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { name: string; delivery_days: number }
      rows = [
        {
          id: 'th-1',
          name: body.name,
          delivery_days: body.delivery_days,
          is_active: true,
          source: 'manual',
        },
      ]
      return route.fulfill({ status: 201, json: rows[0] })
    }
    return route.fulfill({ json: rows })
  })

  await page.goto('/')
  await openSection(page, 'Справочники', 'Страны')
  await expect(page.getByTestId('countries-empty')).toBeVisible()

  await page.getByLabel('Название страны').fill('Таиланд')
  await page.getByLabel('Срок доставки, дней').fill('90')
  await page.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.getByTestId('countries-table')).toContainText('Таиланд')
  await expect(page.getByTestId('countries-table')).toContainText('90 дн')
  await expect(page.getByTestId('countries-count')).toHaveText('1')
})

test('коммерческий директор отправляет годовой план отдела на финальное согласование', async ({
  page,
}) => {
  let submitted = false
  await mockSession(page, COMMERCIAL)
  await page.route('**/api/v1/annual-sales-plans**', (route) => {
    if (route.request().method() === 'POST') {
      submitted = true
      return route.fulfill({
        json: annual({ status: 'on_review', status_title: 'На финальном согласовании' }),
      })
    }
    return route.fulfill({
      json: annual({
        status: submitted ? 'on_review' : 'draft',
        status_title: submitted ? 'На финальном согласовании' : 'Не отправлен',
      }),
    })
  })

  await page.goto('/')
  await openSection(page, 'Планирование', 'Годовой план отдела')
  await expect(page.getByTestId('annual-status')).toContainText('Не отправлен')
  await expect(page.getByTestId('annual-managers')).toContainText('Иван Петров')

  await page.getByRole('button', { name: 'Отправить на финальное согласование' }).click()
  await expect(page.getByTestId('annual-status')).toContainText('На финальном согласовании')
})

test('менеджер предлагает корректировку утверждённого плана', async ({ page }) => {
  let created = false
  await mockSession(page)
  await page.route('**/api/v1/sales-plans', (route) =>
    route.fulfill({
      json: [
        plan({
          status: 'approved',
          status_title: 'Утверждён',
          items: [
            {
              id: 'item-1',
              client_id: 'client-1',
              client_name: 'ООО Ромашка',
              product_id: 'p-1',
              product_code: 'SKU-1',
              product_name: 'Товар 1',
              product_kind: 'finished',
              unit: 'шт',
              month: 10,
              quantity: '10.000',
              notes: null,
            },
          ],
        }),
      ],
    }),
  )
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  await page.route('**/api/v1/counterparties**', (route) => route.fulfill({ json: [CLIENT] }))
  await page.route('**/api/v1/sales-plan-corrections**', (route) => {
    if (route.request().method() === 'POST') {
      created = true
      return route.fulfill({ status: 201, json: CORRECTION })
    }
    return route.fulfill({ json: created ? [CORRECTION] : [] })
  })

  await page.goto('/')
  await openSection(page, 'Планирование', 'Планирование продаж')
  await page.getByRole('button', { name: 'Предложить корректировку' }).click()
  await expect(page.getByTestId('correction-box')).toContainText('Черновик корректировки')
})

test('поступление из 1С открывается в календаре, себестоимость считается сразу', async ({
  page,
}) => {
  await mockSession(page, PURCHASE_DIRECTOR)
  await page.route('**/api/v1/batches**', (route) =>
    route.request().method() === 'PUT'
      ? route.fulfill({ json: RECEIPT })
      : route.fulfill({ json: [{ ...RECEIPT, batch_date: localToday() }] }),
  )
  await page.route('**/api/v1/counterparties**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  await page.route('**/api/v1/purchase-plans**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/rates/USD', (route) =>
    route.fulfill({
      json: { code: 'USD', rate_date: '2026-10-14', rate: '90.5000', nominal: 1, source: 'cbr' },
    }),
  )

  await page.goto('/')
  await openSection(page, 'Закупки', 'Поступления')
  await expect(page.getByTestId('receipts-calendar')).toBeVisible()

  // Поступления создаются выгрузкой 1С: открываем уже загруженное поступление.
  await page.getByTestId('day-receipt-b1').click()
  await expect(page.getByTestId('receipt-number')).toHaveText('P-500')
  // НДС не в теме этого сценария: обнуляем, чтобы суммы остались круглыми.
  await page.getByLabel('НДС i0').fill('0')

  // Живой пересчёт: 1000 $ × 90 = 90 000 ₽, за единицу — 9 000 ₽.
  await expect(page.getByTestId('receipt-total')).toHaveText('90 000,00 ₽')
  await expect(page.getByTestId('unit-cost-i0')).toHaveText('9 000,00')

  // Валютный платёж закрывает часть инвойса по своему курсу и не переоценивается.
  await page.getByRole('button', { name: 'Платежи' }).click()
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

  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  // Карточка остаётся открытой и показывает сохранённое поступление.
  await expect(page.getByTestId('receipt-saved')).toBeVisible()
  await expect(page.getByTestId('receipt-form')).toBeVisible()
})

test('пошлина, Risk и общие расходы считаются в карточке партии', async ({ page }) => {
  const posted: Record<string, unknown>[] = []
  await mockSession(page, PURCHASE_DIRECTOR)
  await page.route('**/api/v1/batches**', (route) => {
    if (route.request().method() === 'PUT') {
      posted.push(route.request().postDataJSON() as Record<string, unknown>)
      return route.fulfill({ json: RECEIPT })
    }
    return route.fulfill({ json: [{ ...RECEIPT, batch_date: localToday() }] })
  })
  await page.route('**/api/v1/counterparties**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  await page.route('**/api/v1/purchase-plans**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/rates/USD', (route) =>
    route.fulfill({
      json: { code: 'USD', rate_date: '2026-10-14', rate: '90.5000', nominal: 1, source: 'cbr' },
    }),
  )

  await page.goto('/')
  await openSection(page, 'Закупки', 'Поступления')
  await page.getByTestId('day-receipt-b1').click()
  await page.getByLabel('Курс', { exact: true }).fill('90')
  await page.getByLabel('Товар i0').fill('SKU-1')
  await page.getByLabel('Количество i0').fill('10')
  await page.getByLabel('Стоимость за ед. i0').fill('100')
  await page.getByLabel('НДС i0').fill('0')
  await page.getByLabel('Пошлина i0').fill('5')
  await page.getByLabel('Risk i0').fill('1')

  // (100 + 5) × 90 + 1 × 90 = 9 540 ₽ за единицу, 95 400 ₽ за строку.
  await expect(page.getByTestId('unit-cost-i0')).toHaveText('9 540,00')
  await expect(page.getByTestId('receipt-total')).toHaveText('95 400,00 ₽')
  await page.getByRole('button', { name: 'Себестоимость' }).click()
  await expect(page.getByTestId('receipt-risk-total')).toContainText('10,00')
  await expect(page.getByTestId('receipt-duty')).toContainText('4 500,00')

  // Общий расход в рублях входит в себестоимость целиком.
  await page.getByRole('button', { name: 'Общие расходы' }).click()
  await page.getByRole('button', { name: 'Добавить расход' }).click()
  await page.getByLabel('Расход enew1').fill('Доставка')
  await page.getByLabel('Сумма расхода enew1').fill('5000')
  await expect(page.getByTestId('receipt-expenses-rub')).toContainText('5 000,00')
  await expect(page.getByTestId('receipt-total')).toHaveText('100 400,00 ₽')

  // Платёж категории Risk закрывает Risk по своему курсу.
  await page.getByRole('button', { name: 'Платежи' }).click()
  await page.getByRole('button', { name: 'Добавить валютный платёж' }).click()
  const payRow = page.locator('[data-testid="receipt-payments"] tbody tr').first()
  await payRow.getByLabel(/Категория платежа/).selectOption('risk')
  await payRow.getByLabel(/Сумма платежа/).fill('10')
  await payRow.getByLabel(/Курс платежа/).fill('100')
  await expect(payRow).toContainText('1 000,00')
  await expect(page.getByTestId('receipt-total')).toHaveText('100 500,00 ₽')
  // Средний курс — по инвойсу и Risk: (90 × 1000 + 100 × 10) ÷ 1010 = 90,099.
  await expect(page.getByTestId('receipt-average-rate')).toHaveText('90.099')
  await expect(page.getByTestId('receipt-risk-rate')).toHaveText('100')

  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  // Карточка остаётся открытой и показывает сохранённое поступление.
  await expect(page.getByTestId('receipt-saved')).toBeVisible()
  await expect(page.getByTestId('receipt-form')).toBeVisible()

  const body = posted[0] as {
    payments: { category: string }[]
    expenses: { currency: string; amount_currency: string }[]
    items: { unit_price_currency: string; duty_percent: string; risk_unit_currency: string }[]
  }
  expect(body.payments[0]?.category).toBe('risk')
  expect(body.expenses[0]?.currency).toBe('RUB')
  expect(body.expenses[0]?.amount_currency).toBe('5000')
  expect(body.items[0]?.unit_price_currency).toBe('100')
  expect(body.items[0]?.duty_percent).toBe('5')
  expect(body.items[0]?.risk_unit_currency).toBe('1')
})

test('растаможка партии: проценты превращаются в фиксированные рубли', async ({ page }) => {
  const today = localToday()
  const taxed = {
    ...RECEIPT,
    batch_date: today,
    items: [{ ...RECEIPT.items[0], duty_percent: '5.0000', vat_percent: '22.0000' }],
  }
  const cleared = {
    ...taxed,
    customs_date: today,
    customs_rate: '80',
    items: [{ ...taxed.items[0], duty_fixed_rub: '4000.00', vat_fixed_rub: '18480.00' }],
  }
  const sent: Record<string, unknown>[] = []
  await mockSession(page, PURCHASE_DIRECTOR)
  await page.route('**/api/v1/batches**', (route) => {
    if (route.request().url().endsWith('/customs')) {
      sent.push(route.request().postDataJSON() as Record<string, unknown>)
      return route.fulfill({ json: cleared })
    }
    // После растаможки список за день тоже показывает пометку — как на сервере.
    return route.fulfill({ json: [sent.length > 0 ? cleared : taxed] })
  })
  await page.route('**/api/v1/counterparties**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  // Курс на дату растаможки приходит с query — шаблон с «**» его тоже ловит.
  // ЦБ отвечает своим курсом на каждую дату: остаток — актуальный, таможня — на свою дату.
  await page.route('**/api/v1/rates/USD**', (route) => {
    const day = new URL(route.request().url()).searchParams.get('date')
    return route.fulfill({
      json: {
        code: 'USD',
        rate_date: day ?? today,
        rate: day === '2026-10-08' ? '84.9048' : '90.5000',
        nominal: 1,
        source: 'cbr',
      },
    })
  })

  await page.goto('/')
  await openSection(page, 'Закупки', 'Поступления')
  await page.getByTestId('day-receipt-b1').click()
  await page.getByTestId('customs-start').click()

  // Курс подставляется из ЦБ на дату растаможки: 50 $ × 90,5 = 4 525 ₽ пошлины.
  await expect(page.getByLabel('Курс растаможки')).toHaveValue('90.5')
  await expect(page.getByTestId('customs-duty-total')).toHaveText('4 525,00 ₽')
  await expect(page.getByTestId('customs-vat-total')).toHaveText('20 905,50 ₽')
  // Пока окно открыто, свойства строк заперты: суммы в окне уже посчитаны.
  await expect(page.getByLabel('Количество i0')).toBeDisabled()
  await expect(page.getByLabel('Пошлина i0')).toBeDisabled()
  await expect(page.getByLabel('НДС i0')).toBeDisabled()
  await expect(page.getByLabel('Стоимость за ед. i0')).toBeDisabled()

  // Сменили дату растаможки — курс ЦБ на неё подтянулся сам, суммы пересчитались.
  await page.getByLabel('Дата растаможки').fill('2026-10-08')
  await expect(page.getByLabel('Курс растаможки')).toHaveValue('84.9048')
  await expect(page.getByTestId('customs-duty-total')).toHaveText('4 245,24 ₽')
  await expect(page.getByTestId('customs-vat-total')).toHaveText('19 613,01 ₽')

  // Курс правят на таможенный — суммы пересчитываются по строкам.
  await page.getByLabel('Курс растаможки').fill('80')
  await expect(page.getByTestId('customs-duty-total')).toHaveText('4 000,00 ₽')
  await expect(page.getByTestId('customs-vat-total')).toHaveText('18 480,00 ₽')
  // Сумму пошлины по-прежнему можно поправить руками.
  await page.getByLabel('Пошлина партии, ₽').fill('4100')
  await expect(page.getByTestId('customs-duty-total')).toHaveText('4 100,00 ₽')
  await page.getByLabel('Пошлина партии, ₽').fill('4000')
  await page.getByTestId('customs-confirm').click()

  await expect(page.getByTestId('customs-badge')).toBeVisible()
  await expect(page.getByTestId('item-duty-i0')).toHaveText('4 000,00')
  await expect(page.getByTestId('item-vat-i0')).toHaveText('18 480,00')
  // Проценты в строках исчезли: вместо полей — зафиксированные рубли.
  await expect(page.getByLabel('Пошлина i0')).toHaveCount(0)
  await expect(page.getByLabel('НДС i0')).toHaveCount(0)
  // Пометка видна в списке дня слева.
  await expect(page.getByTestId('clearance-badge')).toBeVisible()

  expect(sent[0]?.rate).toBe('80')
  expect(sent[0]?.duty_rub).toBe('4000')
  expect(sent[0]?.vat_rub).toBe('18480')
})

test('закупщик грузит позиции партии из файла 1С в черновик', async ({ page }) => {
  const today = localToday()
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
      invoice_remaining_currency: '0.00',
      invoice_rate: '0.000000',
      average_rate: '0.000000',
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
        unit_price_currency: '0.0000',
        duty_percent: '0.0000',
        vat_percent: '22.0000',
        risk_unit_currency: '0.0000',
        duty_fixed_rub: null,
        vat_fixed_rub: null,
        invoice_currency: '0.00',
        risk_currency: '0.00',
        duty_rub: '0.00',
        vat_rub: '0.00',
        risk_rub: '0.00',
        expenses_rub: '0.00',
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

  await page.getByTestId('day-receipt-b1').click()
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
  // Колонка «Товар»: в поле — название позиции, код из 1С — под полем.
  await expect(page.getByRole('columnheader', { name: 'Товар', exact: true })).toBeVisible()
  await expect(page.getByLabel('Товар i0')).toHaveValue('Грецкий орех сушеный, вес')
  await expect(page.getByTestId('product-code-i0')).toHaveText('код ТОВ395561')
  await expect(page.getByLabel('Количество i0')).toHaveValue('20000')
  await expect(page.getByTestId('draft-hint')).toHaveCount(0)
})

const MONTH_RESULT = {
  year: 2026,
  month: 10,
  plan_approved: true,
  rows: [
    {
      client_id: 'client-1',
      client_name: 'ООО Ромашка',
      manager_id: 'sm-1',
      manager_name: 'Иван Петров',
      product_id: 'p-1',
      product_name: 'Товар 1',
      unit: 'шт',
      plan_quantity: '100.000',
      fact_quantity: '80.000',
      fact_amount: '8000.00',
      deviation: '-20.000',
      group: 'plan',
      manager_mismatch: false,
    },
    {
      client_id: 'client-1',
      client_name: 'ООО Ромашка',
      manager_id: 'sm-1',
      manager_name: 'Иван Петров',
      product_id: 'p-2',
      product_name: 'Арахис жареный',
      unit: 'кг',
      plan_quantity: '0.000',
      fact_quantity: '10.000',
      fact_amount: '1000.00',
      deviation: '10.000',
      group: 'extra',
      manager_mismatch: false,
    },
  ],
  unmatched: [
    {
      id: 'un-1',
      source_name: 'Загадочный товар',
      client_name: 'ООО Ромашка',
      quantity: '1.000',
      amount_rub: '10.00',
    },
  ],
  lines: 2,
  deviation_lines: 2,
  extra_lines: 1,
  short_lines: 0,
  without_reason: 2,
  reason_options: [
    { code: 'return', title: 'Возврат клиента' },
    { code: 'quality', title: 'Качество продукции' },
    { code: 'other', title: 'Другое' },
  ],
  fact_amount: '8100.00',
  status: 'open',
  closed_by_name: null,
  closed_at: null,
  reopen_reason: null,
  decision: null,
}

test('итоги месяца: план против факта и очередь сопоставления', async ({ page }) => {
  await mockSession(page, COMMERCIAL)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  await page.route('**/api/v1/month-results**', (route) => route.fulfill({ json: MONTH_RESULT }))
  await page.goto('/')

  await openSection(page, 'Отчёты', 'Итоги месяца')
  await expect(page.getByRole('heading', { level: 1, name: 'Итоги месяца' })).toBeVisible()

  const table = page.getByTestId('month-table')
  await expect(table.getByText('Товар 1')).toBeVisible()
  await expect(table.getByText('-20')).toBeVisible()
  await expect(table.getByText('80,0 %')).toBeVisible()
  await expect(table.getByText('вне плана')).toBeVisible()

  const unmatched = page.getByTestId('unmatched-box')
  await expect(unmatched).toContainText('Загадочный товар')
  await expect(page.getByRole('button', { name: 'Сопоставить' })).toBeVisible()

  await page.getByLabel('Месяц итогов').selectOption('9')
  await expect(page.getByTestId('month-summary')).toContainText('Строк: 2')
})

test('причина отклонения сохраняется из строки итогов', async ({ page }) => {
  await mockSession(page, COMMERCIAL)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  await page.route('**/api/v1/month-results**', (route) => route.fulfill({ json: MONTH_RESULT }))
  await page.route('**/api/v1/month-results/**/reasons', (route) =>
    route.fulfill({
      json: {
        code: 'quality',
        title: 'Качество продукции',
        comment: 'горчит',
        author_name: 'Коммерческий директор',
        updated_at: '2026-10-26T10:00:00Z',
      },
    }),
  )
  await page.goto('/')

  await openSection(page, 'Отчёты', 'Итоги месяца')
  await page.getByRole('button', { name: '+ причина' }).first().click()
  await page.getByLabel('Причина отклонения').selectOption('quality')
  await page.getByLabel('Комментарий к причине').fill('горчит')

  const saved = page.waitForRequest(
    (request) => request.url().includes('/reasons') && request.method() === 'PUT',
  )
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  const body = JSON.parse((await saved).postData() ?? '{}') as Record<string, string>
  expect(body.reason).toBe('quality')
  expect(body.comment).toBe('горчит')
  expect(body.client_id).toBe('client-1')
})

test('месяц закрывается и показывает снимок', async ({ page }) => {
  let closed = false
  const state = () => ({
    ...MONTH_RESULT,
    status: closed ? 'closed' : 'open',
    closed_by_name: closed ? 'Коммерческий директор' : null,
    closed_at: closed ? '2026-10-26T10:00:00Z' : null,
  })

  await mockSession(page, COMMERCIAL)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  // Маршруты проверяются с конца: общий регистрируем первым, закрытие — последним.
  await page.route('**/api/v1/month-results**', (route) => route.fulfill({ json: state() }))
  await page.route('**/api/v1/month-results/**/close', (route) => {
    closed = true
    return route.fulfill({ json: state() })
  })
  await page.goto('/')

  await openSection(page, 'Отчёты', 'Итоги месяца')
  await expect(page.getByTestId('month-state')).toContainText('месяц открыт')

  await page.getByRole('button', { name: 'Закрыть месяц' }).click()
  await expect(page.getByTestId('close-confirm')).toContainText('Снимок зафиксирует')
  await page.getByTestId('close-confirm').getByRole('button', { name: 'Закрыть месяц' }).click()

  await expect(page.getByTestId('month-state')).toContainText('месяц закрыт')
  await expect(page.getByText(/Снимок зафиксирован/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Закрыть месяц' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Открыть заново' })).toBeVisible()
})

const EXECUTIVE = {
  id: 'ed-1',
  login: 'executive',
  full_name: 'Ольга Директорова',
  role: 'executive_director',
  role_title: 'Исполнительный директор',
}

const AUDIT_EVENT = {
  id: 'ev-1',
  created_at: '2026-10-27T10:00:00Z',
  action: 'sales_plan.approved',
  action_title: 'План продаж утверждён',
  level: 'critical',
  entity_kind: 'sales_plan',
  entity_id: 'plan-1',
  entity_label: 'Менеджер по продажам (демо), 2026',
  summary: 'План продаж на 2026 год утверждён: Менеджер по продажам (демо)',
  actor_name: 'Коммерческий директор (демо)',
  actor_role_title: 'Коммерческий директор',
  year: 2026,
  month: null,
  read: false,
}

test('колокольчик приносит директору служебные сообщения и открывает журнал', async ({ page }) => {
  await mockSession(page, EXECUTIVE)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/messages**', (route) =>
    route.fulfill({ json: { rows: [AUDIT_EVENT], unread: 1, total: 1 } }),
  )
  await page.route('**/api/v1/messages/count', (route) => route.fulfill({ json: { unread: 1 } }))
  await page.route('**/api/v1/audit**', (route) => route.fulfill({ json: [AUDIT_EVENT] }))
  await page.route('**/api/v1/messages/read-all', (route) => route.fulfill({ json: { unread: 0 } }))

  await page.goto('/')
  await expect(page.getByTestId('bell-badge')).toHaveText('1')

  await page.getByLabel(/Служебные сообщения, непрочитанных: 1/).click()
  await expect(page.getByTestId('bell-list')).toContainText('План продаж на 2026 год утверждён')

  await page.getByRole('button', { name: 'Весь журнал' }).click()
  await expect(page.getByTestId('audit-table')).toContainText('План продаж утверждён')
  await expect(page.getByTestId('messages-unread')).toContainText('Непрочитанных: 1')
})

test('ссылка из журнала открывает объект и подсвечивает строку', async ({ page }) => {
  await mockSession(page, EXECUTIVE)
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: PRODUCTS }))
  await page.route('**/api/v1/audit/cleanup', (route) => route.fulfill({ json: null }))
  await page.route('**/api/v1/messages**', (route) =>
    route.fulfill({
      json: {
        rows: [
          {
            ...AUDIT_EVENT,
            action: 'product.updated',
            action_title: 'Изменена номенклатура',
            entity_kind: 'product',
            entity_id: 'p-1',
            entity_label: 'SKU-1 · Товар 1',
            summary: 'Изменена номенклатура SKU-1 · Товар 1',
            link: '#/nomenclature/p-1',
          },
        ],
        unread: 0,
        total: 1,
      },
    }),
  )
  await page.route('**/api/v1/messages/count', (route) => route.fulfill({ json: { unread: 0 } }))
  await page.route('**/api/v1/audit**', (route) =>
    route.fulfill({
      json: [
        {
          ...AUDIT_EVENT,
          action: 'product.updated',
          entity_kind: 'product',
          entity_id: 'p-1',
          summary: 'Изменена номенклатура SKU-1 · Товар 1',
          link: '#/nomenclature/p-1',
        },
      ],
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'Администрирование', exact: true }).click()
  await page.getByRole('button', { name: 'Служебные сообщения', exact: true }).click()

  await page.getByRole('link', { name: /Изменена номенклатура SKU-1/ }).click()
  await expect(page).toHaveURL(/#\/nomenclature\/p-1/)
  await expect(page.getByRole('heading', { level: 1, name: 'Номенклатура' })).toBeVisible()
  await expect(page.locator('tr.focus-row')).toContainText('SKU-1')
})

const SALES_USER = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Иван Петров',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

const COMMERCIAL_USER = {
  id: 'cd-1',
  login: 'commercial',
  full_name: 'Ольга Коммерческая',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
}

type TaskReportMock = {
  id: string
  kind: 'interim' | 'final'
  kind_title: string
  step_id: string | null
  step_title: string | null
  progress: number
  text: string
  author_id: string
  author_name: string
  created_at: string
  files: { id: string; original_name: string; size_bytes: number }[]
}

test('таск-трекер: коммерческий ставит задачу, менеджер закрывает этап и задачу', async ({
  page,
}) => {
  let session: Record<string, unknown> = COMMERCIAL_USER
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ json: session }))
  await page.route('**/api/v1/stock', (route) => route.fulfill({ json: [] }))

  let task: Record<string, unknown> | null = null
  const reports: TaskReportMock[] = []
  const steps: Record<string, unknown>[] = []
  const messages: { summary: string; created_at: string }[] = []

  const detail = () => {
    const current = task ?? {}
    const done = current.status === 'done'
    const assignee = current.assignee_id as string | undefined
    const creator = current.created_by_id as string | undefined
    const userId = session.id as string
    return {
      ...current,
      steps: steps.map((step) => ({
        ...step,
        is_done: Boolean(step.is_done),
        has_report: reports.some((row) => row.step_id === step.id),
        needs_report: false,
      })),
      reports,
      reports_count: reports.length,
      files_count: reports.reduce((sum, row) => sum + row.files.length, 0),
      actions: {
        can_edit: userId === creator && !done,
        can_change_status: (userId === creator || userId === assignee) && !done,
        can_report: userId === assignee && !done,
        can_delete: userId === creator && reports.length === 0,
        can_reopen: userId === creator && done,
      },
    }
  }

  await page.route('**/api/v1/tasks**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    if (path.endsWith('/assignees')) {
      return route.fulfill({
        json: [
          { id: 'sm-1', full_name: 'Иван Петров', role_title: 'Менеджер по продажам' },
          {
            id: 'as-1',
            full_name: 'Анна Ассистент',
            role_title: 'Ассистент отдела продаж',
          },
        ],
      })
    }
    if (path === '/api/v1/tasks' && method === 'GET') {
      return route.fulfill({ json: task ? [task] : [] })
    }
    if (path === '/api/v1/tasks' && method === 'POST') {
      const body = JSON.parse(request.postData() ?? '{}') as Record<string, unknown>
      task = {
        id: 'task-1',
        title: String(body.title),
        description: (body.description as string | null) ?? null,
        priority: (body.priority as string) ?? 'yellow',
        priority_title: 'Обычный',
        status: 'in_progress',
        status_title: 'В работе',
        progress: 0,
        start_date: String(body.start_date),
        due_date: String(body.due_date),
        assignee_id: String(body.assignee_id),
        assignee_name: 'Иван Петров',
        created_by_id: 'cd-1',
        created_by_name: 'Ольга Коммерческая',
        closed_at: null,
        created_at: '2026-11-01T09:00:00Z',
        updated_at: '2026-11-01T09:00:00Z',
        is_overdue: false,
        days_overdue: 0,
        last_report: null,
      }
      messages.push({
        summary: `Поставлена задача «${String(body.title)}»`,
        created_at: '2026-11-01T09:00:00Z',
      })
      return route.fulfill({ status: 201, json: detail() })
    }
    if (path.endsWith('/reschedule') && method === 'POST') {
      const body = JSON.parse(request.postData() ?? '{}') as Record<string, string>
      task = { ...(task ?? {}), start_date: body.start_date, due_date: body.due_date }
      return route.fulfill({ json: detail() })
    }
    if (path.endsWith('/steps') && method === 'POST') {
      const body = JSON.parse(request.postData() ?? '{}') as Record<string, unknown>
      steps.push({
        id: `step-${steps.length + 1}`,
        title: String(body.title),
        start_date: String(body.start_date),
        due_date: String(body.due_date),
        position: steps.length,
      })
      return route.fulfill({ json: detail() })
    }
    if (path.endsWith('/reports') && method === 'POST') {
      const body = JSON.parse(request.postData() ?? '{}') as {
        kind: 'interim' | 'final'
        text: string
        progress: number
        step_id: string | null
      }
      const final = body.kind === 'final'
      const step = steps.find((row) => row.id === body.step_id)
      if (step) step.is_done = true
      const report: TaskReportMock = {
        id: `report-${reports.length + 1}`,
        kind: body.kind,
        kind_title: final ? 'Финальный' : 'Промежуточный',
        step_id: body.step_id,
        step_title: step ? String(step.title) : null,
        progress: final ? 100 : body.progress,
        text: body.text,
        author_id: 'sm-1',
        author_name: 'Иван Петров',
        created_at: '2026-11-01T10:00:00Z',
        files: [],
      }
      reports.push(report)
      task = {
        ...(task ?? {}),
        progress: final ? 100 : body.progress,
        status: final ? 'done' : 'in_progress',
        status_title: final ? 'Выполнена' : 'В работе',
        closed_at: final ? '2026-11-01T10:00:00Z' : null,
      }
      messages.push({
        summary: step
          ? `Этап «${String(step.title)}» задачи закрыт — промежуточный отчёт`
          : final
            ? 'Задача выполнена — финальный отчёт'
            : 'Отчёт по задаче',
        created_at: '2026-11-01T10:00:00Z',
      })
      return route.fulfill({ json: detail() })
    }
    if (path.includes('/files') && method === 'POST') {
      const last = reports[reports.length - 1]
      if (last) {
        last.files.push({ id: 'file-1', original_name: 'смета.pdf', size_bytes: 2048 })
      }
      return route.fulfill({ json: { id: 'file-1', original_name: 'смета.pdf', size_bytes: 2048 } })
    }
    if (method === 'GET' && /\/api\/v1\/tasks\/[^/]+$/.test(path)) {
      return route.fulfill({ json: detail() })
    }
    return route.fulfill({ status: 404, json: { detail: `нет мока для ${method} ${path}` } })
  })

  const auditRow = (summary: string) => ({
    id: `ev-${summary.length}`,
    created_at: '2026-11-01T10:00:00Z',
    action: 'task.report_added',
    action_title: 'Отчёт по задаче',
    level: 'info',
    entity_kind: 'task',
    entity_id: 'task-1',
    entity_label: 'Подготовить матрицу цен',
    summary,
    actor_name: 'Ольга Коммерческая',
    actor_role_title: 'Коммерческий директор',
    year: null,
    month: null,
    read: false,
    link: '#/tasks/task-1',
  })
  await page.route('**/api/v1/messages/count', (route) => route.fulfill({ json: { unread: 1 } }))
  await page.route('**/api/v1/messages**', (route) =>
    route.fulfill({
      json: { rows: [auditRow(messages[messages.length - 1]?.summary ?? '')], unread: 1, total: 1 },
    }),
  )

  await page.goto('/')

  // 1. Коммерческий директор ставит задачу менеджеру.
  await page.getByRole('button', { name: 'Задачи', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Задачи' })).toBeVisible()
  await page.getByRole('button', { name: '＋ Новая задача' }).first().click()
  await page.getByLabel('Название').fill('Подготовить матрицу цен')
  await page.getByRole('button', { name: 'Поставить задачу' }).click()

  await expect(
    page.getByRole('heading', { level: 1, name: 'Подготовить матрицу цен' }),
  ).toBeVisible()
  // Задача принята автоматически: она сразу в работе.
  await expect(page.getByText('В работе', { exact: true })).toBeVisible()

  // 2. Постановщик переносит задачу: сроки меняются, этапы поедут следом.
  await page.getByRole('button', { name: 'Перенести' }).click()
  await page.getByLabel('Новое начало').fill('2026-12-01')
  await page.getByLabel('Новое окончание').fill('2026-12-10')
  await page.getByRole('button', { name: 'Сохранить перенос' }).click()
  await expect(page.getByText(/01\.12\.2026 — 10\.12\.2026/)).toBeVisible()

  // 3. Добавляем этап — даты подставляются по порядку.
  await page.getByPlaceholder('Название этапа').fill('Собрать цены')
  await page.getByRole('button', { name: 'Добавить этап' }).click()
  await expect(page.getByText('Собрать цены')).toBeVisible()

  // 4. Исполнитель закрывает этап промежуточным отчётом.
  session = SALES_USER
  await page.goto('/#/tasks/task-1')
  await page.reload()
  await expect(
    page.getByRole('heading', { level: 1, name: 'Подготовить матрицу цен' }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Отчёт по этапу' }).click()
  await page.getByLabel('Что сделано').fill('Цены собраны по всем клиентам')
  await page.getByRole('button', { name: 'Закрыть этап отчётом' }).click()
  await expect(page.getByText('Отчёт получен')).toBeVisible()
  await expect(page.getByText('Отчёт получен')).toHaveCount(1)

  // 5. Финальный отчёт с файлом закрывает задачу.
  await page.getByLabel('Вид отчёта').selectOption('final')
  await page.getByLabel('Что сделано').fill('Матрица согласована')
  await page.locator('input[type="file"]').setInputFiles({
    name: 'смета.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 test'),
  })
  await page.getByRole('button', { name: 'Закрыть задачу' }).click()
  await expect(page.getByText('Выполнена', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'смета.pdf' })).toBeVisible()

  // 6. Постановщик получил служебное сообщение об отчётах.
  session = COMMERCIAL_USER
  await page.goto('/#/tasks/task-1')
  await page.reload()
  await page.getByRole('button', { name: /Служебные сообщения/ }).click()
  await expect(page.getByText(/Задача выполнена — финальный отчёт/)).toBeVisible()
})
