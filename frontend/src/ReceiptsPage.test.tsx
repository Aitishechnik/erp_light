import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Batch, Counterparty, Product, SessionUser } from './api'
import { mockApi } from './apiMock'
import { ReceiptsPage } from './ReceiptsPage'

const SUPPLIERS: Counterparty[] = [
  {
    id: 's1',
    name: 'Импорт Трейд',
    inn: null,
    note: null,
    is_customer: false,
    is_local_supplier: false,
    is_import_supplier: true,
    source: '1c',
    is_active: true,
  },
]

const PRODUCTS: Product[] = [
  {
    id: 'p1',
    code: 'ТОВ1',
    name: 'Арахис в глазури',
    kind: 'finished',
    unit: 'кг',
    source: '1c',
    is_active: true,
  },
]

/** Сегодняшняя дата по локальному календарю — на неё открывается страница. */
const TODAY = (() => {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const date = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${date}`
})()

function batch(overrides: Partial<Batch> = {}): Batch {
  return {
    id: 'b1',
    batch_number: 'P-100',
    batch_type: 'purchase',
    batch_date: TODAY,
    currency: 'USD',
    supplier_id: 's1',
    supplier: 'Импорт Трейд',
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
      invoice_paid_currency: '600.00',
      invoice_paid_rub: '48000.00',
      invoice_remaining_currency: '400.00',
      invoice_rate: '84.000000',
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
      average_rate: '84.000000',
      final_cost_rub: '84000.00',
    },
    payments: [
      {
        id: 'pay1',
        payment_date: TODAY,
        amount_currency: '600.00',
        exchange_rate: '80',
        amount_rub: '48000.00',
        category: 'invoice',
        comment: null,
      },
    ],
    expenses: [],
    items: [
      {
        id: 'i1',
        product_code: 'ТОВ1',
        product_name: 'Арахис в глазури',
        product_kind: 'finished',
        unit: 'кг',
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
        item_total_rub: '84000.00',
        unit_cost: '8400.00',
        quantity_on_hand: '10.000',
      },
    ],
    ...overrides,
  }
}

function routes(extra: Record<string, { status?: number; body?: unknown }> = {}) {
  return {
    '/api/v1/rates/USD': {
      body: { code: 'USD', rate_date: '2026-10-14', rate: '90.5000', nominal: 1, source: 'cbr' },
    },
    '/api/v1/batches': { body: [batch()] },
    '/api/v1/counterparties': { body: SUPPLIERS },
    '/api/v1/products': { body: PRODUCTS },
    ...extra,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Адреса всех запросов, которые сделала страница. */
function fetchUrls(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) => String(call[0]))
}

function bodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) =>
    String((call[1] as { body?: unknown } | undefined)?.body ?? ''),
  )
}

/** Открыть партию из списка дня: карточка списка — сама кнопка. */
async function openBatch(user: ReturnType<typeof userEvent.setup>, id = 'b1') {
  await user.click(screen.getByTestId(`day-receipt-${id}`))
}

/** Раскрыть секцию карточки (Позиции, Платежи, Общие расходы, Таможня, Себестоимость). */
async function openSection(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole('button', { name }))
}

describe('ReceiptsPage', () => {
  it('показывает поступления в календаре и списком за день', async () => {
    mockApi(routes())
    render(<ReceiptsPage />)

    expect(await screen.findByTestId('receipts-calendar')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId(`day-dot-${TODAY}`)).toBeInTheDocument()
    })
    expect(screen.getByTestId('rail-day')).toHaveTextContent('1 поступление')
    const list = await screen.findByTestId('day-receipts')
    expect(list).toHaveTextContent('P-100')
    expect(list).toHaveTextContent('Импорт Трейд')
    expect(list).toHaveTextContent('84 000,00 ₽')
  })

  it('под календарём — только поступления выбранного дня', async () => {
    const user = userEvent.setup()
    // Второй день берём в том же месяце, что и сегодняшний.
    const otherDay = TODAY.endsWith('-10') ? `${TODAY.slice(0, 7)}-11` : `${TODAY.slice(0, 7)}-10`
    const second = batch({
      id: 'b2',
      batch_number: 'P-200',
      batch_date: otherDay,
      supplier: 'Второй поставщик',
    })
    mockApi(routes({ '/api/v1/batches': { body: [batch(), second] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('day-receipt-b1')
    expect(screen.getByTestId('day-receipts')).toHaveTextContent('P-100')
    expect(screen.getByTestId('day-receipts')).not.toHaveTextContent('P-200')

    await user.click(screen.getByTestId(`day-${otherDay}`))
    expect(await screen.findByTestId('day-receipt-b2')).toBeInTheDocument()
    // Поступления другого дня в список не попадают.
    expect(screen.queryByTestId('day-receipt-b1')).toBeNull()
    expect(screen.getByTestId('rail-day')).toHaveTextContent('1 поступление')
  })

  it('пересчитывает остаток по курсу, но не трогает зафиксированный платёж', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<ReceiptsPage />)

    await waitFor(() => {
      expect(screen.getByTestId(`day-${TODAY}`)).toBeInTheDocument()
    })
    await openBatch(user)

    // Цена единицы — во вкладке «Позиции».
    expect(screen.getByTestId('receipt-total')).toHaveTextContent('84 000,00')
    expect(screen.getByTestId('unit-cost-i0')).toHaveTextContent('8 400,00')

    // 600 $ закрыты по курсу платежа 80 (48 000 ₽), остаток 400 $ по 90 = 36 000 ₽.
    await user.click(screen.getByRole('button', { name: 'Платежи' }))
    expect(screen.getByTestId('receipt-paid')).toHaveTextContent('600,00')
    expect(screen.getByTestId('receipt-remaining')).toHaveTextContent('400,00')
    expect(screen.getByTestId('payment-rub-p0')).toHaveTextContent('48 000,00')

    const rate = screen.getByLabelText('Курс')
    await user.clear(rate)
    await user.type(rate, '100')

    // Переоценилась только незакрытая часть: 48 000 + 400 × 100 = 88 000 ₽.
    expect(screen.getByTestId('receipt-total')).toHaveTextContent('88 000,00')
    expect(screen.getByTestId('unit-cost-i0')).toHaveTextContent('8 800,00')
    expect(screen.getByTestId('payment-rub-p0')).toHaveTextContent('48 000,00')
  })

  it('заполняет поступление из 1С строками и сохраняет карточку', async () => {
    const user = userEvent.setup()
    mockApi({
      'PUT /api/v1/batches/d1': { body: batch({ id: 'd1', batch_number: 'ИТ-00000388' }) },
      ...routes({ '/api/v1/batches': { body: [draftBatch()] } }),
    })
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user, 'd1')
    // Номер пришёл из 1С — он не поле ввода.
    expect(screen.getByTestId('receipt-number')).toHaveTextContent('ИТ-00000388')

    await user.click(screen.getByRole('button', { name: 'Добавить строку' }))
    await user.type(screen.getByLabelText('Товар inew1'), 'ТОВ1')
    await user.type(screen.getByLabelText('Количество inew1'), '5')
    await user.type(screen.getByLabelText('Стоимость за ед. inew1'), '50')
    await user.clear(screen.getByLabelText('Курс'))
    await user.type(screen.getByLabelText('Курс'), '95')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(bodies().some((body) => body.includes('"product_code":"ТОВ1"'))).toBe(true)
    })
    const sent = bodies().find((body) => body.includes('"product_code":"ТОВ1"')) ?? ''
    expect(sent).toContain('"supplier_id":"s1"')
    expect(sent).toContain('"current_exchange_rate":"95"')
    expect(sent).toContain('"quantity":"5"')
    expect(sent).toContain('"unit_price_currency":"50"')
    expect(sent).toContain('"vat_percent":"22"')
    // План не выбран — уходит явный null, а не выдуманная ссылка.
    expect(sent).toContain('"purchase_plan_item_id":null')

    // Карточка не закрывается: после сохранения в ней уже сохранённая партия,
    // и «Растаможен» доступен сразу — таможня работает по сохранённым строкам.
    expect(screen.getByTestId('receipt-form')).toBeInTheDocument()
    expect(screen.getByTestId('receipt-saved')).toHaveTextContent('Поступление сохранено')
    expect(screen.getByTestId('customs-start')).toBeEnabled()
  })

  it('показывает ошибку сервера при сохранении', async () => {
    const user = userEvent.setup()
    mockApi({
      'PUT /api/v1/batches/b1': {
        status: 409,
        body: { detail: 'Поступление «P-100» уже существует' },
      },
      ...routes(),
    })
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    const price = screen.getByLabelText('Стоимость за ед. i0')
    await user.clear(price)
    await user.type(price, '111')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('уже существует')
  })

  it('связывает позицию поступления со строкой плана закупок', async () => {
    const user = userEvent.setup()
    const linked = batch()
    const [item] = linked.items
    if (!item) throw new Error('у партии нет строк')
    linked.items = [
      { ...item, purchase_plan_item_id: 'pl1', purchase_plan_label: '2026 · Китай · Импорт Трейд' },
    ]
    mockApi({
      'PUT /api/v1/batches/b1': { body: linked },
      ...routes({
        '/api/v1/purchase-plans': {
          body: [
            {
              status: 'approved',
              year: 2026,
              items: [
                {
                  id: 'pl1',
                  product_id: 'p1',
                  country_name: 'Китай',
                  supplier_name: 'Импорт Трейд',
                  sales_product_name: 'Смесь ореховая',
                },
              ],
            },
          ],
        },
      }),
    })
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    // Предлагается строка того же сырья; «не по плану» — вариант по умолчанию.
    const select = await screen.findByTestId('plan-select-i0')
    expect(select).toHaveValue('')
    await user.selectOptions(select, 'pl1')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(bodies().some((body) => body.includes('"purchase_plan_item_id":"pl1"'))).toBe(true)
    })
    // После сохранения на сервере позиция показывает подпись строки плана.
    expect(screen.getByTestId('plan-select-i0')).toHaveValue('pl1')
  })

  it('помечает в списке дня поступление, связанное с планом', async () => {
    const planned = batch()
    const [item] = planned.items
    if (!item) throw new Error('у партии нет строк')
    planned.items = [{ ...item, purchase_plan_item_id: 'pl1', purchase_plan_label: '2026 · Китай' }]
    mockApi(routes({ '/api/v1/batches': { body: [planned] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('day-receipt-b1')
    expect(screen.getByTestId('plan-badge')).toHaveTextContent('по плану')
  })

  it('подписывает курс остатка: ЦБ с датой или введён вручную', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    // Карточка пришла с курсом ЦБ — видно и курс, и его дату.
    expect(screen.getByTestId('receipt-cbr-rate')).toHaveTextContent(
      /актуальному курсу ЦБ на 08.10.2026 — 90 ₽ за 1 USD/,
    )

    const rate = screen.getByLabelText('Курс')
    await user.clear(rate)
    await user.type(rate, '100')
    expect(screen.getByTestId('receipt-cbr-rate')).toHaveTextContent(
      /введён вручную — 100 ₽ за 1 USD/,
    )
  })

  it('запрашивает курс ЦБ по кнопке', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        '/api/v1/batches': { body: [draftBatch()] },
        '/api/v1/rates/USD': {
          body: {
            code: 'USD',
            rate_date: '2026-10-08',
            rate: '91.2500',
            nominal: 1,
            source: 'cbr',
          },
        },
      }),
    )
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user, 'd1')
    await user.click(screen.getByRole('button', { name: 'Обновить курс ЦБ' }))

    await waitFor(() => {
      expect(screen.getByLabelText('Курс')).toHaveValue('91.2500')
    })
    expect(screen.getByText(/Актуальный курс ЦБ/)).toBeInTheDocument()
    // Дата поступления в запрос курса не попадает: курс остатка — всегда актуальный.
    const urls = fetchUrls()
    const rateCall = urls.find((url) => url.includes('/api/v1/rates/USD'))
    expect(rateCall).not.toContain('date=')
    // И в карточке видно, каким курсом и на какую дату оценён остаток.
    expect(screen.getByTestId('receipt-cbr-rate')).toHaveTextContent(
      /актуальному курсу ЦБ на 08.10.2026 — 91.25 ₽ за 1 USD/,
    )
  })
})

describe('ReceiptsPage — план и лимит', () => {
  const FUTURE = '2099-01-01'

  it('будущий платёж — план: в себестоимость не входит', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [draftBatch()] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user, 'd1')
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }))
    await user.type(screen.getByLabelText('Товар inew1'), 'ТОВ1')
    await user.type(screen.getByLabelText('Количество inew1'), '10')
    await user.type(screen.getByLabelText('Стоимость за ед. inew1'), '100')
    await user.clear(screen.getByLabelText('Курс'))
    await user.type(screen.getByLabelText('Курс'), '90')
    // НДС не про план — обнуляем, чтобы считался только инвойс.
    await user.clear(screen.getByLabelText('НДС inew1'))
    await user.type(screen.getByLabelText('НДС inew1'), '0')

    await user.click(screen.getByRole('button', { name: 'Платежи' }))
    await user.click(screen.getByRole('button', { name: 'Добавить валютный платёж' }))
    const pay = screen.getByTestId('receipt-payments').querySelector('tbody tr')
    expect(pay).not.toBeNull()
    await user.clear(screen.getByLabelText('Дата платежа pnew2'))
    await user.type(screen.getByLabelText('Дата платежа pnew2'), FUTURE)
    await user.type(screen.getByLabelText('Сумма платежа pnew2'), '400')
    await user.type(screen.getByLabelText('Курс платежа pnew2'), '80')

    // Платёж виден как план, но факт и себестоимость считаются без него.
    expect(screen.getByTestId('receipt-planned')).toHaveTextContent('400,00')
    expect(screen.getByTestId('receipt-paid')).toHaveTextContent('0,00')
    expect(screen.getByTestId('receipt-remaining')).toHaveTextContent('1 000,00')
    expect(screen.getByTestId('receipt-total')).toHaveTextContent('90 000,00 ₽')
  })

  it('платёж больше стоимости товаров — предупреждение и блокировка сохранения', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [draftBatch()] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user, 'd1')
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }))
    await user.type(screen.getByLabelText('Товар inew1'), 'ТОВ1')
    await user.type(screen.getByLabelText('Количество inew1'), '10')
    await user.type(screen.getByLabelText('Стоимость за ед. inew1'), '100')
    await user.clear(screen.getByLabelText('Курс'))
    await user.type(screen.getByLabelText('Курс'), '90')
    await user.click(screen.getByRole('button', { name: 'Платежи' }))
    await user.click(screen.getByRole('button', { name: 'Добавить валютный платёж' }))
    await user.type(screen.getByLabelText('Сумма платежа pnew2'), '1500')
    await user.type(screen.getByLabelText('Курс платежа pnew2'), '80')

    expect(screen.getByTestId('receipt-limit-error')).toHaveTextContent('больше')
    expect(screen.getByTestId('receipt-limit')).toHaveTextContent('0,00')
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
  })

  it('черновик из 1С помечен в календаре и сохраняется без позиций', async () => {
    const user = userEvent.setup()
    const draft = draftBatch({ comment: 'Фундук 145600 + сбор 32980' })
    mockApi({
      'PUT /api/v1/batches': { body: draft },
      ...routes({ '/api/v1/batches': { body: [draft] } }),
    })
    render(<ReceiptsPage />)

    const badge = await screen.findByTestId('draft-badge')
    expect(badge).toHaveTextContent('черновик')
    const row = screen.getByTestId('day-receipt-d1')
    // У черновика нет ни курса, ни себестоимости — вместо нулей прочерк.
    expect(row).toHaveTextContent('—')
    expect(row).not.toHaveTextContent('0,00')

    await user.click(screen.getByTestId('day-receipt-d1'))
    expect(screen.getByTestId('draft-hint')).toHaveTextContent('Черновик из выгрузки 1С')
    // Валюту берём из партии (импорт — USD), а курс у черновика пустой:
    // пока нет позиций, считать нечего.
    expect(screen.getByLabelText('Валюта')).toHaveValue('USD')
    expect(screen.getByLabelText('Курс')).toHaveValue('')
    // Выдуманного «курса 1» в итоге быть не должно.
    expect(screen.getByText(/курс не задан/)).toBeInTheDocument()
    // Сохраняем черновик, не добавляя ни одной позиции.
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      expect(screen.getByTestId('receipt-saved')).toBeInTheDocument()
    })
    // Карточка осталась открытой: после сохранения в ней то, что записал сервер.
    expect(screen.getByTestId('receipt-form')).toBeInTheDocument()
    const sent = bodies().find((body) => body.includes('ИТ-00000388')) ?? ''
    expect(sent).toContain('"items":[]')
    expect(sent).toContain('Фундук 145600')
  })

  it('в списке за день показывается средний курс партии', async () => {
    mockApi(
      routes({
        '/api/v1/batches': {
          body: [
            batch({
              finance: {
                ...batch().finance,
                exchange_rate: '85',
                average_rate: '100.500000',
              },
            }),
          ],
        },
      }),
    )
    render(<ReceiptsPage />)

    const list = await screen.findByTestId('day-receipts')
    expect(list).toHaveTextContent('100.5')
    expect(list).not.toHaveTextContent('85')
  })

  it('средний курс партии учитывает платежи по Risk', async () => {
    const user = userEvent.setup()
    // Инвойс 124 000 $ по 88 и Risk 60 000 $ по 91 → 88,978261.
    const withRisk = batch({
      items: [
        {
          id: 'i1',
          product_code: 'ТОВ1',
          product_name: 'Арахис в глазури',
          product_kind: 'finished',
          unit: 'кг',
          quantity: '20000.000',
          unit_price_currency: '6.2000',
          duty_percent: '5.0000',
          vat_percent: '22.0000',
          risk_unit_currency: '3.0000',
          duty_fixed_rub: null,
          vat_fixed_rub: null,
          purchase_plan_item_id: null,
          purchase_plan_label: null,
          invoice_currency: '124000.00',
          risk_currency: '60000.00',
          duty_rub: '0.00',
          vat_rub: '0.00',
          risk_rub: '0.00',
          expenses_rub: '0.00',
          item_total_rub: '0.00',
          unit_cost: '0.00',
          quantity_on_hand: '20000.000',
        },
      ],
      payments: [
        {
          id: 'pay1',
          payment_date: TODAY,
          amount_currency: '124000.00',
          exchange_rate: '88',
          amount_rub: '10912000.00',
          category: 'invoice',
          comment: null,
        },
        {
          id: 'pay2',
          payment_date: TODAY,
          amount_currency: '60000.00',
          exchange_rate: '91',
          amount_rub: '5460000.00',
          category: 'risk',
          comment: null,
        },
      ],
      finance: {
        ...batch().finance,
        invoice_total_currency: '124000.00',
        risk_total_currency: '60000.00',
        invoice_paid_currency: '124000.00',
        invoice_paid_rub: '10912000.00',
        invoice_remaining_currency: '0.00',
        invoice_rate: '88.000000',
        risk_paid_currency: '60000.00',
        risk_paid_rub: '5460000.00',
        risk_remaining_currency: '0.00',
        risk_rate: '91.000000',
        average_rate: '88.978261',
      },
    })
    mockApi(routes({ '/api/v1/batches': { body: [withRisk] } }))
    render(<ReceiptsPage />)

    const list = await screen.findByTestId('day-receipts')
    expect(list).toHaveTextContent('88.978261')

    await user.click(within(list).getByTestId('day-receipt-b1'))
    // Средний курс — 88,9783; рядом видно, из чего он собран.
    expect(screen.getByTestId('receipt-average-rate')).toHaveTextContent('88.9783')
    await openSection(user, 'Себестоимость')
    expect(screen.getByTestId('receipt-effective')).toHaveTextContent('88')
    expect(screen.getByTestId('receipt-risk-rate')).toHaveTextContent('91')
  })
})

describe('ReceiptsPage — пошлина, НДС, Risk и общие расходы', () => {
  it('считает цену за единицу по новой формуле', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [draftBatch()] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user, 'd1')
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }))
    await user.clear(screen.getByLabelText('Курс'))
    await user.type(screen.getByLabelText('Курс'), '90')
    await user.type(screen.getByLabelText('Товар inew1'), 'ТОВ1')
    await user.type(screen.getByLabelText('Стоимость за ед. inew1'), '10')
    await user.type(screen.getByLabelText('Количество inew1'), '100')
    await user.type(screen.getByLabelText('Пошлина inew1'), '5')
    await user.type(screen.getByLabelText('Risk inew1'), '1')

    // (10 + 0,5 + 2,31) × 90 + 1 × 90 = 1 242,90 ₽ за единицу, 124 290 ₽ за строку.
    expect(screen.getByTestId('unit-cost-inew1')).toHaveTextContent('1 242,90')
    expect(screen.getByTestId('item-total-inew1')).toHaveTextContent('124 290,00')
    await openSection(user, 'Себестоимость')
    expect(screen.getByTestId('receipt-duty')).toHaveTextContent('4 500,00')
    expect(screen.getByTestId('receipt-vat')).toHaveTextContent('20 790,00')
    expect(screen.getByTestId('receipt-risk-total')).toHaveTextContent('100,00')
  })

  it('добавляет общий расход в usd и пересчитывает его по курсу ЦБ', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [draftBatch({ currency: 'RUB' })] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user, 'd1')
    await user.clear(screen.getByLabelText('Курс'))
    await user.type(screen.getByLabelText('Курс'), '1')
    await user.click(screen.getByRole('button', { name: 'Общие расходы' }))
    await user.click(screen.getByRole('button', { name: 'Добавить расход' }))

    await user.type(screen.getByLabelText('Расход enew1'), 'Доставка')
    await user.selectOptions(screen.getByLabelText('Валюта расхода enew1'), 'USD')
    await user.type(screen.getByLabelText('Сумма расхода enew1'), '100')

    // 100 $ по курсу ЦБ 90,5 = 9 050 ₽.
    expect(screen.getByTestId('expense-rub-enew1')).toHaveTextContent('9 050,00')
    expect(screen.getByTestId('receipt-expenses-rub')).toHaveTextContent('9 050,00')

    // Строка 10 шт × 100 ₽ (партия в рублях, курс 1) + НДС 22 % + расход 9 050 ₽.
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }))
    await user.type(screen.getByLabelText('Товар inew2'), 'ТОВ1')
    await user.type(screen.getByLabelText('Стоимость за ед. inew2'), '100')
    await user.type(screen.getByLabelText('Количество inew2'), '10')
    await openSection(user, 'Себестоимость')
    expect(screen.getByTestId('receipt-vat')).toHaveTextContent('220,00')
    expect(screen.getByTestId('receipt-total')).toHaveTextContent('10 270,00')
  })

  it('категория Risk предлагается, только когда Risk есть в партии', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    await user.click(screen.getByRole('button', { name: 'Платежи' }))

    const category = screen.getByLabelText('Категория платежа p0')
    expect(within(category).getByRole('option', { name: 'Инвойс' })).toBeInTheDocument()
    expect(within(category).queryByRole('option', { name: 'Risk' })).toBeNull()

    // Появился Risk в строке — появился и выбор категории платежа.
    await user.clear(screen.getByLabelText('Risk i0'))
    await user.type(screen.getByLabelText('Risk i0'), '1')
    expect(within(category).getByRole('option', { name: 'Risk' })).toBeInTheDocument()
  })

  it('в секции «Себестоимость» видно, из чего сложилась сумма', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    await user.click(screen.getByRole('button', { name: 'Себестоимость' }))

    const panel = screen.getByTestId('panel-cost')
    expect(screen.getByTestId('cost-total')).toHaveTextContent('84 000,00 ₽')
    // Единственное слагаемое — инвойс: 1 000 $ по курсу 84 = 84 000 ₽.
    expect(panel).toHaveTextContent('1 000,00 USD × курс 84')
    expect(panel).toHaveTextContent('100 %')
    expect(panel).toHaveTextContent('84 000,00 ₽')
  })
})

const IMPORT_USER: SessionUser = {
  id: 'u1',
  login: 'import',
  full_name: 'Импортёр',
  role: 'import_manager',
  role_title: 'Менеджер по закупкам (импорт)',
}

function draftBatch(overrides: Partial<Batch> = {}): Batch {
  return batch({
    id: 'd1',
    batch_number: 'ИТ-00000388',
    source: '1c',
    currency: 'USD',
    items: [],
    payments: [],
    finance: {
      ...batch().finance,
      invoice_total_currency: '0.00',
      invoice_paid_currency: '0.00',
      invoice_paid_rub: '0.00',
      invoice_remaining_currency: '0.00',
      invoice_rate: '0.000000',
      average_rate: '0.000000',
      final_cost_rub: '0.00',
    },
    ...overrides,
  })
}

/** Файл без содержимого: важно только имя, его и отправляет форма. */
function file(name = 'Партия.xlsx'): File {
  return new File(['xlsx'], name, {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

describe('ReceiptsPage — позиции из файла «Партия»', () => {
  it('менеджер по закупкам грузит позиции и видит итог', async () => {
    const user = userEvent.setup()
    const loaded = draftBatch({
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
          purchase_plan_item_id: null,
          purchase_plan_label: null,
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
    })
    mockApi({
      '/api/v1/batches/d1/import-items': {
        body: {
          batch: loaded,
          report: {
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
            message: 'поступление ИТ-00000388: загружено строк 1',
            created_at: '2026-10-14T10:00:00Z',
          },
        },
      },
      ...routes({ '/api/v1/batches': { body: [draftBatch()] } }),
    })
    render(<ReceiptsPage user={IMPORT_USER} />)

    await screen.findByTestId('receipts-calendar')
    await user.click(screen.getByTestId('day-receipt-d1'))

    await user.upload(screen.getByLabelText('Файл партии из 1С'), file())
    await user.click(screen.getByRole('button', { name: 'Загрузить позиции из 1С' }))

    await waitFor(() => {
      expect(screen.getByTestId('batch-items-hint')).toHaveTextContent('загружено строк: 1')
    })
    // Строка из файла появилась в карточке: в поле — название, код — под ним.
    expect(screen.getByLabelText('Товар i0')).toHaveValue('Грецкий орех сушеный, вес')
    expect(screen.getByTestId('product-code-i0')).toHaveTextContent('код ТОВ395561')
    expect(screen.getByLabelText('Количество i0')).toHaveValue('20000')
    // Цены файл не несёт — поле пустое, НДС стоит по умолчанию 22 %.
    expect(screen.getByLabelText('Стоимость за ед. i0')).toHaveValue('')
    expect(screen.getByLabelText('НДС i0')).toHaveValue('22')
  })

  it('колонка называется «Товар», название в поле и код под ним', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [batch()] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await user.click(screen.getByTestId('day-receipt-b1'))

    const items = screen.getByTestId('receipt-items')
    expect(within(items).getByRole('columnheader', { name: 'Товар' })).toBeInTheDocument()
    expect(within(items).queryByRole('columnheader', { name: 'Товар (код)' })).toBeNull()

    // В строке партии — название товара, код из 1С показан под полем.
    expect(screen.getByLabelText('Товар i0')).toHaveValue('Арахис в глазури')
    expect(screen.getByTestId('product-code-i0')).toHaveTextContent('код ТОВ1')

    // Товара нет в справочнике — предупреждаем, что строка не сохранится.
    await user.clear(screen.getByLabelText('Товар i0'))
    await user.type(screen.getByLabelText('Товар i0'), 'Неизвестный товар')
    expect(screen.getByTestId('product-missing-i0')).toHaveTextContent('нет в справочнике')

    // Снова выбираем товар по названию — код возвращается.
    await user.clear(screen.getByLabelText('Товар i0'))
    await user.type(screen.getByLabelText('Товар i0'), 'Арахис в глазури')
    expect(screen.getByTestId('product-code-i0')).toHaveTextContent('код ТОВ1')
  })

  it('менеджер по продажам видит поступление только для чтения', async () => {
    const user = userEvent.setup()
    const sales: SessionUser = { ...IMPORT_USER, role: 'sales_manager' }
    mockApi(routes())
    render(<ReceiptsPage user={sales} />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)

    expect(screen.getByTestId('receipt-form')).toBeInTheDocument()
    // Карточка открыта, но править и сохранять нечего: всё выключено, кнопок нет.
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Удалить' })).toBeNull()
    expect(screen.queryByTestId('customs-start')).toBeNull()
    expect(screen.getByTestId('item-title-i0')).toHaveTextContent('Арахис в глазури')
    expect(screen.queryByLabelText('Товар i0')).toBeNull()
    expect(screen.getByRole('button', { name: 'Добавить строку' })).toBeDisabled()
    expect(screen.queryByTestId('batch-items-import')).toBeNull()
  })

  it('показывает причину отказа сервера', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/batches/d1/import-items': {
        status: 400,
        body: { detail: 'Файл не загружен. строка 2: номенклатура «Неизвестный» не найдена' },
      },
      ...routes({ '/api/v1/batches': { body: [draftBatch()] } }),
    })
    render(<ReceiptsPage user={IMPORT_USER} />)

    await screen.findByTestId('receipts-calendar')
    await user.click(screen.getByTestId('day-receipt-d1'))

    await user.upload(screen.getByLabelText('Файл партии из 1С'), file())
    await user.click(screen.getByRole('button', { name: 'Загрузить позиции из 1С' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('не найдена')
  })
})

/** Партия с пошлиной и НДС в строках — на ней видно фиксацию таможни. */
function taxedBatch(overrides: Partial<Batch> = {}): Batch {
  const [item] = batch().items
  if (!item) throw new Error('у партии нет строк')
  return batch({
    items: [{ ...item, duty_percent: '5.0000', vat_percent: '22.0000' }],
    ...overrides,
  })
}

/** Растаможенная партия: проценты заменены фиксом, курс таможни 80. */
function clearedBatch(overrides: Partial<Batch> = {}): Batch {
  const base = taxedBatch()
  const [item] = base.items
  if (!item) throw new Error('у партии нет строк')
  return taxedBatch({
    customs_date: '2026-10-20',
    customs_rate: '80',
    items: [{ ...item, duty_fixed_rub: '4100.00', vat_fixed_rub: '18480.00' }],
    finance: { ...base.finance, duty_rub: '4100.00', vat_rub: '18480.00' },
    ...overrides,
  })
}

const DIRECTOR_USER: SessionUser = {
  id: 'u2',
  login: 'purchase',
  full_name: 'Директор по закупкам',
  role: 'purchase_director',
  role_title: 'Директор по закупкам',
}

/** Тело запроса по фрагменту URL: мок пишет все вызовы fetch. */
function callInit(fragment: string): { method?: string; body?: string } {
  const mock = fetch as unknown as {
    mock: { calls: [RequestInfo | URL, { method?: string; body?: unknown }?][] }
  }
  const call = mock.mock.calls.find(([input]) => String(input).includes(fragment))
  return { method: call?.[1]?.method, body: String(call?.[1]?.body ?? '') }
}

describe('ReceiptsPage — растаможка партии', () => {
  it('перед фиксацией показывает курс и суммы и шлёт правку', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/batches/b1/customs': { body: clearedBatch() },
      ...routes({ '/api/v1/batches': { body: [taxedBatch()] } }),
    })
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    await user.click(screen.getByTestId('customs-start'))

    // Курс подставляется из ЦБ на дату растаможки (в моке — 90,5).
    await waitFor(() => {
      expect(screen.getByLabelText('Курс растаможки')).toHaveValue('90.5')
    })
    // Пошлина 5 % × 10 шт × 90,5 = 4 525 ₽, НДС 23,1 $ × 10 × 90,5 = 20 905,50 ₽.
    expect(screen.getByTestId('customs-duty-total')).toHaveTextContent('4 525,00')
    expect(screen.getByTestId('customs-vat-total')).toHaveTextContent('20 905,50')

    // Курс правят руками — суммы пересчитываются по строкам.
    await user.clear(screen.getByLabelText('Курс растаможки'))
    await user.type(screen.getByLabelText('Курс растаможки'), '80')
    expect(screen.getByTestId('customs-duty-total')).toHaveTextContent('4 000,00')
    expect(screen.getByTestId('customs-vat-total')).toHaveTextContent('18 480,00')

    // И сам итог тоже правят: в таможне бывает своя сумма.
    await user.clear(screen.getByLabelText('Пошлина партии, ₽'))
    await user.type(screen.getByLabelText('Пошлина партии, ₽'), '4100')
    expect(screen.getByTestId('customs-sum')).toHaveTextContent('22 580,00')

    await user.click(screen.getByTestId('customs-confirm'))

    await waitFor(() => {
      expect(screen.getByTestId('customs-badge')).toBeInTheDocument()
    })
    const sent = JSON.parse(callInit('/customs').body ?? '{}') as Record<string, string>
    expect(callInit('/customs').method).toBe('POST')
    expect(sent.rate).toBe('80')
    expect(sent.duty_rub).toBe('4100')
    expect(sent.vat_rub).toBe('18480')

    // Карточка перешла в режим фикса: проценты заменены рублями.
    expect(screen.getByTestId('item-duty-i0')).toHaveTextContent('4 100,00')
    expect(screen.getByTestId('item-vat-i0')).toHaveTextContent('18 480,00')
    expect(screen.queryByLabelText('Пошлина i0')).toBeNull()
    expect(screen.queryByLabelText('НДС i0')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Добавить строку' })).toBeNull()
    // Строк в таблице не убрать: «Убрать» остался только у платежей и расходов.
    expect(
      within(screen.getByTestId('receipt-items')).queryByRole('button', { name: 'Убрать' }),
    ).toBeNull()
    // Валюта — база фикса: в растаможенной партии поле заблокировано.
    expect(screen.getByLabelText('Валюта')).toBeDisabled()

    // Живой расчёт берёт фикс: 1000 $ × 84 + 4 100 + 18 480 = 106 580 ₽.
    expect(screen.getByTestId('receipt-total')).toHaveTextContent('106 580,00')
    expect(screen.getByTestId('unit-cost-i0')).toHaveTextContent('10 658,00')
  })

  it('отменить растаможку может только директор по закупкам', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/batches/b1/customs': { body: taxedBatch() },
      ...routes({ '/api/v1/batches': { body: [clearedBatch()] } }),
    })
    render(<ReceiptsPage user={IMPORT_USER} />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    expect(screen.getByTestId('customs-badge')).toBeInTheDocument()
    // Менеджер по закупкам видит статус, но не отменяет фиксацию.
    expect(screen.queryByTestId('customs-cancel')).toBeNull()
    expect(screen.queryByTestId('customs-start')).toBeNull()
  })

  it('директор снимает фиксацию — проценты возвращаются в строки', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/batches/b1/customs': { body: taxedBatch() },
      ...routes({ '/api/v1/batches': { body: [clearedBatch()] } }),
    })
    render(<ReceiptsPage user={DIRECTOR_USER} />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    await user.click(screen.getByTestId('customs-cancel'))

    await waitFor(() => {
      expect(screen.queryByTestId('customs-badge')).toBeNull()
    })
    expect(callInit('/customs').method).toBe('DELETE')
    expect(screen.getByLabelText('Пошлина i0')).toHaveValue('5')
    expect(screen.getByLabelText('НДС i0')).toHaveValue('22')
  })

  it('черновик без позиций растаможить нельзя', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [draftBatch()] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user, 'd1')

    expect(screen.getByTestId('customs-start')).toBeDisabled()
  })

  it('курс на дату растаможки подтягивается сам при смене даты', async () => {
    const user = userEvent.setup()
    mockApi({
      // Конкретный маршрут — раньше общего: мок берёт первое совпадение.
      '/api/v1/rates/USD?date=2026-10-08': {
        body: { code: 'USD', rate_date: '2026-10-08', rate: '84.9048', nominal: 1, source: 'cbr' },
      },
      ...routes({ '/api/v1/batches': { body: [taxedBatch()] } }),
    })
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    await user.click(screen.getByTestId('customs-start'))
    // По умолчанию дата растаможки — сегодня, курс ЦБ на неё (в моке 90,5).
    await waitFor(() => {
      expect(screen.getByLabelText('Курс растаможки')).toHaveValue('90.5')
    })

    fireEvent.change(screen.getByLabelText('Дата растаможки'), {
      target: { value: '2026-10-08' },
    })
    // Курс подтянулся сам, итоги пересчитаны по нему: 50 $ × 84,9048 и 231 $ × 84,9048.
    await waitFor(() => {
      expect(screen.getByLabelText('Курс растаможки')).toHaveValue('84.9048')
    })
    expect(screen.getByTestId('customs-duty-total')).toHaveTextContent('4 245,24')
    expect(screen.getByTestId('customs-vat-total')).toHaveTextContent('19 613,01')
  })

  it('растаможка и её отмена ждут сохранения карточки', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [clearedBatch()] } }))
    render(<ReceiptsPage user={DIRECTOR_USER} />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    expect(screen.getByTestId('customs-cancel')).toBeEnabled()
    expect(screen.queryByTestId('customs-dirty')).toBeNull()

    // Правка, которой нет на сервере: суммы таможни считались бы не по этим данным.
    fireEvent.change(screen.getByLabelText('Дата поступления'), {
      target: { value: '2026-10-05' },
    })
    expect(screen.getByTestId('customs-dirty')).toHaveTextContent('несохранённые изменения')
    expect(screen.getByTestId('customs-cancel')).toBeDisabled()

    // Вернули как было — фиксация снова доступна.
    fireEvent.change(screen.getByLabelText('Дата поступления'), { target: { value: TODAY } })
    expect(screen.queryByTestId('customs-dirty')).toBeNull()
    expect(screen.getByTestId('customs-cancel')).toBeEnabled()
  })

  it('в списке за день и календаре видно, что партия растаможена', async () => {
    mockApi(routes({ '/api/v1/batches': { body: [clearedBatch()] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    expect(screen.getByTestId('clearance-badge')).toBeInTheDocument()
    expect(screen.getByTestId(`day-dot-${TODAY}`)).toHaveClass('cleared')
  })

  it('пока открыто окно растаможки, строки партии не правятся', async () => {
    const user = userEvent.setup()
    mockApi(routes({ '/api/v1/batches': { body: [taxedBatch()] } }))
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)
    // До окна строки правятся: количество, цена и проценты доступны.
    expect(screen.getByLabelText('Количество i0')).toBeEnabled()
    expect(screen.getByLabelText('Пошлина i0')).toBeEnabled()

    await user.click(screen.getByTestId('customs-start'))
    await waitFor(() => {
      expect(screen.getByLabelText('Курс растаможки')).toHaveValue('90.5')
    })
    // Окно открыто — свойства строк заперты: суммы в окне уже посчитаны.
    expect(screen.getByLabelText('Товар i0')).toBeDisabled()
    expect(screen.getByLabelText('Количество i0')).toBeDisabled()
    expect(screen.getByLabelText('Стоимость за ед. i0')).toBeDisabled()
    expect(screen.getByLabelText('Пошлина i0')).toBeDisabled()
    expect(screen.getByLabelText('НДС i0')).toBeDisabled()
    expect(screen.getByLabelText('Risk i0')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Добавить строку' })).toBeDisabled()
    expect(screen.getByLabelText('Валюта')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Удалить' })).toBeDisabled()

    // Окно закрыли — карточка снова доступна.
    await user.click(
      within(screen.getByTestId('customs-box')).getByRole('button', { name: 'Отмена' }),
    )
    expect(screen.getByLabelText('Количество i0')).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled()
  })

  it('после сохранения карточка остаётся открытой — можно сразу растамаживать', async () => {
    const user = userEvent.setup()
    mockApi({
      'PUT /api/v1/batches': { body: taxedBatch() },
      ...routes({ '/api/v1/batches': { body: [taxedBatch()] } }),
    })
    render(<ReceiptsPage />)

    await screen.findByTestId('receipts-calendar')
    await openBatch(user)

    // Поменяли процент в строке — растаможка ждёт сохранения.
    await user.clear(screen.getByLabelText('Пошлина i0'))
    await user.type(screen.getByLabelText('Пошлина i0'), '7')
    expect(screen.getByTestId('customs-start')).toBeDisabled()
    expect(screen.getByTestId('customs-dirty')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => {
      expect(screen.getByTestId('receipt-saved')).toHaveTextContent('Поступление сохранено')
    })
    // Карточка не закрылась, правок нет, растаможка снова доступна.
    expect(screen.getByTestId('receipt-form')).toBeInTheDocument()
    expect(screen.queryByTestId('customs-dirty')).toBeNull()
    expect(screen.getByTestId('customs-start')).toBeEnabled()

    // Пометка «сохранено» исчезает, как только карточку снова поправили.
    await user.clear(screen.getByLabelText('Пошлина i0'))
    await user.type(screen.getByLabelText('Пошлина i0'), '8')
    expect(screen.queryByTestId('receipt-saved')).toBeNull()
  })
})
