import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  applyCustoms,
  type Batch,
  type BatchIn,
  type Counterparty,
  cancelCustoms,
  createBatch,
  deleteBatch,
  type ExpenseCurrency,
  errorMessage,
  fetchBatches,
  fetchCounterparties,
  fetchProducts,
  fetchRate,
  formatMoney,
  type PaymentCategory,
  type Product,
  type Role,
  type SessionUser,
  updateBatch,
  uploadBatchItems,
} from './api'

/** Позиции из файла «Партия» грузят те же роли, что правят поступления. */
const ITEM_IMPORT_ROLES: Role[] = ['purchase_director', 'import_manager']

/** Подпись валюты партии: для рубля — знак, для остальных — код. */
function currencyLabel(currency: string): string {
  return currency.trim().toUpperCase() === 'RUB' ? '₽' : currency.trim().toUpperCase()
}

type ItemDraft = {
  key: string
  /** Что видно в поле «Товар»: название позиции. */
  title: string
  /** Код из 1С — то, что уходит на сервер; пустой, если название не нашлось. */
  code: string
  quantity: string
  /** Стоимость за единицу в валюте партии. */
  price: string
  /** Пошлина, % от валютной стоимости единицы. */
  duty: string
  /** НДС, % от стоимости единицы с пошлиной. */
  vat: string
  /** Risk за единицу в валюте партии. */
  risk: string
  /** Пошлина строки, ₽: фикс после растаможки (вместо процента). */
  dutyRub: string
  /** НДС строки, ₽: фикс после растаможки (вместо процента). */
  vatRub: string
}

/** Ключ сравнения: регистр, «ё» и лишние пробелы не важны. */
function productKey(value: string): string {
  return value.split(/\s+/).join(' ').trim().toLowerCase().replace(/ё/g, 'е')
}

/** Товар по введённому тексту: сначала по названию, потом по коду (как привыкли раньше). */
function findProduct(products: Product[], value: string): Product | undefined {
  const text = value.trim()
  if (!text) return undefined
  const key = productKey(text)
  return (
    products.find((row) => productKey(row.name) === key) ??
    products.find((row) => row.code.toLowerCase() === text.toLowerCase())
  )
}

type ExpenseDraft = {
  key: string
  description: string
  /** Валюта расхода: только руб. или usd. */
  currency: ExpenseCurrency
  amount: string
}

type PaymentDraft = {
  key: string
  date: string
  amount: string
  rate: string
  /** Какой валютный долг закрывает платёж: инвойс или Risk. */
  category: PaymentCategory
  comment: string
}

type Draft = {
  id: string | null
  number: string
  date: string
  currency: string
  supplierId: string
  supplierText: string
  rate: string
  comment: string
  items: ItemDraft[]
  payments: PaymentDraft[]
  expenses: ExpenseDraft[]
  /** Черновик из выгрузки 1С: позиций ещё нет, сохранять без них можно. */
  isDraft: boolean
  /** Дата растаможки; пусто — партия не растаможена. */
  customsDate: string
  /** Курс, по которому зафиксированы пошлина и НДС. */
  customsRate: string
  /**
   * Дата курса ЦБ, которым оценён незакрытый остаток (пусто — курс введён вручную).
   * Курс остатка — всегда актуальный: дата поступления на него не влияет.
   */
  rateDate: string
}

/** Вкладки карточки партии: детали не мешаются на одном экране. */
type TabId = 'items' | 'expenses' | 'payments' | 'customs' | 'cost'

/** Черновик окна подтверждения растаможки: дата, курс и правимые итоги. */
type CustomsDraft = {
  date: string
  rate: string
  /** Пошлина партии, ₽ — считается по строкам, но правится вручную. */
  duty: string
  /** НДС партии, ₽ — так же. */
  vat: string
  hint: string | null
}

const WEEKDAYS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

/** Локальная дата в формате ГГГГ-ММ-ДД (toISOString даёт UTC и сдвигает день). */
function iso(day: Date): string {
  const month = String(day.getMonth() + 1).padStart(2, '0')
  const date = String(day.getDate()).padStart(2, '0')
  return `${day.getFullYear()}-${month}-${date}`
}

function monthStart(month: string): Date {
  return new Date(`${month}-01T00:00:00`)
}

function monthDays(month: string): { date: string; inMonth: boolean }[] {
  const first = monthStart(month)
  const offset = (first.getDay() + 6) % 7 // понедельник — первый день недели
  const days: { date: string; inMonth: boolean }[] = []
  const start = new Date(first)
  start.setDate(first.getDate() - offset)
  for (let index = 0; index < 42; index += 1) {
    const day = new Date(start)
    day.setDate(start.getDate() + index)
    days.push({ date: iso(day), inMonth: iso(day).startsWith(month) })
  }
  let lastInMonth = 0
  days.forEach((cell, index) => {
    if (cell.inMonth) lastInMonth = index
  })
  return days.slice(0, lastInMonth + 1)
}

/** «2026-10-16» → «16.10.2026»: дата курса ЦБ в подписи карточки. */
function ruDate(value: string | null | undefined): string {
  if (!value) return '—'
  const [year, month, day] = value.split('-')
  return year && month && day ? `${day}.${month}.${year}` : value
}

/** Курс показываем с четырьмя знаками: 100.4619 вместо 100.46191999999999. */
function formatRate(value: number): string {
  return trim(value.toFixed(4))
}

/** «5000.00» → «5000», «90.000000» → «90»: в полях ввода лишние нули не нужны. */
function trim(value: string): string {
  return value.includes('.') ? value.replace(/\.?0+$/, '') : value
}

function number(value: string): number {
  const parsed = Number(value.replace(',', '.'))
  return Number.isFinite(parsed) ? parsed : 0
}

/** Итог по одной категории валютного долга: инвойс или Risk. */
type CategoryTotals = {
  total: number
  paidCurrency: number
  paidRub: number
  remaining: number
  rate: number
  plannedCurrency: number
  plannedRub: number
}

/**
 * Живой расчёт себестоимости — та же формула, что на сервере:
 *   пошлина$ = цена × %пошлины;  НДС$ = (цена + пошлина$) × %НДС
 *   курс кат. = (Σ платёж × курс платежа + остаток × курс ЦБ) ÷ сумма категории$
 *   цена за ед.₽ = (цена + пошлина$ + НДС$) × курс инвойса + Risk$ × курс Risk
 *                  + доля общих расходов на единицу
 * Общие расходы делятся по полной валютной стоимости строки (инвойс + Risk).
 */
type LiveCost = {
  invoice: CategoryTotals
  risk: CategoryTotals
  cbrRate: number
  /** Средний курс партии по инвойсу и Risk — как в списке поступлений. */
  averageRate: number
  expensesRub: number
  dutyRub: number
  vatRub: number
  unit: Record<string, number>
  itemTotal: Record<string, number>
  total: number
  limitInvoiceExceeded: boolean
  limitRiskExceeded: boolean
}

/** Округление денег до копейки (HALF_UP, как на сервере). */
function round2(value: number): number {
  return Math.round(value * 100) / 100
}

/** Округление курса до шести знаков — так он хранится на сервере. */
function round6(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000
}

/** Сумма одного общего расхода в рублях: рубли как есть, usd — по курсу ЦБ на сегодня. */
function expenseRub(row: ExpenseDraft, usdRate: number | null): number {
  const amount = number(row.amount)
  if (row.currency === 'USD') return amount * (usdRate ?? 0)
  return amount
}

function categoryTotals(
  total: number,
  rows: { amount: number; rate: number; category: PaymentCategory; date: string }[],
  category: PaymentCategory,
  today: string,
  cbrRate: number,
): CategoryTotals {
  let paidCurrency = 0
  let paidRub = 0
  let plannedCurrency = 0
  let plannedRub = 0
  for (const row of rows) {
    if (row.category !== category) continue
    const rub = row.amount * row.rate
    // Платёж с будущей датой — план: показываем, но в расчёт не берём.
    if (row.date && row.date <= today) {
      paidCurrency += row.amount
      paidRub += rub
    } else {
      plannedCurrency += row.amount
      plannedRub += rub
    }
  }
  const remaining = Math.max(0, total - paidCurrency)
  // Курс на сервере хранится с шестью знаками — повторяем то же округление,
  // иначе живой расчёт разойдётся с сохранённым на копейку.
  const exact = total > 0 ? (paidRub + remaining * cbrRate) / total : 0
  const rate = round6(exact)
  return { total, paidCurrency, paidRub, remaining, rate, plannedCurrency, plannedRub }
}

