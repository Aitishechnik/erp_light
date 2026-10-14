import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  type Batch,
  type BatchIn,
  type Counterparty,
  createBatch,
  deleteBatch,
  errorMessage,
  fetchBatches,
  fetchCounterparties,
  fetchProducts,
  fetchRate,
  formatMoney,
  type Product,
  type Role,
  type SessionUser,
  updateBatch,
  uploadBatchItems,
} from './api'

/** Позиции из файла «Партия» грузят те же роли, что правят поступления. */
const ITEM_IMPORT_ROLES: Role[] = ['purchase_director', 'import_manager']

type ItemDraft = {
  key: string
  code: string
  quantity: string
  amount: string
}

type ExpenseDraft = {
  key: string
  date: string
  amount: string
  description: string
}

type PaymentDraft = {
  key: string
  date: string
  amount: string
  rate: string
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

/** Живой расчёт себестоимости: та же формула, что на сервере (оплаты пока нет). */
type LiveCost = {
  total: number
  unit: Record<string, number>
  itemTotal: Record<string, number>
  invoiceTotal: number
  paidCurrency: number
  paidRub: number
  rubPayments: number
  remaining: number
  plannedCurrency: number
  plannedRub: number
  plannedRubPayments: number
  paymentsTotal: number
  limitExceeded: boolean
  effectiveRate: number
}

/**
 * Живой расчёт себестоимости — та же формула, что на сервере:
 *   остаток = max(0, инвойс − валютные платежи)
 *   себестоимость = Σ(платёж × курс платежа) + руб. платежи + остаток × текущий курс
 * Позиции делят сумму пропорционально своей доле в инвойсе.
 */
function liveCost(draft: Draft): LiveCost {
  const today = iso(new Date())
  const invoiceTotal = draft.items.reduce((sum, item) => sum + number(item.amount), 0)

  // Платежи и расходы с будущей датой — план: показываем, но в расчёт не берём.
  let paidCurrency = 0
  let paidRub = 0
  let plannedCurrency = 0
  let plannedRub = 0
  let paymentsTotal = 0
  for (const row of draft.payments) {
    const amount = number(row.amount)
    const rub = amount * number(row.rate)
    paymentsTotal += amount
    if (row.date && row.date <= today) {
      paidCurrency += amount
      paidRub += rub
    } else {
      plannedCurrency += amount
      plannedRub += rub
    }
  }

  let rubPayments = 0
  let plannedRubPayments = 0
  for (const row of draft.expenses) {
    const amount = number(row.amount)
    if (row.date && row.date <= today) rubPayments += amount
    else plannedRubPayments += amount
  }

  const rate = draft.currency === 'RUB' ? 1 : number(draft.rate) || 1
  const remaining = Math.max(0, invoiceTotal - paidCurrency)
  const total = paidRub + rubPayments + remaining * rate

  const unit: Record<string, number> = {}
  const itemTotal: Record<string, number> = {}
  for (const item of draft.items) {
    const quantity = number(item.quantity)
    const share = invoiceTotal > 0 ? number(item.amount) / invoiceTotal : 0
    itemTotal[item.key] = invoiceTotal > 0 ? total * share : 0
    const rowTotal = itemTotal[item.key] ?? 0
    unit[item.key] = quantity > 0 && invoiceTotal > 0 ? rowTotal / quantity : 0
  }

  return {
    total,
    unit,
    itemTotal,
    invoiceTotal,
    paidCurrency,
    paidRub,
    rubPayments,
    remaining,
    plannedCurrency,
    plannedRub,
    plannedRubPayments,
    paymentsTotal,
    limitExceeded: paymentsTotal > invoiceTotal,
    effectiveRate: invoiceTotal > 0 ? total / invoiceTotal : 0,
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
    comment: batch.comment ?? '',
    items: batch.items.map((item, index) => ({
      key: `i${index}`,
      code: item.product_code,
      quantity: trim(item.quantity),
      amount: trim(item.total_invoice_currency),
    })),
    payments: batch.payments.map((payment, index) => ({
      key: `p${index}`,
      date: payment.payment_date,
      amount: trim(payment.amount_currency),
      rate: trim(payment.exchange_rate),
      comment: payment.comment ?? '',
    })),
    expenses: batch.expenses.map((expense, index) => ({
      key: `e${index}`,
      date: expense.expense_date,
      amount: trim(expense.amount_rub),
      description: expense.description,
    })),
    isDraft,
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
    comment: '',
    items: [{ key: 'i0', code: '', quantity: '', amount: '' }],
    payments: [],
    expenses: [],
    isDraft: false,
  }
}

export function ReceiptsPage({ user }: { user?: SessionUser }) {
  const today = iso(new Date())
  const [month, setMonth] = useState(today.slice(0, 7))
  const [batches, setBatches] = useState<Batch[]>([])
  const [day, setDay] = useState(today)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [suppliers, setSuppliers] = useState<Counterparty[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [rateHint, setRateHint] = useState<string | null>(null)
  const [itemsFile, setItemsFile] = useState<File | null>(null)
  const [itemsHint, setItemsHint] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const itemsInput = useRef<HTMLInputElement>(null)
  // Ключи новых строк: у загруженных строк ключи вида i0/p0/e0, поэтому у новых
  // префикс другой — иначе React получает два элемента с одинаковым ключом.
  const keyCounter = useRef(1)
  const nextKey = (prefix: string) => `${prefix}new${keyCounter.current++}`
  const mayLoadItems = !user || ITEM_IMPORT_ROLES.includes(user.role)

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
  const cost = draft ? liveCost(draft) : null

  const shiftMonth = (delta: number) => {
    const base = monthStart(month)
    base.setMonth(base.getMonth() + delta)
    const next = `${base.getFullYear()}-${String(base.getMonth() + 1).padStart(2, '0')}`
    setMonth(next)
    setDay(`${next}-01`)
  }

  const startCreate = (target = day) => {
    setRateHint(null)
    setError(null)
    setItemsFile(null)
    setItemsHint(null)
    setDraft(emptyDraft(target))
  }

  const startEdit = (batch: Batch) => {
    setRateHint(null)
    setError(null)
    setItemsFile(null)
    setItemsHint(null)
    setDraft(draftFrom(batch))
  }

  /**
   * Позиции из файла «Партия» (1С): в партию попадают товар и количество.
   * Суммы и себестоимость файл не несёт — их считает финансовая часть карточки.
   */
  const loadItems = async () => {
    if (!draft?.id || !itemsFile) return
    setBusy(true)
    setError(null)
    setItemsHint(null)
    try {
      const result = await uploadBatchItems(draft.id, itemsFile)
      setDraft(draftFrom(result.batch))
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

  const fillRate = async () => {
    if (!draft) return
    setRateHint(null)
    try {
      const rate = await fetchRate(draft.currency.trim().toUpperCase() || 'RUB', draft.date)
      setDraft({ ...draft, rate: rate.rate })
      setRateHint(
        rate.source === 'base'
          ? 'Рубль — курс 1'
          : `Курс ЦБ на ${draft.date}: ${rate.rate} ₽ за 1 ${rate.code}`,
      )
    } catch (err) {
      setRateHint(errorMessage(err))
    }
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!draft) return
    if (liveCost(draft).limitExceeded) {
      setError('Сумма валютных платежей больше стоимости товаров партии')
      return
    }
    const items = draft.items
      .filter((item) => item.code.trim() !== '' && number(item.quantity) > 0)
      .map((item) => ({
        product_code: item.code.trim(),
        quantity: item.quantity.replace(',', '.'),
        total_invoice_currency: (item.amount || '0').replace(',', '.'),
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
      total_invoice_value: null,
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
          comment: row.comment.trim() === '' ? null : row.comment.trim(),
        })),
      expenses: draft.expenses
        .filter((row) => number(row.amount) > 0)
        .map((row) => ({
          expense_date: row.date || null,
          amount_rub: row.amount.replace(',', '.'),
          description: row.description,
        })),
    }
    setBusy(true)
    setError(null)
    try {
      if (draft.id) {
        await updateBatch(draft.id, payload)
      } else {
        await createBatch(payload)
      }
      setDraft(null)
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
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

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
                          {/* У черновиков из 1С позиций ещё нет: нулевая себестоимость — не итог дня. */}
                          {total > 0 ? (
                            <span className="calendar-sum">{formatMoney(String(total))} ₽</span>
                          ) : (
                            <span className="calendar-sum" data-testid={`day-drafts-${cell.date}`}>
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
                  </td>
                  <td>{batch.supplier ?? '—'}</td>
                  <td>{batch.items.length}</td>
                  <td>{batch.currency}</td>
                  <td className="num">{isDraft ? '—' : trim(batch.finance.effective_rate)}</td>
                  <td className="num">
                    {isDraft ? '—' : formatMoney(batch.finance.final_cost_rub)}
                  </td>
                  <td>
                    <button type="button" className="mini" onClick={() => startEdit(batch)}>
                      Открыть
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {draft ? (
        <form className="receipt-form" onSubmit={submit} data-testid="receipt-form">
          <h2 className="section-title">
            {draft.id ? `Поступление ${draft.number}` : 'Новое поступление'}
          </h2>
          {draft.isDraft ? (
            <p className="hint" data-testid="draft-hint">
              Черновик из выгрузки 1С: заполнены номер, дата, поставщик и комментарий. Загрузите
              файл «Партия» из 1С или добавьте позиции вручную — и поступление станет обычным.
            </p>
          ) : null}
          <div className="toolbar">
            <label className="field">
              Номер
              <input
                aria-label="Номер поступления"
                value={draft.number}
                onChange={(event) => setDraft({ ...draft, number: event.target.value })}
                required
              />
            </label>
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
                onChange={(event) => setDraft({ ...draft, currency: event.target.value })}
              />
            </label>
            <label className="field">
              Курс для остатка, ₽
              <input
                aria-label="Курс"
                value={draft.rate}
                onChange={(event) => setDraft({ ...draft, rate: event.target.value })}
              />
            </label>
            <button type="button" onClick={() => void fillRate()}>
              Обновить курс ЦБ
            </button>
            <label className="field">
              Комментарий
              <textarea
                aria-label="Комментарий"
                rows={2}
                value={draft.comment}
                onChange={(event) => setDraft({ ...draft, comment: event.target.value })}
              />
            </label>
          </div>
          {rateHint ? <p className="hint">{rateHint}</p> : null}

          {draft.id && mayLoadItems ? (
            <div className="toolbar" data-testid="batch-items-import">
              <label className="field">
                Позиции из 1С (файл «Партия»)
                <input
                  ref={itemsInput}
                  type="file"
                  accept=".xlsx"
                  aria-label="Файл партии из 1С"
                  disabled={busy}
                  onChange={(event) => {
                    setItemsFile(event.target.files?.[0] ?? null)
                    setItemsHint(null)
                  }}
                />
              </label>
              <button type="button" disabled={busy || !itemsFile} onClick={() => void loadItems()}>
                {busy ? 'Загрузка…' : 'Загрузить позиции из 1С'}
              </button>
              <span className="hint">
                Из файла берутся товар и количество: суммы и себестоимость считает карточка.
              </span>
            </div>
          ) : null}
          {itemsHint ? (
            <p className="hint" data-testid="batch-items-hint">
              {itemsHint}
            </p>
          ) : null}

          <table className="receipt-items" data-testid="receipt-items">
            <thead>
              <tr>
                <th scope="col">Товар (код)</th>
                <th scope="col" className="num">
                  Количество
                </th>
                <th scope="col" className="num">
                  Сумма в валюте
                </th>
                <th scope="col" className="num">
                  Стоимость, ₽
                </th>
                <th scope="col" className="num">
                  Себестоимость ед., ₽
                </th>
                <th scope="col" aria-label="Действия" />
              </tr>
            </thead>
            <tbody>
              {draft.items.map((item) => {
                const product = products.find(
                  (row) => row.code.toLowerCase() === item.code.trim().toLowerCase(),
                )
                return (
                  <tr key={item.key}>
                    <td>
                      <input
                        aria-label={`Товар ${item.key}`}
                        list="receipt-products"
                        placeholder="код из 1С"
                        value={item.code}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            items: draft.items.map((row) =>
                              row.key === item.key ? { ...row, code: event.target.value } : row,
                            ),
                          })
                        }
                      />
                      {product ? <span className="unit"> {product.name}</span> : null}
                    </td>
                    <td className="num">
                      <input
                        className="cell"
                        aria-label={`Количество ${item.key}`}
                        value={item.quantity}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            items: draft.items.map((row) =>
                              row.key === item.key ? { ...row, quantity: event.target.value } : row,
                            ),
                          })
                        }
                      />
                    </td>
                    <td className="num">
                      <input
                        className="cell"
                        aria-label={`Сумма ${item.key}`}
                        value={item.amount}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            items: draft.items.map((row) =>
                              row.key === item.key ? { ...row, amount: event.target.value } : row,
                            ),
                          })
                        }
                      />
                    </td>
                    <td className="num" data-testid={`item-total-${item.key}`}>
                      {formatMoney(String(cost?.itemTotal[item.key] ?? 0))}
                    </td>
                    <td className="num" data-testid={`unit-cost-${item.key}`}>
                      {formatMoney(String(cost?.unit[item.key] ?? 0))}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="mini"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            items: draft.items.filter((row) => row.key !== item.key),
                          })
                        }
                      >
                        Убрать
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <datalist id="receipt-products">
            {products.map((product) => (
              <option key={product.id} value={product.code}>
                {product.name}
              </option>
            ))}
          </datalist>
          <div className="toolbar">
            <button
              type="button"
              onClick={() =>
                setDraft({
                  ...draft,
                  items: [
                    ...draft.items,
                    { key: nextKey('i'), code: '', quantity: '', amount: '' },
                  ],
                })
              }
            >
              Добавить строку
            </button>
          </div>

          <h2 className="section-title">Фин. инфо.</h2>

          <table className="receipt-payments" data-testid="receipt-payments">
            <thead>
              <tr>
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
                  <td colSpan={6} className="hint">
                    Валютных платежей нет — инвойс не закрыт.
                  </td>
                </tr>
              ) : (
                draft.payments.map((row) => (
                  <tr key={row.key}>
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
                      {row.date > iso(new Date()) ? <span className="badge"> план</span> : null}
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
                            payments: draft.payments.filter((payment) => payment.key !== row.key),
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
          <div className="toolbar">
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
                      comment: '',
                    },
                  ],
                })
              }
            >
              Добавить валютный платёж
            </button>
          </div>

          <table className="receipt-expenses" data-testid="receipt-expenses">
            <thead>
              <tr>
                <th scope="col">Руб. платёж</th>
                <th scope="col">Дата</th>
                <th scope="col" className="num">
                  Сумма, ₽
                </th>
                <th scope="col" aria-label="Действия" />
              </tr>
            </thead>
            <tbody>
              {draft.expenses.length === 0 ? (
                <tr>
                  <td colSpan={4} className="hint">
                    Рублёвых платежей нет.
                  </td>
                </tr>
              ) : (
                draft.expenses.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <div className="cell-with-badge">
                        <input
                          aria-label={`Расход ${row.key}`}
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
                        {row.date > iso(new Date()) ? <span className="badge"> план</span> : null}
                      </div>
                    </td>
                    <td>
                      <input
                        type="date"
                        aria-label={`Дата расхода ${row.key}`}
                        value={row.date}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            expenses: draft.expenses.map((expense) =>
                              expense.key === row.key
                                ? { ...expense, date: event.target.value }
                                : expense,
                            ),
                          })
                        }
                      />
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
                    <td>
                      <button
                        type="button"
                        className="mini"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            expenses: draft.expenses.filter((expense) => expense.key !== row.key),
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
          <div className="toolbar">
            <button
              type="button"
              onClick={() =>
                setDraft({
                  ...draft,
                  expenses: [
                    ...draft.expenses,
                    { key: nextKey('e'), date: draft.date, amount: '', description: 'Доставка' },
                  ],
                })
              }
            >
              Добавить руб. платёж
            </button>
          </div>

          <div className="toolbar">
            <span className="hint">
              Инвойс:{' '}
              <strong data-testid="receipt-invoice">
                {formatMoney(String(cost?.invoiceTotal ?? 0))}
              </strong>{' '}
              {draft.currency} · оплачено в валюте:{' '}
              <strong data-testid="receipt-paid">
                {formatMoney(String(cost?.paidCurrency ?? 0))}
              </strong>{' '}
              · оплачено ₽: <strong>{formatMoney(String(cost?.paidRub ?? 0))}</strong> · руб.
              платежи: <strong>{formatMoney(String(cost?.rubPayments ?? 0))}</strong>
            </span>
          </div>
          <div className="toolbar">
            <span className="hint">
              План (ещё не наступило):{' '}
              <strong data-testid="receipt-planned">
                {formatMoney(String(cost?.plannedCurrency ?? 0))} {draft.currency}
              </strong>{' '}
              = <strong>{formatMoney(String(cost?.plannedRub ?? 0))}</strong> ₽ по валютным платежам
              ·{' '}
              <strong data-testid="receipt-planned-rub">
                {formatMoney(String(cost?.plannedRubPayments ?? 0))}
              </strong>{' '}
              ₽ рублёвых
            </span>
            <span className="sep" />
            <span className="hint">
              Лимит платежей:{' '}
              <strong data-testid="receipt-limit">
                {formatMoney(
                  String(Math.max(0, (cost?.invoiceTotal ?? 0) - (cost?.paymentsTotal ?? 0))),
                )}{' '}
                {draft.currency}
              </strong>
            </span>
          </div>
          {cost?.limitExceeded ? (
            <p className="error" role="alert" data-testid="receipt-limit-error">
              Сумма валютных платежей ({formatMoney(String(cost.paymentsTotal))} {draft.currency})
              больше стоимости товаров партии ({formatMoney(String(cost.invoiceTotal))}{' '}
              {draft.currency}). Уменьшите платёж или добавьте товары.
            </p>
          ) : null}
          <div className="toolbar">
            <span className="hint">
              Незакрытая часть:{' '}
              <strong data-testid="receipt-remaining">
                {formatMoney(String(cost?.remaining ?? 0))} {draft.currency}
              </strong>{' '}
              {trim(draft.rate) ? (
                <>
                  по курсу <strong>{trim(draft.rate)}</strong> ={' '}
                  <strong>
                    {formatMoney(String((cost?.remaining ?? 0) * (number(draft.rate) || 1)))}
                  </strong>{' '}
                  ₽
                </>
              ) : (
                // У черновика из 1С курса ещё нет — не показываем выдуманный «курс 1».
                <>— курс не задан</>
              )}
            </span>
            <span className="sep" />
            <span className="hint">
              Средний курс партии:{' '}
              <strong data-testid="receipt-effective">
                {formatRate(cost?.effectiveRate ?? 0)}
              </strong>{' '}
              · себестоимость:{' '}
              <strong data-testid="receipt-total">{formatMoney(String(cost?.total ?? 0))} ₽</strong>
            </span>
          </div>

          <div className="toolbar">
            <button
              type="submit"
              className="primary"
              disabled={busy || (cost?.limitExceeded ?? false)}
            >
              Сохранить
            </button>
            <button type="button" disabled={busy} onClick={() => setDraft(null)}>
              Отмена
            </button>
            {draft.id ? (
              <button type="button" disabled={busy} onClick={() => void remove()}>
                Удалить
              </button>
            ) : null}
          </div>
        </form>
      ) : null}
    </section>
  )
}