function liveCost(draft: Draft, usdRate: number | null): LiveCost {
  const today = iso(new Date())
  const cbrRate = draft.currency.trim().toUpperCase() === 'RUB' ? 1 : number(draft.rate) || 1

  const rows = draft.items.map((item) => {
    const quantity = number(item.quantity)
    const price = number(item.price)
    const riskUnit = number(item.risk)
    return {
      key: item.key,
      quantity,
      price,
      riskUnit,
      invoice: price * quantity,
      risk: riskUnit * quantity,
    }
  })
  const invoiceTotal = rows.reduce((sum, row) => sum + row.invoice, 0)
  const riskTotal = rows.reduce((sum, row) => sum + row.risk, 0)

  const payments = draft.payments.map((row) => ({
    amount: number(row.amount),
    rate: number(row.rate),
    category: row.category,
    date: row.date,
  }))
  const invoice = categoryTotals(invoiceTotal, payments, 'invoice', today, cbrRate)
  const risk = categoryTotals(riskTotal, payments, 'risk', today, cbrRate)

  const expensesRub = draft.expenses.reduce((sum, row) => sum + expenseRub(row, usdRate), 0)

  const unit: Record<string, number> = {}
  const itemTotal: Record<string, number> = {}
  let dutyRub = 0
  let vatRub = 0
  const fullTotal = invoiceTotal + riskTotal
  // Растаможенная партия: пошлина и НДС — фикс в рублях, курс их не трогает.
  const cleared = draft.customsDate !== ''
  for (const item of draft.items) {
    const row = rows.find((candidate) => candidate.key === item.key)
    const quantity = row?.quantity ?? 0
    const price = row?.price ?? 0
    const riskUnit = row?.riskUnit ?? 0
    const share = fullTotal > 0 ? ((row?.invoice ?? 0) + (row?.risk ?? 0)) / fullTotal : 0
    // Сервер округляет долю расходов и сумму строки до копейки — повторяем,
    // чтобы живой расчёт совпадал с сохранённым.
    const expensesItem = round2(expensesRub * share)
    let rowTotal: number
    if (cleared) {
      // Как на сервере: товар по курсу инвойса, Risk по своему, таможня — фиксом.
      const dutyItem = number(item.dutyRub)
      const vatItem = number(item.vatRub)
      const goodsRub = round2(round2(price * quantity) * invoice.rate)
      const riskRub = round2(round2(riskUnit * quantity) * risk.rate)
      rowTotal = round2(goodsRub + dutyItem + vatItem + riskRub + expensesItem)
      dutyRub += dutyItem
      vatRub += vatItem
    } else {
      const dutyUnit = (price * number(item.duty)) / 100
      const vatUnit = ((price + dutyUnit) * number(item.vat)) / 100
      const baseUnit = (price + dutyUnit + vatUnit) * invoice.rate + riskUnit * risk.rate
      rowTotal = round2(baseUnit * quantity + expensesItem)
      dutyRub += dutyUnit * quantity * invoice.rate
      vatRub += vatUnit * quantity * invoice.rate
    }
    itemTotal[item.key] = rowTotal
    unit[item.key] = quantity > 0 ? round2(rowTotal / quantity) : 0
  }

  let total = 0
  for (const item of draft.items) total += itemTotal[item.key] ?? 0

  // Средний курс партии — по обоим валютным долгам, взвешенно по их суммам.
  const debts = invoiceTotal + riskTotal
  const averageRate =
    debts > 0 ? round6((invoice.rate * invoiceTotal + risk.rate * riskTotal) / debts) : 0

  return {
    invoice,
    risk,
    cbrRate,
    averageRate,
    expensesRub,
    dutyRub,
    vatRub,
    unit,
    itemTotal,
    total,
    limitInvoiceExceeded: invoice.paidCurrency + invoice.plannedCurrency > invoiceTotal,
    limitRiskExceeded: risk.paidCurrency + risk.plannedCurrency > riskTotal,
  }
}

function draftFrom(batch: Batch): Draft {
  const isDraft = batch.source === '1c' && batch.items.length === 0
  return {
    id: batch.id,
    number: batch.batch_number,
    date: batch.batch_date,
    currency: batch.currency,
    supplierId: batch.supplier_id ?? (batch.supplier ? '__manual__' : ''),
    supplierText: batch.supplier_id ? '' : (batch.supplier ?? ''),
    // У черновика из 1С позиций нет — курс брать неоткуда. Оставляем пустым,
    // чтобы случайный курс не попал в себестоимость, когда добавят товар.
    rate: isDraft ? '' : trim(batch.finance.exchange_rate),
    rateDate: isDraft ? '' : (batch.finance.rate_date ?? ''),
    comment: batch.comment ?? '',
    items: batch.items.map((item, index) => ({
      key: `i${index}`,
      title: item.product_name,
      code: item.product_code,
      quantity: trim(item.quantity),
      // Цена неизвестна (позиции из файла «Партия») — поле оставляем пустым.
      price: number(item.unit_price_currency) === 0 ? '' : trim(item.unit_price_currency),
      duty: trim(item.duty_percent),
      vat: trim(item.vat_percent),
      risk: trim(item.risk_unit_currency),
      dutyRub: item.duty_fixed_rub === null ? '' : trim(item.duty_fixed_rub),
      vatRub: item.vat_fixed_rub === null ? '' : trim(item.vat_fixed_rub),
    })),
    payments: batch.payments.map((payment, index) => ({
      key: `p${index}`,
      date: payment.payment_date,
      amount: trim(payment.amount_currency),
      rate: trim(payment.exchange_rate),
      category: payment.category,
      comment: payment.comment ?? '',
    })),
    expenses: batch.expenses.map((expense, index) => ({
      key: `e${index}`,
      description: expense.description,
      currency: expense.currency,
      amount: trim(expense.amount_currency),
    })),
    isDraft,
    customsDate: batch.customs_date ?? '',
    customsRate: batch.customs_rate === null ? '' : trim(batch.customs_rate),
  }
}

function emptyDraft(day: string): Draft {
  return {
    id: null,
    number: '',
    date: day,
    currency: 'RUB',
    supplierId: '',
    supplierText: '',
    rate: '1',
    // Курс ещё не выбирали: подпись покажет «введён вручную», пока не нажмут «Курс ЦБ».
    rateDate: '',
    comment: '',
    items: [
      {
        key: 'i0',
        title: '',
        code: '',
        quantity: '',
        price: '',
        duty: '0',
        vat: '22',
        risk: '0',
        dutyRub: '',
        vatRub: '',
      },
    ],
    payments: [],
    expenses: [],
    isDraft: false,
    customsDate: '',
    customsRate: '',
  }
}

/**
 * Слепок карточки — то, что уйдёт на сервер при сохранении.
 *
 * Растаможка и её отмена считают суммы по **сохранённым** строкам, поэтому
 * несохранённые правки в карточке нужно поймать до нажатия кнопки: сравниваем
 * текущий слепок с тем, что пришло с сервера.
 */
function snapshot(source: Draft): string {
  return JSON.stringify({
    number: source.number.trim(),
    date: source.date,
    currency: source.currency.trim().toUpperCase(),
    supplierId: source.supplierId,
    supplierText: source.supplierText.trim(),
    rate: source.rate.replace(',', '.'),
    rateDate: source.rateDate,
    comment: source.comment,
    items: source.items.map((row) => [
      row.code,
      row.quantity,
      row.price,
      row.duty,
      row.vat,
      row.risk,
      row.dutyRub,
      row.vatRub,
    ]),
    payments: source.payments.map((row) => [
      row.date,
      row.amount,
      row.rate,
      row.category,
      row.comment,
    ]),
    expenses: source.expenses.map((row) => [row.description, row.currency, row.amount]),
  })
}

export function ReceiptsPage({ user }: { user?: SessionUser }) {
  const today = iso(new Date())
  const [month, setMonth] = useState(today.slice(0, 7))
  const [batches, setBatches] = useState<Batch[]>([])
  const [day, setDay] = useState(today)
  const [draft, setDraft] = useState<Draft | null>(null)
  /** Слепок сохранённой карточки: по нему видно, есть ли несохранённые правки. */
  const [savedSnapshot, setSavedSnapshot] = useState<string | null>(null)
  /** Пометка «сохранено»: карточка после сохранения остаётся открытой. */
  const [savedHint, setSavedHint] = useState<string | null>(null)
  const [suppliers, setSuppliers] = useState<Counterparty[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [rateHint, setRateHint] = useState<string | null>(null)
  const [itemsFile, setItemsFile] = useState<File | null>(null)
  const [itemsHint, setItemsHint] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  /** Окно подтверждения растаможки: дата, курс и правимые итоги. */
  const [customs, setCustoms] = useState<CustomsDraft | null>(null)
  /** Какая вкладка открыта в карточке: по умолчанию — позиции. */
  const [tab, setTab] = useState<TabId>('items')
  /** Курс ЦБ на сегодня для расходов в usd: без даты — последний доступный. */
  const [usdRate, setUsdRate] = useState<string | null>(null)
  const itemsInput = useRef<HTMLInputElement>(null)
  // Ключи новых строк: у загруженных строк ключи вида i0/p0/e0, поэтому у новых
  // префикс другой — иначе React получает два элемента с одинаковым ключом.
  const keyCounter = useRef(1)
  const nextKey = (prefix: string) => `${prefix}new${keyCounter.current++}`
  const mayLoadItems = !user || ITEM_IMPORT_ROLES.includes(user.role)
  // Отмена растаможки — директору по закупкам (как решено в контракте, §4).
  const mayCancelCustoms = !user || user.role === 'purchase_director'

  const reload = useCallback(async () => {
    const first = `${month}-01`
    const last = iso(new Date(monthStart(month).getFullYear(), monthStart(month).getMonth() + 1, 0))
    try {
      setBatches(await fetchBatches(first, last))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [month])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    Promise.all([
      fetchCounterparties({ role: 'local_supplier' }),
      fetchCounterparties({ role: 'import_supplier' }),
    ])
      .then(([local, imported]) => {
        const merged = new Map<string, Counterparty>()
        for (const row of [...local, ...imported]) merged.set(row.id, row)
        setSuppliers([...merged.values()].sort((a, b) => a.name.localeCompare(b.name, 'ru')))
      })
      .catch(() => setSuppliers([]))
    fetchProducts()
      .then((rows) => setProducts(rows.filter((product) => product.is_active)))
      .catch(() => setProducts([]))
  }, [])

  useEffect(() => {
    // Курс ЦБ на сегодня нужен расходам в usd; без него такой расход не оценён.
    fetchRate('USD')
      .then((rate) => setUsdRate(rate.rate))
      .catch(() => setUsdRate(null))
  }, [])

  const weeks = useMemo(() => {
    const cells = monthDays(month)
    const rows: { date: string; inMonth: boolean }[][] = []
    for (let index = 0; index < cells.length; index += 7) {
      rows.push(cells.slice(index, index + 7))
    }
    return rows
  }, [month])

  const byDay = useMemo(() => {
    const map = new Map<string, Batch[]>()
    for (const batch of batches) {
      const list = map.get(batch.batch_date) ?? []
      list.push(batch)
      map.set(batch.batch_date, list)
    }
    return map
  }, [batches])

  const dayBatches = byDay.get(day) ?? []
  const cost = draft ? liveCost(draft, usdRate === null ? null : number(usdRate)) : null
  const hasRisk = (cost?.risk.total ?? 0) > 0
  /** Партия растаможена: пошлина и НДС — фикс в рублях, строки только для чтения. */
  const cleared = (draft?.customsDate ?? '') !== ''
  /** В карточке есть правки, которых нет на сервере: таможню считать ещё не по чему. */
  const dirty = draft !== null && savedSnapshot !== null && snapshot(draft) !== savedSnapshot
  /**
   * Открыто окно растаможки: строки карточки за ним не правятся. Иначе количество, цену
   * или процент можно поменять уже после того, как суммы в окне посчитаны: в окне останутся
   * старые числа, а в базе — другой процент, чем тот, по которому зафиксирована таможня.
   */
  const locked = customs !== null

  const shiftMonth = (delta: number) => {
    const base = monthStart(month)
    base.setMonth(base.getMonth() + delta)
    const next = `${base.getFullYear()}-${String(base.getMonth() + 1).padStart(2, '0')}`
    setMonth(next)
    setDay(`${next}-01`)
  }

  const startCreate = (target = day) => {
    setTab('items')
    setRateHint(null)
    setError(null)
    setItemsFile(null)
    setItemsHint(null)
    setCustoms(null)
    const fresh = emptyDraft(target)
    setDraft(fresh)
    setSavedSnapshot(snapshot(fresh))
    setSavedHint(null)
  }

  const startEdit = (batch: Batch) => {
    setTab('items')
    setRateHint(null)
    setError(null)
    setItemsFile(null)
    setItemsHint(null)
    setCustoms(null)
    const fresh = draftFrom(batch)
    setDraft(fresh)
    setSavedSnapshot(snapshot(fresh))
    setSavedHint(null)
  }

  /**
   * Позиции из файла «Партия» (1С): в партию попадают товар и количество.
   * Цену, пошлину, НДС и Risk файл не несёт — их заполняют в карточке.
   */
  const loadItems = async () => {
    if (!draft?.id || !itemsFile) return
    setBusy(true)
    setError(null)
    setItemsHint(null)
    try {
      const result = await uploadBatchItems(draft.id, itemsFile)
      const fresh = draftFrom(result.batch)
      setDraft(fresh)
      setSavedSnapshot(snapshot(fresh))
      setSavedHint(null)
      setItemsFile(null)
      if (itemsInput.current) itemsInput.current.value = ''
      const replaced = result.report.rows_updated
      setItemsHint(
        `Из файла загружено строк: ${result.report.rows_created}` +
          (replaced ? `, заменено прежних: ${replaced}` : ''),
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  /**
   * «Обновить курс ЦБ» — курс для незакрытого остатка.
   *
   * Берём **актуальный** курс (последний доступный день), а не курс на дату
   * поступления: дата в прошлом задаёт только растаможку.
   */
  const fillRate = async () => {
    if (!draft) return
    setRateHint(null)
    try {
      const rate = await fetchRate(draft.currency.trim().toUpperCase() || 'RUB')
      setDraft({ ...draft, rate: rate.rate, rateDate: rate.rate_date ?? '' })
      setRateHint(
        rate.source === 'base'
          ? 'Рубль — курс 1'
          : `Актуальный курс ЦБ на ${ruDate(rate.rate_date)}: ${rate.rate} ₽ за 1 ${rate.code}`,
      )
    } catch (err) {
      setRateHint(errorMessage(err))
    }
  }

  /**
   * Итоги растаможки по строкам: пошлина и НДС партии в рублях по курсу фиксации.
   * Округление как на сервере — валютная сумма строки, потом умножение на курс.
   */
  const customsTotals = (source: Draft, rate: number): { duty: number; vat: number } => {
    let duty = 0
    let vat = 0
    for (const item of source.items) {
      const quantity = number(item.quantity)
      const price = number(item.price)
      const dutyUnit = (price * number(item.duty)) / 100
      const vatUnit = ((price + dutyUnit) * number(item.vat)) / 100
      duty += round2(round2(dutyUnit * quantity) * rate)
      vat += round2(round2(vatUnit * quantity) * rate)
    }
    return { duty: round2(duty), vat: round2(vat) }
  }

  const batchCurrencyRate = (source: Draft) =>
    source.currency.trim().toUpperCase() === 'RUB' ? 1 : number(source.rate) || 1

  /**
   * Курс ЦБ на выбранную дату растаможки: подтягиваем сами при смене даты и по кнопке.
   *
   * Здесь дата в прошлом уместна — именно ею фиксируются пошлина и НДС.
   */
  const loadCustomsRate = async (day: string) => {
    if (!draft || !day) return
    try {
      const row = await fetchRate(draft.currency.trim().toUpperCase() || 'RUB', day)
      const rate = number(row.rate) || 1
      setCustoms((current) => {
        // Пока ходили в ЦБ, дату могли сменить: применяем ответ только к своей дате.
        if (current === null || current.date !== day) return current
        const totals = customsTotals(draft, rate)
        return {
          ...current,
          rate: trim(row.rate),
          duty: String(totals.duty),
          vat: String(totals.vat),
          hint:
            row.source === 'base'
              ? 'Рубль — курс 1'
              : `Курс ЦБ на ${ruDate(day)}: ${trim(row.rate)} ₽ за 1 ${row.code}`,
        }
      })
    } catch (err) {
      setCustoms((current) =>
        current === null || current.date !== day
          ? current
          : { ...current, hint: `${errorMessage(err)} — введите курс вручную` },
      )
    }
  }

  /** Открыть окно растаможки: дата — сегодня, курс — ЦБ на эту дату (если доступен). */
  const openCustoms = async () => {
    if (!draft?.id) return
    const start = iso(new Date())
    const fallbackRate = batchCurrencyRate(draft)
    const totals = customsTotals(draft, fallbackRate)
    setError(null)
    setCustoms({
      date: start,
      rate: trim(String(fallbackRate)),
      duty: String(totals.duty),
      vat: String(totals.vat),
      hint: null,
    })
    await loadCustomsRate(start)
  }

  /** Курс в окне растаможки правят руками — итоги пересчитываем по строкам. */
  const changeCustomsRate = (value: string) => {
    if (!draft || !customs) return
    const totals = customsTotals(draft, number(value))
    setCustoms({
      ...customs,
      rate: value,
      duty: String(totals.duty),
      vat: String(totals.vat),
    })
  }

  const submitCustoms = async () => {
    if (!draft?.id || !customs) return
    setBusy(true)
    setError(null)
    try {
      const batch = await applyCustoms(draft.id, {
        customs_date: customs.date,
        rate: customs.rate.replace(',', '.') || '0',
        duty_rub: customs.duty.replace(',', '.') || '0',
        vat_rub: customs.vat.replace(',', '.') || '0',
      })
      const fresh = draftFrom(batch)
      setDraft(fresh)
      setSavedSnapshot(snapshot(fresh))
      setCustoms(null)
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const dropCustoms = async () => {
    if (!draft?.id) return
    setBusy(true)
    setError(null)
    try {
      const batch = await cancelCustoms(draft.id)
      const fresh = draftFrom(batch)
      setDraft(fresh)
      setSavedSnapshot(snapshot(fresh))
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!draft) return
    const current = liveCost(draft, usdRate === null ? null : number(usdRate))
    if (current.limitInvoiceExceeded || current.limitRiskExceeded) {
      setError('Сумма валютных платежей больше суммы партии по этой категории')
      return
    }
    const items = draft.items
      .filter((item) => item.code.trim() !== '' && number(item.quantity) > 0)
      .map((item) => ({
        product_code: item.code.trim(),
        quantity: item.quantity.replace(',', '.'),
        unit_price_currency: (item.price || '0').replace(',', '.'),
        duty_percent: (item.duty || '0').replace(',', '.'),
        vat_percent: (item.vat || '0').replace(',', '.'),
        risk_unit_currency: (item.risk || '0').replace(',', '.'),
      }))
    if (items.length === 0 && !draft.isDraft) {
      setError('Добавьте хотя бы одну строку: товар и количество')
      return
    }
    const payload: BatchIn = {
      batch_number: draft.number.trim(),
      batch_date: draft.date,
      currency: draft.currency.trim().toUpperCase() || 'RUB',
      supplier_id: draft.supplierId && draft.supplierId !== '__manual__' ? draft.supplierId : null,
      supplier:
        draft.supplierId === '__manual__'
          ? draft.supplierText.trim() || null
          : (suppliers.find((row) => row.id === draft.supplierId)?.name ?? null),
      current_exchange_rate: draft.currency === 'RUB' ? '1' : draft.rate.replace(',', '.') || null,
      auto_rate: false,
      comment: draft.comment || null,
      items,
      payments: draft.payments
        .filter((row) => number(row.amount) > 0 && number(row.rate) > 0)
        .map((row) => ({
          payment_date: row.date,
          amount_currency: row.amount.replace(',', '.'),
          exchange_rate: row.rate.replace(',', '.'),
          category: row.category,
          comment: row.comment.trim() === '' ? null : row.comment.trim(),
        })),
      expenses: draft.expenses
        .filter((row) => number(row.amount) > 0)
        .map((row) => ({
          amount_currency: row.amount.replace(',', '.'),
          currency: row.currency,
          description: row.description,
        })),
    }
    setBusy(true)
    setError(null)
    try {
      const saved = draft.id ? await updateBatch(draft.id, payload) : await createBatch(payload)
      // Карточка не закрывается, а показывает то, что записал сервер: сразу видно
      // результат и можно переходить к растаможке — она работает по сохранённым строкам.
      const fresh = draftFrom(saved)
      setDraft(fresh)
      setSavedSnapshot(snapshot(fresh))
      setSavedHint('Поступление сохранено')
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!draft?.id) return
    setBusy(true)
    try {
      await deleteBatch(draft.id)
      setDraft(null)
      setSavedSnapshot(null)
      setSavedHint(null)
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  /**
   * Подпись под шапкой: каким курсом оценён незакрытый остаток.
   * Курс остатка — актуальный ЦБ; с даты поступления он не берётся.
   */
  const rateCaption = (() => {
    if (!draft) return ''
    const code = draft.currency.trim().toUpperCase() || 'RUB'
    if (code === 'RUB') return 'Рубль — курс 1'
    if (number(draft.rate) <= 0) return 'Курс остатка не задан — нажмите «Обновить курс ЦБ».'
    const value = `${formatRate(number(draft.rate))} ₽ за 1 ${code}`
    return draft.rateDate
      ? `Незакрытый остаток оценивается по актуальному курсу ЦБ на ${ruDate(draft.rateDate)} — ${value}: дата поступления на курс не влияет.`
      : `Курс остатка введён вручную — ${value} (например, когда ЦБ недоступен).`
  })()

  /** Закрыть карточку и вернуться к календарю; несохранённые правки спрашиваем. */
  const closeDocument = () => {
    if (
      dirty &&
      !window.confirm('В карточке есть несохранённые изменения. Закрыть без сохранения?')
    ) {
      return
    }
    setCustoms(null)
    setDraft(null)
    setSavedHint(null)
    setSavedSnapshot(null)
  }

  /* ── Календарь и список за день: карточка закрыта ───────────────────── */

  if (!draft || !cost) {
    return (
      <section>
        <header className="page-head">
          <h1>Поступления</h1>
          <p className="hint">
            Календарь поступлений партий: поставщик, товары, валюта и курс. Себестоимость
            пересчитывается сразу при изменении курса, сумм и расходов.
          </p>
          <div className="toolbar">
            <button type="button" onClick={() => shiftMonth(-1)} aria-label="Предыдущий месяц">
              ←
            </button>
            <strong data-testid="receipts-month">{month}</strong>
            <button type="button" onClick={() => shiftMonth(1)} aria-label="Следующий месяц">
              →
            </button>
            <span className="sep" />
            <button type="button" className="primary" onClick={() => startCreate(day)}>
              Добавить поступление
            </button>
          </div>
        </header>

        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}

        <table className="calendar" data-testid="receipts-calendar">
          <thead>
            <tr>
              {WEEKDAYS.map((title) => (
                <th key={title} scope="col">
                  {title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {weeks.map((week) => (
              <tr key={week[0]?.date ?? 'week'}>
                {week.map((cell) => {
                  const rows = byDay.get(cell.date) ?? []
                  const total = rows.reduce(
                    (sum, batch) => sum + Number(batch.finance.final_cost_rub),
                    0,
                  )
                  const clearedCount = rows.filter((batch) => batch.customs_date).length
                  return (
                    <td
                      key={cell.date}
                      className={[
                        'calendar-day',
                        cell.inMonth ? '' : 'other-month',
                        cell.date === day ? 'selected' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                    >
                      <button
                        type="button"
                        className="calendar-cell"
                        onClick={() => setDay(cell.date)}
                        data-testid={`day-${cell.date}`}
                      >
                        <span className="calendar-date">{Number(cell.date.slice(-2))}</span>
                        {rows.length > 0 ? (
                          <>
                            <span className="badge status-filling">поступлений: {rows.length}</span>
                            {clearedCount > 0 ? (
                              <span
                                className="badge status-clearance"
                                data-testid={`day-cleared-${cell.date}`}
                              >
                                растаможено: {clearedCount}
                              </span>
                            ) : null}
                            {/* У черновиков из 1С позиций ещё нет: нулевая себестоимость — не итог дня. */}
                            {total > 0 ? (
                              <span className="calendar-sum">{formatMoney(String(total))} ₽</span>
                            ) : (
                              <span
                                className="calendar-sum"
                                data-testid={`day-drafts-${cell.date}`}
                              >
                                черновики
                              </span>
                            )}
                          </>
                        ) : null}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>

        <h2 className="section-title">Поступления на {day}</h2>
        {dayBatches.length === 0 ? (
          <p className="hint" data-testid="day-empty">
            В этот день поступлений нет.
          </p>
        ) : (
          <table data-testid="day-receipts">
            <thead>
              <tr>
                <th scope="col">Номер</th>
                <th scope="col">Поставщик</th>
                <th scope="col">Позиций</th>
                <th scope="col">Валюта</th>
                <th scope="col" className="num">
                  Курс
                </th>
                <th scope="col" className="num">
                  Себестоимость, ₽
                </th>
                <th scope="col" aria-label="Действия" />
              </tr>
            </thead>
            <tbody>
              {dayBatches.map((batch) => {
                const isDraft = batch.source === '1c' && batch.items.length === 0
                return (
                  <tr key={batch.id} data-testid={`day-receipt-${batch.id}`}>
                    <td>
                      {batch.batch_number}
                      {isDraft ? (
                        <span className="badge status-draft" data-testid="draft-badge">
                          {' '}
                          черновик
                        </span>
                      ) : null}
                      {batch.customs_date ? (
                        <span
                          className="badge status-clearance"
                          data-testid="clearance-badge"
                          title={`Растаможена ${batch.customs_date}`}
                        >
                          {' '}
                          растаможена
                        </span>
                      ) : null}
                    </td>
                    <td>{batch.supplier ?? '—'}</td>
                    <td>{batch.items.length}</td>
                    <td>{batch.currency}</td>
                    <td className="num">{isDraft ? '—' : trim(batch.finance.average_rate)}</td>
                    <td className="num">
                      {isDraft ? '—' : formatMoney(batch.finance.final_cost_rub)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="mini"
                        onClick={() => {
                          setTab('items')
                          startEdit(batch)
                        }}
                      >
                        Открыть
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    )
  }

  /* ── Карточка партии: отдельный экран документа ─────────────────────── */

  const currency = draft.currency.trim().toUpperCase() || 'RUB'
  const money = (value: number) => formatMoney(String(value))
  const invoiceRub = cost.invoice.total * cost.invoice.rate
  const riskRub = cost.risk.total * cost.risk.rate
  const partsTotal = invoiceRub + riskRub + cost.dutyRub + cost.vatRub + cost.expensesRub
  const sharePct = (part: number) =>
    partsTotal > 0 ? Math.round((part / partsTotal) * 1000) / 10 : 0
  const shareText = (part: number) => String(sharePct(part)).replace('.', ',')
  const paidRub = cost.invoice.paidRub + cost.risk.paidRub

  return (
    <section className="receipt-doc" data-testid="receipt-doc">
      <div className="doc-crumbs">
        <span>Закупки</span>
        <span className="sep">/</span>
        <span>Поступления</span>
        <span className="sep">/</span>
        <strong>{draft.number.trim() || 'новое поступление'}</strong>
      </div>

      <form className="receipt-form receipt-doc-form" onSubmit={submit} data-testid="receipt-form">
        <header className="doc-header">
          <div className="doc-header-main">
            <button
              type="button"
              className="back-link"
              data-testid="receipt-back"
              onClick={closeDocument}
            >
              ← К поступлениям
            </button>
            <div className="doc-title-row">
              <input
                className="doc-title-input"
                aria-label="Номер поступления"
                placeholder="Новый номер"
                value={draft.number}
                size={Math.max(draft.number.length, 8)}
                onChange={(event) => setDraft({ ...draft, number: event.target.value })}
                required
              />
              {draft.isDraft ? (
                <span className="badge status-draft" data-testid="draft-badge">
                  черновик
                </span>
              ) : null}
              {draft.customsDate ? (
                <span className="badge status-clearance" data-testid="customs-badge">
                  растаможена {ruDate(draft.customsDate)}
                  {draft.customsRate ? ` · курс ${trim(draft.customsRate)}` : ''}
                </span>
              ) : null}
              {!draft.isDraft && !draft.customsDate && draft.id ? (
                <span className="badge status-filling">в работе</span>
              ) : null}
              {draft.id ? <span className="badge status-source">из 1С</span> : null}
            </div>
            {savedHint && !dirty ? (
              <p className="hint saved" data-testid="receipt-saved">
                {savedHint}
              </p>
            ) : null}
            {draft.isDraft ? (
              <p className="hint" data-testid="draft-hint">
                Черновик из выгрузки 1С: заполнены номер, дата, поставщик и комментарий. Загрузите
                файл «Партия» из 1С или добавьте позиции вручную — и поступление станет обычным.
              </p>
            ) : null}
          </div>
          <div className="doc-header-actions">
            {draft.customsDate === '' ? (
              <button
                type="button"
                className="primary"
                data-testid="customs-start"
                disabled={busy || dirty || !draft.id || draft.items.length === 0}
                onClick={() => void openCustoms()}
              >
                Растаможить
              </button>
            ) : mayCancelCustoms ? (
              <button
                type="button"
                data-testid="customs-cancel"
                disabled={busy || dirty}
                onClick={() => void dropCustoms()}
              >
                Отменить растаможку
              </button>
            ) : null}
          </div>
        </header>

        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}

        <section className="doc-passport" aria-label="Реквизиты поступления">
          <label className="field">
            Дата
            <input
              type="date"
              aria-label="Дата поступления"
              value={draft.date}
              onChange={(event) => setDraft({ ...draft, date: event.target.value })}
              required
            />
          </label>
          <label className="field">
            Поставщик
            <select
              aria-label="Поставщик"
              value={draft.supplierId}
              onChange={(event) => setDraft({ ...draft, supplierId: event.target.value })}
            >
              <option value="">— не выбран —</option>
              {suppliers.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
              <option value="__manual__">— ввести вручную —</option>
            </select>
          </label>
          {draft.supplierId === '__manual__' ? (
            <label className="field">
              Название поставщика
              <input
                aria-label="Название поставщика"
                value={draft.supplierText}
                onChange={(event) => setDraft({ ...draft, supplierText: event.target.value })}
              />
            </label>
          ) : null}
          <label className="field">
            Валюта
            <input
              aria-label="Валюта"
              value={draft.currency}
              // Фикс таможни посчитан в валюте партии: после растаможки её не меняем,
              // а пока открыто окно — тем более: суммы посчитаны в этой валюте.
              disabled={cleared || locked}
              onChange={(event) => setDraft({ ...draft, currency: event.target.value })}
            />
          </label>
          <div className="field">
            <span>Курс остатка, ₽</span>
            <div className="rate-row">
              <input
                aria-label="Курс"
                value={draft.rate}
                onChange={(event) =>
                  // Курс вписан руками — дата курса ЦБ больше не применима.
                  setDraft({ ...draft, rate: event.target.value, rateDate: '' })
                }
              />
              <button type="button" aria-label="Обновить курс ЦБ" onClick={() => void fillRate()}>
                Курс ЦБ
              </button>
            </div>
          </div>
          <label className="field doc-comment">
            Комментарий
            <textarea
              aria-label="Комментарий"
              rows={2}
              value={draft.comment}
              onChange={(event) => setDraft({ ...draft, comment: event.target.value })}
            />
          </label>
        </section>

        {rateHint ? <p className="hint">{rateHint}</p> : null}
        {/* Каким курсом и на какую дату оценён незакрытый остаток. */}
        <p className="hint doc-rate-caption" data-testid="receipt-cbr-rate">
          {rateCaption}
        </p>

        {dirty ? (
          // Таможня считает суммы по сохранённым строкам: с несохранёнными правками
          // карточка после растаможки вернулась бы к состоянию на сервере.
          <p className="hint" data-testid="customs-dirty">
            В карточке есть несохранённые изменения. Сначала сохраните поступление — потом
            растаможка посчитает суммы по сохранённым строкам.
          </p>
        ) : null}
        {draft.customsDate === '' && !draft.id ? (
          <p className="hint" data-testid="customs-need-save">
            Растаможка доступна после сохранения поступления.
          </p>
        ) : null}

        <section className="kpis" aria-label="Итоги партии">
          <div className="kpi kpi-primary">
            <span className="kpi-label">Себестоимость</span>
            <span className="kpi-value" data-testid="receipt-total">
              {money(cost.total)} ₽
            </span>
            <span className="kpi-sub">
              {draft.items.length} поз. · {currency}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-label">Средний курс</span>
            <span className="kpi-value" data-testid="receipt-average-rate">
              {formatRate(cost.averageRate)}
            </span>
            <span className="kpi-sub">
              {trim(draft.rate) ? (
                <>
                  инвойс <b data-testid="receipt-effective">{formatRate(cost.invoice.rate)}</b> ·
                  Risk <b data-testid="receipt-risk-rate">{formatRate(cost.risk.rate)}</b>
                </>
              ) : (
                'курс не задан'
              )}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-label">Инвойс</span>
            <span className="kpi-value" data-testid="receipt-invoice">
              {money(cost.invoice.total)} {currency}
            </span>
            <span className="kpi-sub">
              {cost.invoice.paidCurrency > 0
                ? `оплачено ${money(cost.invoice.paidCurrency)} ${currency}`
                : 'не оплачен'}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-label">Risk</span>
            <span className="kpi-value" data-testid="receipt-risk-total">
              {money(cost.risk.total)} {currency}
            </span>
            <span className="kpi-sub">
              {cost.risk.total === 0
                ? 'нет в партии'
                : cost.risk.paidCurrency >= cost.risk.total
                  ? 'оплачен'
                  : `оплачено ${money(cost.risk.paidCurrency)} ${currency}`}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-label">Пошлина</span>
            <span className="kpi-value" data-testid="receipt-duty">
              {money(cost.dutyRub)} ₽
            </span>
            <span className="kpi-sub">{cleared ? 'зафиксирована' : 'в процентах по строкам'}</span>
          </div>
          <div className="kpi">
            <span className="kpi-label">НДС</span>
            <span className="kpi-value" data-testid="receipt-vat">
              {money(cost.vatRub)} ₽
            </span>
            <span className="kpi-sub">{cleared ? 'зафиксирован' : 'в процентах по строкам'}</span>
          </div>
        </section>

        <div className="doc-tabs-panel">
          <div className="receipt-tabs" role="tablist" aria-label="Разделы поступления">
            <button
              type="button"
              role="tab"
              id="tab-items"
              aria-selected={tab === 'items'}
              aria-controls="panel-items"
              aria-label="Позиции"
              data-testid="tab-items"
              className={tab === 'items' ? 'tab active' : 'tab'}
              onClick={() => setTab('items')}
            >
              Позиции <span className="tab-count">{draft.items.length}</span>
            </button>
            <button
              type="button"
              role="tab"
              id="tab-expenses"
              aria-selected={tab === 'expenses'}
              aria-controls="panel-expenses"
              aria-label="Общие расходы"
              data-testid="tab-expenses"
              className={tab === 'expenses' ? 'tab active' : 'tab'}
              onClick={() => setTab('expenses')}
            >
              Общие расходы <span className="tab-count">{draft.expenses.length}</span>
            </button>
            <button
              type="button"
              role="tab"
              id="tab-payments"
              aria-selected={tab === 'payments'}
              aria-controls="panel-payments"
              aria-label="Платежи"
              data-testid="tab-payments"
              className={tab === 'payments' ? 'tab active' : 'tab'}
              onClick={() => setTab('payments')}
            >
              Платежи <span className="tab-count">{draft.payments.length}</span>
            </button>
            <button
              type="button"
              role="tab"
              id="tab-customs"
              aria-selected={tab === 'customs'}
              aria-controls="panel-customs"
              aria-label="Таможня"
              data-testid="tab-customs"
              className={tab === 'customs' ? 'tab active' : 'tab'}
              onClick={() => setTab('customs')}
            >
              Таможня
            </button>
            <button
              type="button"
              role="tab"
              id="tab-cost"
              aria-selected={tab === 'cost'}
              aria-controls="panel-cost"
              aria-label="Себестоимость"
              data-testid="tab-cost"
              className={tab === 'cost' ? 'tab active' : 'tab'}
              onClick={() => setTab('cost')}
            >
              Себестоимость
            </button>
          </div>

          {tab === 'items' ? (
            <div className="doc-card" id="panel-items" role="tabpanel" aria-labelledby="tab-items">
              <div className="doc-card-head">
                <h2 className="doc-card-title">Позиции</h2>
                <span className="doc-card-sub">{draft.items.length} строк</span>
                <span className="spacer" />
                {cleared ? null : (
                  <button
                    type="button"
                    disabled={locked}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        items: [
                          ...draft.items,
                          {
                            key: nextKey('i'),
                            title: '',
                            code: '',
                            quantity: '',
                            price: '',
                            duty: '0',
                            vat: '22',
                            risk: '0',
                            dutyRub: '',
                            vatRub: '',
                          },
                        ],
                      })
                    }
                  >
                    Добавить строку
                  </button>
                )}
              </div>

              {draft.id && mayLoadItems ? (
                <div className="doc-toolbar" data-testid="batch-items-import">
                  <span className="doc-toolbar-label">Позиции из 1С (файл «Партия»)</span>
                  <label className="file-pick">
                    Выбрать файл
                    <input
                      ref={itemsInput}
                      type="file"
                      accept=".xlsx"
                      aria-label="Файл партии из 1С"
                      // Пока открыто окно растаможки, позиции из файла не подменяем.
                      disabled={busy || locked}
                      onChange={(event) => {
                        setItemsFile(event.target.files?.[0] ?? null)
                        setItemsHint(null)
                      }}
                    />
                  </label>
                  <span className="file-pick-name">
                    {itemsFile ? itemsFile.name : 'файл не выбран'}
                  </span>
                  <button
                    type="button"
                    disabled={busy || locked || !itemsFile}
                    onClick={() => void loadItems()}
                  >
                    {busy ? 'Загрузка…' : 'Загрузить позиции из 1С'}
                  </button>
                  <span className="hint">Из файла берутся товар и количество</span>
                </div>
              ) : null}
              {itemsHint ? (
                <p className="hint doc-inline-hint" data-testid="batch-items-hint">
                  {itemsHint}
                </p>
              ) : null}

              <div className="table-scroll">
                <table className="receipt-items" data-testid="receipt-items">
                  <thead>
                    <tr>
                      <th scope="col">Товар</th>
                      <th scope="col" className="num">
                        Стоимость за ед., {currencyLabel(draft.currency)}
                      </th>
                      <th scope="col" className="num">
                        Кол-во
                      </th>
                      <th scope="col" className="num">
                        Пошлина, {cleared ? '₽' : '%'}
                      </th>
                      <th scope="col" className="num">
                        НДС, {cleared ? '₽' : '%'}
                      </th>
                      <th scope="col" className="num">
                        Risk, {currencyLabel(draft.currency)}
                      </th>
                      <th scope="col" className="num">
                        Цена за ед., ₽
                      </th>
                      <th scope="col" className="num">
                        Сумма, ₽
                      </th>
                      <th scope="col" aria-label="Действия" />
                    </tr>
                  </thead>
                  <tbody>
                    {draft.items.length === 0 ? (
                      <tr>
                        <td colSpan={9} className="hint">
                          Позиций пока нет — добавьте строку или загрузите файл «Партия» из 1С.
                        </td>
                      </tr>
                    ) : null}
                    {draft.items.map((item) => (
                      <tr key={item.key}>
                        <td>
                          {cleared ? (
                            <>
                              <span data-testid={`item-title-${item.key}`}>{item.title}</span>
                              {item.code ? (
                                <span className="unit" data-testid={`product-code-${item.key}`}>
                                  код {item.code}
                                </span>
                              ) : null}
                            </>
                          ) : (
                            <>
                              <input
                                aria-label={`Товар ${item.key}`}
                                list="receipt-products"
                                disabled={locked}
                                placeholder="название товара"
                                value={item.title}
                                onChange={(event) => {
                                  // В поле — название; код под полем всегда тот, что уйдёт на сервер.
                                  const title = event.target.value
                                  const found = findProduct(products, title)
                                  setDraft({
                                    ...draft,
                                    items: draft.items.map((row) =>
                                      row.key === item.key
                                        ? { ...row, title, code: found?.code ?? '' }
                                        : row,
                                    ),
                                  })
                                }}
                              />
                              {item.code ? (
                                <span className="unit" data-testid={`product-code-${item.key}`}>
                                  код {item.code}
                                </span>
                              ) : item.title.trim() ? (
                                <span
                                  className="unit product-missing"
                                  data-testid={`product-missing-${item.key}`}
                                >
                                  нет в справочнике — строка не сохранится
                                </span>
                              ) : null}
                            </>
                          )}
                        </td>
                        <td className="num">
                          {cleared ? (
                            <span data-testid={`item-price-${item.key}`}>{item.price}</span>
                          ) : (
                            <input
                              className="cell"
                              aria-label={`Стоимость за ед. ${item.key}`}
                              disabled={locked}
                              value={item.price}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  items: draft.items.map((row) =>
                                    row.key === item.key
                                      ? { ...row, price: event.target.value }
                                      : row,
                                  ),
                                })
                              }
                            />
                          )}
                        </td>
                        <td className="num">
                          {cleared ? (
                            <span data-testid={`item-quantity-${item.key}`}>{item.quantity}</span>
                          ) : (
                            <input
                              className="cell"
                              aria-label={`Количество ${item.key}`}
                              disabled={locked}
                              value={item.quantity}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  items: draft.items.map((row) =>
                                    row.key === item.key
                                      ? { ...row, quantity: event.target.value }
                                      : row,
                                  ),
                                })
                              }
                            />
                          )}
                        </td>
                        <td className="num" data-testid={`item-duty-${item.key}`}>
                          {cleared ? (
                            // После растаможки в колонке — зафиксированные рубли, а не процент.
                            formatMoney(item.dutyRub || '0')
                          ) : (
                            <input
                              className="cell"
                              aria-label={`Пошлина ${item.key}`}
                              disabled={locked}
                              value={item.duty}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  items: draft.items.map((row) =>
                                    row.key === item.key
                                      ? { ...row, duty: event.target.value }
                                      : row,
                                  ),
                                })
                              }
                            />
                          )}
                        </td>
                        <td className="num" data-testid={`item-vat-${item.key}`}>
                          {cleared ? (
                            formatMoney(item.vatRub || '0')
                          ) : (
                            <input
                              className="cell"
                              aria-label={`НДС ${item.key}`}
                              disabled={locked}
                              value={item.vat}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  items: draft.items.map((row) =>
                                    row.key === item.key
                                      ? { ...row, vat: event.target.value }
                                      : row,
                                  ),
                                })
                              }
                            />
                          )}
                        </td>
                        <td className="num">
                          {cleared ? (
                            <span data-testid={`item-risk-${item.key}`}>{item.risk}</span>
                          ) : (
                            <input
                              className="cell"
                              aria-label={`Risk ${item.key}`}
                              disabled={locked}
                              value={item.risk}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  items: draft.items.map((row) =>
                                    row.key === item.key
                                      ? { ...row, risk: event.target.value }
                                      : row,
                                  ),
                                })
                              }
                            />
                          )}
                        </td>
                        <td className="num" data-testid={`unit-cost-${item.key}`}>
                          {formatMoney(String(cost.unit[item.key] ?? 0))}
                        </td>
                        <td className="num" data-testid={`item-total-${item.key}`}>
                          {formatMoney(String(cost.itemTotal[item.key] ?? 0))}
                        </td>
                        <td>
                          {cleared ? null : (
                            <button
                              type="button"
                              className="mini"
                              disabled={locked}
                              onClick={() =>
                                setDraft({
                                  ...draft,
                                  items: draft.items.filter((row) => row.key !== item.key),
                                })
                              }
                            >
                              Убрать
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <datalist id="receipt-products">
                {products.map((product) => (
                  <option key={product.id} value={product.name}>
                    {product.code}
                  </option>
                ))}
              </datalist>
              {cleared ? (
                <p className="hint doc-inline-hint" data-testid="customs-hint">
                  Таможня пройдена {draft.customsDate}: пошлина и НДС зафиксированы в рублях по
                  курсу {trim(draft.customsRate)} и больше не пересчитываются. Строки изменить
                  нельзя — сначала отмените растаможку.
                </p>
              ) : null}
            </div>
          ) : null}

          {tab === 'expenses' ? (
            <div
              className="doc-card"
              id="panel-expenses"
              role="tabpanel"
              aria-labelledby="tab-expenses"
            >
              <div className="doc-card-head">
                <h2 className="doc-card-title">Общие расходы</h2>
                <span className="doc-card-sub">на всю партию</span>
                <span className="spacer" />
                <button
                  type="button"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      expenses: [
                        ...draft.expenses,
                        { key: nextKey('e'), description: '', currency: 'RUB', amount: '' },
                      ],
                    })
                  }
                >
                  Добавить расход
                </button>
              </div>
              <p className="hint doc-inline-hint">
                Доставка, оформление и прочее. Валюта — только руб. или usd; расход в usd считается
                по курсу ЦБ на сегодня
                {usdRate === null ? ' (курс пока не получен)' : ` (${trim(usdRate)} ₽)`}.
              </p>
              <div className="table-scroll">
                <table className="receipt-expenses" data-testid="receipt-expenses">
                  <thead>
                    <tr>
                      <th scope="col">Название</th>
                      <th scope="col">Валюта</th>
                      <th scope="col" className="num">
                        Сумма
                      </th>
                      <th scope="col" className="num">
                        Сумма, ₽
                      </th>
                      <th scope="col" aria-label="Действия" />
                    </tr>
                  </thead>
                  <tbody>
                    {draft.expenses.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="hint">
                          Общих расходов нет.
                        </td>
                      </tr>
                    ) : (
                      draft.expenses.map((row) => (
                        <tr key={row.key}>
                          <td>
                            <input
                              aria-label={`Расход ${row.key}`}
                              placeholder="название расхода"
                              value={row.description}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  expenses: draft.expenses.map((expense) =>
                                    expense.key === row.key
                                      ? { ...expense, description: event.target.value }
                                      : expense,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td>
                            <select
                              aria-label={`Валюта расхода ${row.key}`}
                              value={row.currency}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  expenses: draft.expenses.map((expense) =>
                                    expense.key === row.key
                                      ? {
                                          ...expense,
                                          currency: event.target.value as ExpenseCurrency,
                                        }
                                      : expense,
                                  ),
                                })
                              }
                            >
                              <option value="RUB">руб.</option>
                              <option value="USD">usd</option>
                            </select>
                          </td>
                          <td className="num">
                            <input
                              className="cell"
                              aria-label={`Сумма расхода ${row.key}`}
                              value={row.amount}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  expenses: draft.expenses.map((expense) =>
                                    expense.key === row.key
                                      ? { ...expense, amount: event.target.value }
                                      : expense,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td className="num" data-testid={`expense-rub-${row.key}`}>
                            {formatMoney(
                              String(expenseRub(row, usdRate === null ? null : number(usdRate))),
                            )}
                          </td>
                          <td>
                            <button
                              type="button"
                              className="mini"
                              onClick={() =>
                                setDraft({
                                  ...draft,
                                  expenses: draft.expenses.filter(
                                    (expense) => expense.key !== row.key,
                                  ),
                                })
                              }
                            >
                              Убрать
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <div className="doc-card-foot">
                <span>
                  Итого расходов:{' '}
                  <strong data-testid="receipt-expenses-rub">{money(cost.expensesRub)} ₽</strong>
                </span>
              </div>
            </div>
          ) : null}

          {tab === 'payments' ? (
            <div
              className="doc-card"
              id="panel-payments"
              role="tabpanel"
              aria-labelledby="tab-payments"
            >
              <div className="doc-card-head">
                <h2 className="doc-card-title">Платежи</h2>
                <span className="doc-card-sub">закрывают инвойс и Risk</span>
                <span className="spacer" />
                <button
                  type="button"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      payments: [
                        ...draft.payments,
                        {
                          key: nextKey('p'),
                          date: draft.date,
                          amount: '',
                          rate: draft.currency === 'RUB' ? '1' : draft.rate,
                          category: 'invoice',
                          comment: '',
                        },
                      ],
                    })
                  }
                >
                  Добавить валютный платёж
                </button>
              </div>
              <div className="table-scroll">
                <table className="receipt-payments" data-testid="receipt-payments">
                  <thead>
                    <tr>
                      <th scope="col">Категория</th>
                      <th scope="col">Валютный платёж: дата</th>
                      <th scope="col" className="num">
                        Сумма, {draft.currency}
                      </th>
                      <th scope="col" className="num">
                        Курс, ₽
                      </th>
                      <th scope="col" className="num">
                        Сумма, ₽
                      </th>
                      <th scope="col">Комментарий</th>
                      <th scope="col" aria-label="Действия" />
                    </tr>
                  </thead>
                  <tbody>
                    {draft.payments.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="hint">
                          Валютных платежей нет — инвойс не закрыт.
                        </td>
                      </tr>
                    ) : (
                      draft.payments.map((row) => (
                        <tr key={row.key}>
                          <td>
                            <select
                              aria-label={`Категория платежа ${row.key}`}
                              value={row.category}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  payments: draft.payments.map((payment) =>
                                    payment.key === row.key
                                      ? {
                                          ...payment,
                                          category: event.target.value as PaymentCategory,
                                        }
                                      : payment,
                                  ),
                                })
                              }
                            >
                              <option value="invoice">Инвойс</option>
                              {/* Risk предлагаем только когда он есть в партии. */}
                              {hasRisk || row.category === 'risk' ? (
                                <option value="risk">Risk</option>
                              ) : null}
                            </select>
                          </td>
                          <td>
                            <input
                              type="date"
                              aria-label={`Дата платежа ${row.key}`}
                              value={row.date}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  payments: draft.payments.map((payment) =>
                                    payment.key === row.key
                                      ? { ...payment, date: event.target.value }
                                      : payment,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td className="num">
                            <input
                              className="cell"
                              aria-label={`Сумма платежа ${row.key}`}
                              value={row.amount}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  payments: draft.payments.map((payment) =>
                                    payment.key === row.key
                                      ? { ...payment, amount: event.target.value }
                                      : payment,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td className="num">
                            <input
                              className="cell"
                              aria-label={`Курс платежа ${row.key}`}
                              value={row.rate}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  payments: draft.payments.map((payment) =>
                                    payment.key === row.key
                                      ? { ...payment, rate: event.target.value }
                                      : payment,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td className="num" data-testid={`payment-rub-${row.key}`}>
                            {formatMoney(String(number(row.amount) * number(row.rate)))}
                            {row.date > iso(new Date()) ? (
                              <span className="badge"> план</span>
                            ) : null}
                          </td>
                          <td>
                            <input
                              aria-label={`Комментарий платежа ${row.key}`}
                              value={row.comment}
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  payments: draft.payments.map((payment) =>
                                    payment.key === row.key
                                      ? { ...payment, comment: event.target.value }
                                      : payment,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td>
                            <button
                              type="button"
                              className="mini"
                              onClick={() =>
                                setDraft({
                                  ...draft,
                                  payments: draft.payments.filter(
                                    (payment) => payment.key !== row.key,
                                  ),
                                })
                              }
                            >
                              Убрать
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              <div className="closing">
                <div className="closing-group">
                  <h3>Инвойс</h3>
                  <div className="closing-row">
                    <span>Оплачено</span>
                    <strong data-testid="receipt-paid">
                      {money(cost.invoice.paidCurrency)} {currency}
                    </strong>
                    <span className="muted">= {money(cost.invoice.paidRub)} ₽</span>
                  </div>
                  <div className="closing-row">
                    <span>Незакрытая часть</span>
                    <strong data-testid="receipt-remaining">
                      {money(cost.invoice.remaining)} {currency}
                    </strong>
                    <span className="muted">
                      {trim(draft.rate)
                        ? `по курсу ${formatRate(cost.invoice.rate)}`
                        : '— курс не задан'}
                    </span>
                  </div>
                  <div className="closing-row">
                    <span>План (ещё не наступило)</span>
                    <strong data-testid="receipt-planned">
                      {money(cost.invoice.plannedCurrency)} {currency}
                    </strong>
                    <span className="muted">= {money(cost.invoice.plannedRub)} ₽</span>
                  </div>
                  <div className="closing-row">
                    <span>Свободно к оплате</span>
                    <strong data-testid="receipt-limit">
                      {money(
                        Math.max(
                          0,
                          cost.invoice.total -
                            cost.invoice.paidCurrency -
                            cost.invoice.plannedCurrency,
                        ),
                      )}{' '}
                      {currency}
                    </strong>
                    <span className="muted">лимит платежей</span>
                  </div>
                </div>

                <div className="closing-group">
                  <h3>Risk</h3>
                  {hasRisk ? (
                    <>
                      <div className="closing-row">
                        <span>Оплачено</span>
                        <strong data-testid="receipt-risk-paid">
                          {money(cost.risk.paidCurrency)} {currency}
                        </strong>
                        <span className="muted">= {money(cost.risk.paidRub)} ₽</span>
                      </div>
                      <div className="closing-row">
                        <span>Незакрытая часть</span>
                        <strong data-testid="receipt-risk-remaining">
                          {money(cost.risk.remaining)} {currency}
                        </strong>
                        <span className="muted">по курсу {formatRate(cost.risk.rate)}</span>
                      </div>
                      <div className="closing-row">
                        <span>План (ещё не наступило)</span>
                        <strong data-testid="receipt-planned-risk">
                          {money(cost.risk.plannedCurrency)} {currency}
                        </strong>
                        <span className="muted">= {money(cost.risk.plannedRub)} ₽</span>
                      </div>
                      <div className="closing-row">
                        <span>Свободно к оплате</span>
                        <strong data-testid="receipt-risk-limit">
                          {money(
                            Math.max(
                              0,
                              cost.risk.total - cost.risk.paidCurrency - cost.risk.plannedCurrency,
                            ),
                          )}{' '}
                          {currency}
                        </strong>
                        <span className="muted">лимит платежей</span>
                      </div>
                    </>
                  ) : (
                    <p className="hint closed-empty">
                      Risk в партии нет — платежи этой категории не нужны.
                    </p>
                  )}
                </div>
              </div>

              {cost.limitInvoiceExceeded || cost.limitRiskExceeded ? (
                <p className="error" role="alert" data-testid="receipt-limit-error">
                  {cost.limitRiskExceeded
                    ? 'Сумма платежей категории Risk больше Risk партии.'
                    : 'Сумма валютных платежей больше инвойсной стоимости партии.'}{' '}
                  Уменьшите платёж или добавьте товары.
                </p>
              ) : null}
            </div>
          ) : null}

          {tab === 'customs' ? (
            <div
              className="doc-card"
              id="panel-customs"
              role="tabpanel"
              aria-labelledby="tab-customs"
            >
              <div className="doc-card-head">
                <h2 className="doc-card-title">Таможня</h2>
                <span className="doc-card-sub">
                  {cleared ? `пройдена ${ruDate(draft.customsDate)}` : 'не пройдена'}
                </span>
                <span className="spacer" />
                {cleared && mayCancelCustoms ? (
                  <button type="button" disabled={busy || dirty} onClick={() => void dropCustoms()}>
                    Отменить растаможку
                  </button>
                ) : null}
              </div>

              {cleared ? (
                <div className="customs-facts">
                  <div>
                    <span className="kpi-label">Дата растаможки</span>
                    <strong>{ruDate(draft.customsDate)}</strong>
                  </div>
                  <div>
                    <span className="kpi-label">Курс фиксации, ₽</span>
                    <strong>{trim(draft.customsRate) || '—'}</strong>
                  </div>
                  <div>
                    <span className="kpi-label">Пошлина, ₽</span>
                    <strong>{money(cost.dutyRub)}</strong>
                  </div>
                  <div>
                    <span className="kpi-label">НДС, ₽</span>
                    <strong>{money(cost.vatRub)}</strong>
                  </div>
                </div>
              ) : (
                <div className="customs-facts">
                  <div>
                    <span className="kpi-label">Пошлина сейчас</span>
                    <strong>{money(cost.dutyRub)} ₽</strong>
                  </div>
                  <div>
                    <span className="kpi-label">НДС сейчас</span>
                    <strong>{money(cost.vatRub)} ₽</strong>
                  </div>
                  <div>
                    <span className="kpi-label">Курс остатка</span>
                    <strong>{trim(draft.rate) || '—'}</strong>
                  </div>
                </div>
              )}

              <p className="hint doc-inline-hint">
                {cleared
                  ? 'Пошлина и НДС зафиксированы в рублях по курсу на дату растаможки и больше не пересчитываются. Строки партии изменить нельзя — сначала отмените растаможку.'
                  : 'Пока партия не растаможена, пошлина и НДС считаются в процентах от стоимости строки. При растаможке они зафиксируются в рублях по курсу на выбранную дату — курс и суммы можно поправить вручную.'}
              </p>
            </div>
          ) : null}

          {tab === 'cost' ? (
            <div className="doc-card" id="panel-cost" role="tabpanel" aria-labelledby="tab-cost">
              <div className="doc-card-head">
                <h2 className="doc-card-title">Из чего сложилась себестоимость</h2>
                <span className="doc-card-sub">все суммы в рублях</span>
                <span className="spacer" />
                <span className="doc-card-sub">средний курс {formatRate(cost.averageRate)}</span>
              </div>

              <div className="cost-summary">
                <div className="cost-total">
                  <span className="kpi-label">Себестоимость партии</span>
                  <strong data-testid="cost-total">{money(cost.total)} ₽</strong>
                  <span className="doc-card-sub">
                    {draft.items.length} поз. · оплачено{' '}
                    {money(cost.invoice.paidCurrency + cost.risk.paidCurrency)} {currency}
                  </span>
                </div>
                <div className="cost-bars">
                  <div className="cost-bar" data-testid="cost-bar">
                    {partsTotal > 0 ? (
                      <>
                        {invoiceRub > 0 ? (
                          <span
                            style={{ width: `${sharePct(invoiceRub)}%`, background: '#1f6feb' }}
                            title={`Инвойс ${money(invoiceRub)} ₽`}
                          />
                        ) : null}
                        {riskRub > 0 ? (
                          <span
                            style={{ width: `${sharePct(riskRub)}%`, background: '#6941c6' }}
                            title={`Risk ${money(riskRub)} ₽`}
                          />
                        ) : null}
                        {cost.dutyRub > 0 ? (
                          <span
                            style={{ width: `${sharePct(cost.dutyRub)}%`, background: '#0f766e' }}
                            title={`Пошлина ${money(cost.dutyRub)} ₽`}
                          />
                        ) : null}
                        {cost.vatRub > 0 ? (
                          <span
                            style={{ width: `${sharePct(cost.vatRub)}%`, background: '#b45309' }}
                            title={`НДС ${money(cost.vatRub)} ₽`}
                          />
                        ) : null}
                        {cost.expensesRub > 0 ? (
                          <span
                            style={{
                              width: `${sharePct(cost.expensesRub)}%`,
                              background: '#98a2b3',
                            }}
                            title={`Расходы ${money(cost.expensesRub)} ₽`}
                          />
                        ) : null}
                      </>
                    ) : null}
                  </div>
                  <div className="cost-legend">
                    <span className="cost-legend-item">
                      <i style={{ background: '#1f6feb' }} />
                      <span className="cost-legend-name">Инвойс</span>
                      <b>{money(invoiceRub)} ₽</b>
                      <small>{shareText(invoiceRub)} %</small>
                    </span>
                    <span className="cost-legend-item">
                      <i style={{ background: '#6941c6' }} />
                      <span className="cost-legend-name">Risk</span>
                      <b>{money(riskRub)} ₽</b>
                      <small>{shareText(riskRub)} %</small>
                    </span>
                    <span className="cost-legend-item">
                      <i style={{ background: '#0f766e' }} />
                      <span className="cost-legend-name">Пошлина</span>
                      <b>{money(cost.dutyRub)} ₽</b>
                      <small>{shareText(cost.dutyRub)} %</small>
                    </span>
                    <span className="cost-legend-item">
                      <i style={{ background: '#b45309' }} />
                      <span className="cost-legend-name">НДС</span>
                      <b>{money(cost.vatRub)} ₽</b>
                      <small>{shareText(cost.vatRub)} %</small>
                    </span>
                    <span className="cost-legend-item">
                      <i style={{ background: '#98a2b3' }} />
                      <span className="cost-legend-name">Расходы</span>
                      <b>{money(cost.expensesRub)} ₽</b>
                      <small>{shareText(cost.expensesRub)} %</small>
                    </span>
                  </div>
                </div>
              </div>

              <div className="table-scroll">
                <table className="cost-lines">
                  <thead>
                    <tr>
                      <th scope="col">Слагаемое</th>
                      <th scope="col">Как получилось</th>
                      <th scope="col" className="num">
                        Сумма, ₽
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Инвойс</td>
                      <td className="muted">
                        {money(cost.invoice.total)} {currency} × курс{' '}
                        {formatRate(cost.invoice.rate)}
                      </td>
                      <td className="num">{money(invoiceRub)}</td>
                    </tr>
                    {cost.risk.total > 0 ? (
                      <tr>
                        <td>Risk</td>
                        <td className="muted">
                          {money(cost.risk.total)} {currency} × курс {formatRate(cost.risk.rate)}
                        </td>
                        <td className="num">{money(riskRub)}</td>
                      </tr>
                    ) : null}
                    <tr>
                      <td>Пошлина</td>
                      <td className="muted">
                        {cleared ? 'зафиксирована при растаможке' : 'проценты по строкам'}
                      </td>
                      <td className="num">{money(cost.dutyRub)}</td>
                    </tr>
                    <tr>
                      <td>НДС</td>
                      <td className="muted">
                        {cleared ? 'зафиксирован при растаможке' : 'проценты по строкам'}
                      </td>
                      <td className="num">{money(cost.vatRub)}</td>
                    </tr>
                    <tr>
                      <td>Общие расходы</td>
                      <td className="muted">
                        {draft.expenses.length === 0
                          ? 'расходов нет'
                          : `${draft.expenses.length} шт. — делятся между строками`}
                      </td>
                      <td className="num">{money(cost.expensesRub)}</td>
                    </tr>
                    <tr className="total-row">
                      <td colSpan={2}>Себестоимость</td>
                      <td className="num">{money(cost.total)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>

        <footer className="doc-footer">
          <div className="doc-footer-total">
            <span className="kpi-label">Себестоимость</span>
            <strong>{money(cost.total)} ₽</strong>
          </div>
          <span className="doc-footer-note">
            Средний курс {formatRate(cost.averageRate)} · оплачено {money(paidRub)} ₽
          </span>
          <span className="spacer" />
          <button type="button" onClick={closeDocument}>
            Отмена
          </button>
          <button
            type="submit"
            className="primary"
            // Пока открыто окно растаможки, карточку не сохраняем: сначала подтвердите её.
            disabled={busy || locked || cost.limitInvoiceExceeded || cost.limitRiskExceeded}
          >
            Сохранить
          </button>
          {draft.id ? (
            <button type="button" disabled={busy || locked} onClick={() => void remove()}>
              Удалить
            </button>
          ) : null}
        </footer>

        {customs ? (
          <div className="modal-backdrop">
            <div
              className="customs-box modal"
              role="dialog"
              aria-modal="true"
              aria-label="Растаможка партии"
              data-testid="customs-box"
            >
              <h3 className="section-title">Растаможка: проверьте курс и суммы</h3>
              <div className="toolbar">
                <label className="field">
                  Дата растаможки
                  <input
                    type="date"
                    aria-label="Дата растаможки"
                    value={customs.date}
                    onChange={(event) => {
                      const day = event.target.value
                      setCustoms({ ...customs, date: day })
                      // Курс ЦБ на дату растаможки — сразу, без отдельного нажатия.
                      void loadCustomsRate(day)
                    }}
                  />
                </label>
                <label className="field">
                  Курс фиксации, ₽
                  <input
                    aria-label="Курс растаможки"
                    value={customs.rate}
                    onChange={(event) => changeCustomsRate(event.target.value)}
                  />
                </label>
                <label className="field">
                  Пошлина, ₽
                  <input
                    className="cell"
                    aria-label="Пошлина партии, ₽"
                    value={customs.duty}
                    onChange={(event) => setCustoms({ ...customs, duty: event.target.value })}
                  />
                </label>
                <label className="field">
                  НДС, ₽
                  <input
                    className="cell"
                    aria-label="НДС партии, ₽"
                    value={customs.vat}
                    onChange={(event) => setCustoms({ ...customs, vat: event.target.value })}
                  />
                </label>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void loadCustomsRate(customs.date)}
                  data-testid="customs-rate"
                >
                  Курс ЦБ на дату
                </button>
              </div>
              {customs.hint ? (
                <p className="hint" data-testid="customs-rate-hint">
                  {customs.hint}
                </p>
              ) : (
                <p className="hint">Курс и суммы можно исправить до подтверждения.</p>
              )}
              <p className="hint" data-testid="customs-total">
                Итог: пошлина{' '}
                <strong data-testid="customs-duty-total">
                  {formatMoney(customs.duty || '0')} ₽
                </strong>{' '}
                · НДС{' '}
                <strong data-testid="customs-vat-total">{formatMoney(customs.vat || '0')} ₽</strong>{' '}
                · всего{' '}
                <strong data-testid="customs-sum">
                  {formatMoney(String(number(customs.duty) + number(customs.vat)))} ₽
                </strong>
              </p>
              <p className="hint">
                Итог распределится по строкам пропорционально их пошлине: сумма строк в точности
                равна введённой. После подтверждения проценты в строках заменятся этими рублями.
              </p>
              <div className="toolbar">
                <button
                  type="button"
                  className="primary"
                  data-testid="customs-confirm"
                  disabled={busy || number(customs.rate) <= 0}
                  onClick={() => void submitCustoms()}
                >
                  Подтвердить растаможку
                </button>
                <button type="button" disabled={busy} onClick={() => setCustoms(null)}>
                  Отмена
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </form>
    </section>
  )
}
