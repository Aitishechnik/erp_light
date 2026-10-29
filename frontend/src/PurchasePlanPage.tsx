import { useCallback, useEffect, useState } from 'react'
import {
  acknowledgePurchasePlanSource,
  approvePurchasePlan,
  type Counterparty,
  type Country,
  createPurchasePlan,
  deletePurchasePlan,
  errorMessage,
  fetchCounterparties,
  fetchCountries,
  fetchProducts,
  fetchPurchasePlans,
  formatDate,
  formatMoney,
  formatQuantity,
  MONTH_TITLES,
  type Product,
  type PurchasePlan,
  type PurchasePlanChange,
  type PurchasePlanItemIn,
  type PurchasePlanPosition,
  type PurchasePlanSourceEvent,
  rejectPurchasePlan,
  reopenPurchasePlan,
  requestPurchasePlanRevision,
  type SessionUser,
  savePurchasePlanItems,
  submitPurchasePlan,
} from './api'

const QTY_PATTERN = /^\d+(?:[.,]\d{1,3})?$/
const PRICE_PATTERN = /^\d+(?:[.,]\d{1,2})?$/

function normalize(raw: string): string {
  return raw.trim().replace(',', '.')
}

/** «100.000» → «100», «250.50» → «250.5»: в поле лишние нули не нужны. */
function trimZeros(raw: string): string {
  return raw.includes('.') ? raw.replace(/\.?0+$/, '') : raw
}

function toMilli(raw: string): number {
  return Math.round(Number(normalize(raw)) * 1000)
}

function monthShort(month: number): string {
  return (MONTH_TITLES[month - 1] ?? '').slice(0, 3).toLowerCase()
}

type DraftRow = {
  key: string
  /** Строка плана на сервере; пусто у новой. */
  id: string | null
  salesProductId: string
  productId: string
  productName: string
  countryId: string
  countryName: string
  deliveryDays: number
  quantity: string
  priceRub: string
  supplierId: string
  supplierName: string
  notes: string
  /** Поступило по связанным поступлениям и процент исполнения. */
  factQuantity: string
  factShare: string
  /** Факт по месяцам прихода: месяц → количество. */
  factMonths: { month: number; quantity: string }[]
  /** Приходы, которые участвуют в покрытии: пришедшие после снимка остатков. */
  coverageMonths: { month: number; quantity: string }[]
  /** Остаток сырья на складе по последнему отчёту 1С. */
  stockQuantity: string
  stockDate: string | null
  /** Остаток готовой продукции: закрывает часть потребности. */
  productStockQuantity: string
}

type PreviewEntry = {
  month: number
  quantityMilli: number
  orderYear: number
  orderMonth: number
  overdue: boolean
}

/** Тот же расчёт, что на сервере: доли месяцев, остаток готовой продукции и срок доставки. */
function splitPreview(
  annualMilli: number,
  position: PurchasePlanPosition | undefined,
  deliveryDays: number,
  planYear: number,
  productStockMilli = 0,
): PreviewEntry[] {
  if (!position || annualMilli <= 0) return []
  const sold = position.months
    .map((row) => ({ month: row.month, milli: toMilli(row.quantity) }))
    .filter((row) => row.milli > 0)
    .sort((left, right) => left.month - right.month)
  const total = sold.reduce((sum, row) => sum + row.milli, 0)
  if (total <= 0) return []

  // Готовая продукция на складе закрывает первые месяцы: сырьё нужно не на весь год.
  let shares = sold
  let buy = annualMilli
  const stock = Math.min(Math.max(productStockMilli, 0), total)
  if (stock > 0) {
    let left = stock
    shares = []
    for (const row of sold) {
      const deficit = row.milli - left
      if (deficit > 0) shares.push({ month: row.month, milli: deficit })
      left = Math.max(left - row.milli, 0)
    }
    if (shares.length === 0) return []
    buy = Math.round((annualMilli * (total - stock)) / total)
    if (buy <= 0) return []
  }
  const weight = shares.reduce((sum, row) => sum + row.milli, 0)
  if (weight <= 0) return []

  const today = new Date()
  const shift = deliveryDays > 0 ? Math.ceil(deliveryDays / 30) : 0
  const result: PreviewEntry[] = []
  let remaining = buy
  shares.forEach((share, index) => {
    const isLast = index === shares.length - 1
    let milli = isLast ? remaining : Math.min(Math.round((buy * share.milli) / weight), remaining)
    milli = Math.max(milli, 0)
    remaining -= milli
    if (milli <= 0) return
    const orderIndex = planYear * 12 + share.month - 1 - shift
    const orderYear = Math.floor(orderIndex / 12)
    const orderMonth = (((orderIndex % 12) + 12) % 12) + 1
    result.push({
      month: share.month,
      quantityMilli: milli,
      orderYear,
      orderMonth,
      overdue:
        orderYear < today.getFullYear() ||
        (orderYear === today.getFullYear() && orderMonth < today.getMonth() + 1),
    })
  })
  return result
}

/** Как показывать график заказа: сводкой, полосой по месяцам заказа или кварталами. */
type ScheduleMode = 'summary' | 'bars' | 'quarters'

const SCHEDULE_MODES: { id: ScheduleMode; title: string }[] = [
  { id: 'summary', title: 'кратко' },
  { id: 'bars', title: 'полосой' },
  { id: 'quarters', title: 'кварталы' },
]

type ScheduleRow = {
  entry: PreviewEntry
  need: number
  covered: number
  remaining: number
  carry: number
  /** Перекрыто, %: не больше 100 — перезатар показывать не нужно. */
  share: number
  /** Срок заказа — этот месяц, но ещё не прошёл. */
  soon: boolean
}

function scheduleRows(
  entries: PreviewEntry[],
  factMonths: { month: number; quantity: string }[],
  stockQuantity = '0',
): ScheduleRow[] {
  const today = new Date()
  const current = today.getFullYear() * 12 + today.getMonth()
  let available = toMilli(stockQuantity)
  return entries.map((entry) => {
    const factRow = factMonths.find((row) => row.month === entry.month)
    const needMilli = entry.quantityMilli
    available += factRow ? toMilli(factRow.quantity) : 0
    const coveredMilli = Math.min(needMilli, Math.max(available, 0))
    available -= coveredMilli
    return {
      entry,
      need: needMilli / 1000,
      covered: coveredMilli / 1000,
      remaining: (needMilli - coveredMilli) / 1000,
      carry: available / 1000,
      share: needMilli > 0 ? (coveredMilli / needMilli) * 100 : 0,
      soon: !entry.overdue && entry.orderYear * 12 + entry.orderMonth - 1 === current,
    }
  })
}

function orderDate(row: ScheduleRow): string {
  return `01.${String(row.entry.orderMonth).padStart(2, '0')}.${row.entry.orderYear}`
}

function needMonth(row: ScheduleRow, year: number): string {
  return `${(MONTH_TITLES[row.entry.month - 1] ?? '').toLowerCase()} ${year}`
}

const QUARTER_TITLES = ['I квартал', 'II квартал', 'III квартал', 'IV квартал']

/** Пояснения под графиком: что закрыл склад готовой продукции и что пришло вне графика. */
function extraFacts(row: DraftRow, schedule: PreviewEntry[]): string {
  const parts: string[] = []
  const need = schedule.reduce((sum, entry) => sum + entry.quantityMilli, 0)
  const annual = toMilli(row.quantity)
  if (Number(normalize(row.productStockQuantity) || 0) > 0 && annual > need) {
    parts.push(
      `склад готовой продукции закрывает ${formatQuantity(
        ((annual - need) / 1000).toFixed(3),
      )} кг сырья — заказывать ${formatQuantity((need / 1000).toFixed(3))}`,
    )
  }
  const outside = row.factMonths.filter(
    (month) => !schedule.some((entry) => entry.month === month.month),
  )
  if (outside.length > 0) {
    parts.push(
      `вне графика: ${outside
        .map((month) => `${monthShort(month.month)} ${formatQuantity(month.quantity)}`)
        .join(' · ')}`,
    )
  }
  return parts.join(' · ')
}

/** Таблица месяцев: потребность, сколько нужно, к какому числу заказать и что пришло. */
function ScheduleTable({
  rows,
  year,
  extra,
}: {
  rows: ScheduleRow[]
  year: number
  extra: string
}) {
  return (
    <table className="sched-table" data-testid="schedule-table">
      <thead>
        <tr>
          <th>Месяц потребности</th>
          <th>Нужно, кг</th>
          <th>Заказать к</th>
          <th>Перекрыто</th>
          <th>Докупить, кг</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.entry.month}
            className={row.entry.overdue ? 'overdue' : row.soon ? 'soon' : undefined}
          >
            <td>{needMonth(row, year)}</td>
            <td className="num">{formatQuantity(row.need.toFixed(3))}</td>
            <td>
              {orderDate(row)}
              {row.entry.overdue ? ' · просрочен' : ''}
            </td>
            <td>
              {row.covered > 0 ? (
                <span
                  className={row.share >= 100 ? 'cover-line done' : 'cover-line'}
                  title={`Перекрыто ${formatQuantity(row.covered.toFixed(3))} кг`}
                >
                  {formatQuantity(row.share.toFixed(1))} %
                </span>
              ) : (
                '—'
              )}
            </td>
            <td className="num">
              {row.remaining > 0 ? formatQuantity(row.remaining.toFixed(3)) : '—'}
            </td>
          </tr>
        ))}
      </tbody>
      {extra ? (
        <tfoot>
          <tr>
            <td colSpan={5} className="hint">
              {extra}
            </td>
          </tr>
        </tfoot>
      ) : null}
    </table>
  )
}

/** График заказа: один и тот же расчёт, три способа показать. */
function ScheduleView({
  rows,
  mode,
  expanded,
  onToggle,
  year,
  extra,
  wide = false,
  tableOnly = false,
}: {
  rows: ScheduleRow[]
  mode: ScheduleMode
  expanded: boolean
  onToggle: () => void
  year: number
  extra: string
  wide?: boolean
  tableOnly?: boolean
}) {
  const nearest = rows.find((row) => row.remaining > 0) ?? null
  const last = rows.length > 0 ? rows[rows.length - 1] : null
  const carry = last ? last.carry : 0
  const extraLine = extra ? <span className="month-fact extra">{extra}</span> : null

  if (mode === 'summary' && tableOnly) {
    return <ScheduleTable rows={rows} year={year} extra="" />
  }

  if (mode === 'bars') {
    const max = Math.max(...rows.map((row) => row.need), 1)
    const maxHeight = wide ? 96 : 56
    return (
      <div className="sched-bars-wrap">
        <div className="sched-bars" data-testid="schedule-bars">
          {rows.map((row) => {
            const height = Math.max(Math.round((row.need / max) * maxHeight), 3)
            const filled = Math.min(row.covered / Math.max(row.need, 1), 1) * height
            return (
              <span
                key={row.entry.month}
                className={
                  row.entry.overdue ? 'bar-col overdue' : row.soon ? 'bar-col soon' : 'bar-col'
                }
                title={`Потребность ${needMonth(row, year)}: ${formatQuantity(
                  row.need.toFixed(3),
                )} кг; заказ к ${orderDate(row)}${
                  row.covered > 0
                    ? `; перекрыто ${formatQuantity(row.covered.toFixed(3))} кг (${formatQuantity(
                        row.share.toFixed(1),
                      )} %)`
                    : ''
                }`}
              >
                <span className="bar-body" style={{ height }}>
                  <i style={{ height: filled }} />
                </span>
                <span className="bar-label">
                  {monthShort(row.entry.orderMonth)}
                  <i>{String(row.entry.orderYear).slice(2)}</i>
                </span>
              </span>
            )
          })}
        </div>
        <span className="sched-legend">
          месяцы заказа · тёмная часть столбика — перекрыто остатком и приходами
        </span>
        {extraLine}
      </div>
    )
  }

  if (mode === 'quarters') {
    return (
      <div className="sched-quarters" data-testid="schedule-quarters">
        {[1, 2, 3, 4].map((quarter, index) => {
          const group = rows.filter((row) => Math.ceil(row.entry.month / 3) === quarter)
          if (group.length === 0) return null
          const need = group.reduce((sum, row) => sum + row.need, 0)
          const covered = group.reduce((sum, row) => sum + row.covered, 0)
          const remaining = group.reduce((sum, row) => sum + row.remaining, 0)
          const first = group.reduce((best, row) =>
            row.entry.orderYear * 12 + row.entry.orderMonth <
            best.entry.orderYear * 12 + best.entry.orderMonth
              ? row
              : best,
          )
          return (
            <span className="q-card" key={quarter}>
              <span className="q-title">
                {QUARTER_TITLES[index]} {year}
              </span>
              <span className="q-sum">{formatQuantity(need.toFixed(3))} кг</span>
              <span
                className={
                  first.entry.overdue ? 'q-order overdue' : first.soon ? 'q-order soon' : 'q-order'
                }
              >
                заказ к {orderDate(first)}
              </span>
              {first.entry.overdue || first.soon ? (
                <span className="q-note">
                  {first.entry.overdue ? 'срок прошёл' : 'срок в этом месяце'}
                </span>
              ) : null}
              <span className="q-fact">
                {remaining > 0
                  ? `перекрыто ${formatQuantity(covered.toFixed(3))} · докупить ${formatQuantity(
                      remaining.toFixed(3),
                    )} кг`
                  : `перекрыто полностью (${formatQuantity(covered.toFixed(3))} кг)`}
              </span>
            </span>
          )
        })}
        {extraLine}
      </div>
    )
  }

  return (
    <div className="sched-summary" data-testid="schedule-summary">
      {nearest ? (
        <span className="sched-line">
          Ближайший заказ: <b>к {orderDate(nearest)}</b> —{' '}
          {formatQuantity(nearest.remaining.toFixed(3))} кг
          <span className="sched-need"> (потребность — {needMonth(nearest, year)})</span>
        </span>
      ) : (
        <span className="sched-done">Потребность закрыта до конца года</span>
      )}
      {carry > 0 && last ? (
        <span className="sched-carry">
          излишек после {needMonth(last, year)} — {formatQuantity(carry.toFixed(3))} кг, переносим
          на {year + 1} год
        </span>
      ) : null}
      <button type="button" className="mini" onClick={onToggle}>
        {expanded ? 'Скрыть график' : 'Весь график'}
      </button>
      {extraLine}
    </div>
  )
}

function draftsFromPlan(plan: PurchasePlan): DraftRow[] {
  return plan.items.map((item) => ({
    key: item.id,
    id: item.id,
    salesProductId: item.sales_product_id,
    productId: item.product_id,
    productName: item.product_name,
    countryId: item.country_id,
    countryName: item.country_name,
    deliveryDays: item.delivery_days,
    quantity: trimZeros(item.quantity),
    priceRub: item.price_rub === null ? '' : trimZeros(item.price_rub),
    supplierId: item.supplier_id ?? '',
    supplierName: item.supplier_name ?? '',
    notes: item.notes ?? '',
    factQuantity: item.fact_quantity,
    factShare: item.fact_share,
    factMonths: item.fact_months ?? [],
    coverageMonths: item.coverage_months ?? [],
    stockQuantity: item.stock_quantity ?? '0',
    stockDate: item.stock_date ?? null,
    productStockQuantity: item.product_stock_quantity ?? '0',
  }))
}

function changeLabel(change: PurchasePlanChange): string {
  if (change.kind === 'added') return 'новая позиция'
  if (change.kind === 'removed') return 'позиция убрана'
  const was = Number(change.was ?? 0)
  const now = Number(change.now ?? 0)
  const delta = now - was
  const sign = delta > 0 ? '+' : '−'
  return `${sign}${formatQuantity(Math.abs(delta).toFixed(3))}`
}

function ChangesTable({
  changes,
  onGo,
}: {
  changes: PurchasePlanChange[]
  onGo?: (productId: string) => void
}) {
  return (
    <div className="purchase-table">
      <table data-testid="source-changes">
        <thead>
          <tr>
            <th scope="col">Позиция</th>
            <th scope="col">Месяц</th>
            <th scope="col" className="num">
              Было
            </th>
            <th scope="col" className="num">
              Стало
            </th>
            <th scope="col">Что изменилось</th>
            <th scope="col" aria-label="Перейти" />
          </tr>
        </thead>
        <tbody>
          {changes.map((change) => (
            <tr key={`${change.product_id}-${change.month}-${change.kind}`}>
              <td>
                {change.code} · {change.name}
                <span className="unit">, {change.unit}</span>
              </td>
              <td>{MONTH_TITLES[change.month - 1]}</td>
              <td className="num">{change.was === null ? '—' : formatQuantity(change.was)}</td>
              <td className="num">{change.now === null ? '—' : formatQuantity(change.now)}</td>
              <td>{changeLabel(change)}</td>
              <td>
                {onGo ? (
                  <button type="button" className="mini" onClick={() => onGo(change.product_id)}>
                    Перейти
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function HistoryBlock({ events }: { events: PurchasePlanSourceEvent[] }) {
  if (events.length === 0) return null
  return (
    <details className="source-history" data-testid="source-history">
      <summary>История изменений плана продаж ({events.length})</summary>
      {events.map((event) => (
        <div key={event.id} className="source-history-entry">
          <p className="hint">
            {formatDate(event.acknowledged_at)} · принял: {event.acknowledged_by_name ?? '—'} ·
            изменений: {event.changes.length}
          </p>
          <ChangesTable changes={event.changes} />
        </div>
      ))}
    </details>
  )
}

export function PurchasePlanPage({ user, focus }: { user: SessionUser; focus?: string[] }) {
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(focus?.[0] ? Number(focus[0]) : thisYear)
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>('summary')
  const [openSchedule, setOpenSchedule] = useState<string[]>([])

  const toggleSchedule = (key: string) =>
    setOpenSchedule((current) =>
      current.includes(key) ? current.filter((row) => row !== key) : [...current, key],
    )
  const [plans, setPlans] = useState<PurchasePlan[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [suppliers, setSuppliers] = useState<Counterparty[]>([])
  const [countries, setCountries] = useState<Country[]>([])
  const [drafts, setDrafts] = useState<DraftRow[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showChanges, setShowChanges] = useState(false)
  const [flashId, setFlashId] = useState<string | null>(null)

  const plan = plans.find((row) => row.year === year) ?? null
  const isEditor = user.role === 'purchase_director' || user.role === 'import_manager'
  const isExecutive = user.role === 'executive_director'
  const yearEditable = (plan?.editable_months.length ?? 0) > 0
  const canEdit = plan !== null && plan.status === 'draft' && isEditor && yearEditable
  const canSubmit = canEdit && drafts.length > 0 && plan?.source.state !== 'changed'
  const canApprove = plan !== null && plan.status === 'on_review' && isExecutive
  const canReopen = plan !== null && plan.status === 'approved' && isExecutive
  const canDelete = plan !== null && plan.status === 'draft' && user.role === 'purchase_director'
  const sourceChanged = plan?.source.state === 'changed' || plan?.source.state === 'no_snapshot'
  const canRequestRevision =
    plan !== null &&
    plan.status === 'approved' &&
    isEditor &&
    sourceChanged &&
    plan.source.revision_requested_at === null
  const canAcknowledge = plan !== null && plan.status !== 'approved' && isEditor && sourceChanged

  const reload = useCallback(async () => {
    try {
      setPlans(await fetchPurchasePlans())
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void reload()
    fetchProducts()
      .then((rows) => setProducts(rows.filter((row) => row.is_active && row.kind === 'raw')))
      .catch(() => setProducts([]))
    fetchCounterparties()
      .then((rows) =>
        setSuppliers(
          rows.filter((row) => row.is_active && (row.is_local_supplier || row.is_import_supplier)),
        ),
      )
      .catch(() => setSuppliers([]))
    fetchCountries()
      .then(setCountries)
      .catch(() => setCountries([]))
  }, [reload])

  useEffect(() => {
    setDrafts(plan ? draftsFromPlan(plan) : [])
    setRejectReason('')
  }, [plan])

  const run = async (action: () => Promise<unknown>, _message: string) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const updateRow = (key: string, patch: Partial<DraftRow>) => {
    setDrafts((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  const removeRow = (key: string) => {
    setDrafts((current) => current.filter((row) => row.key !== key))
  }

  const addRow = (position: PurchasePlanPosition) => {
    setDrafts((current) => [
      ...current,
      {
        key: `new-${position.product_id}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        id: null,
        salesProductId: position.product_id,
        productId: '',
        productName: '',
        countryId: '',
        countryName: '',
        deliveryDays: 30,
        quantity: '',
        priceRub: '',
        supplierId: '',
        supplierName: '',
        notes: '',
        factQuantity: '0',
        factShare: '0',
        factMonths: [],
        coverageMonths: [],
        stockQuantity: '0',
        stockDate: null,
        productStockQuantity: '0',
      },
    ])
    setError(null)
  }

  const collectItems = (): PurchasePlanItemIn[] | null => {
    const items: PurchasePlanItemIn[] = []
    for (const [index, row] of drafts.entries()) {
      if (!row.productId) {
        setError(`Строка ${index + 1}: выберите сырьё`)
        return null
      }
      if (!row.countryId) {
        setError(`Строка ${index + 1}: выберите страну — от неё зависит срок доставки`)
        return null
      }
      const quantity = normalize(row.quantity)
      if (!QTY_PATTERN.test(quantity) || Number(quantity) <= 0) {
        setError(`Строка ${index + 1}: количество — число больше нуля`)
        return null
      }
      const price = normalize(row.priceRub)
      if (price !== '' && !PRICE_PATTERN.test(price)) {
        setError(`Строка ${index + 1}: цена — неотрицательное число`)
        return null
      }
      items.push({
        id: row.id,
        sales_product_id: row.salesProductId,
        product_id: row.productId,
        country_id: row.countryId,
        quantity,
        price_rub: price === '' ? null : price,
        supplier_id: row.supplierId || null,
        notes: row.notes || null,
      })
    }
    return items
  }

  const save = () => {
    if (!plan) return
    const items = collectItems()
    if (items) void run(() => savePurchasePlanItems(plan.id, items), 'План сохранён')
  }

  const submit = () => {
    if (!plan) return
    if (drafts.length === 0) {
      setError('Нельзя отправить пустой план: добавьте хотя бы одну строку')
      return
    }
    if (drafts.some((row) => row.priceRub.trim() === '')) {
      setError('Укажите цену у всех строк: без цены план не отправить')
      return
    }
    if (plan.source.state === 'changed') {
      setError('Сначала примите изменения плана продаж к сведению')
      return
    }
    void run(() => submitPurchasePlan(plan.id), 'План отправлен на согласование')
  }

  const goTo = (productId: string) => {
    const element = document.getElementById(`position-${productId}`)
    element?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    setFlashId(productId)
    window.setTimeout(() => setFlashId(null), 2000)
  }

  const totalAmount = drafts.reduce((sum, row) => {
    if (row.priceRub.trim() === '') return sum
    return sum + Number(normalize(row.priceRub) || 0) * Number(normalize(row.quantity) || 0)
  }, 0)

  const changedPositions = new Set((plan?.source.changes ?? []).map((row) => row.product_id))
  const source = plan?.source

  return (
    <section>
      <header className="page-head">
        <h1>План закупок сырья</h1>
        <p className="hint">
          Годовой план строится из финально согласованного годового плана продаж. Позиция
          раскладывается на сырьё вручную: страна задаёт срок доставки, по нему считается месяц
          заказа. Утверждает исполнительный директор.
        </p>
        <div className="toolbar">
          <button
            type="button"
            aria-label="Предыдущий год"
            disabled={busy}
            onClick={() => {
              setYear(year - 1)
            }}
          >
            ←
          </button>
          <strong data-testid="purchase-year">{year}</strong>
          <button
            type="button"
            aria-label="Следующий год"
            disabled={busy}
            onClick={() => {
              setYear(year + 1)
            }}
          >
            →
          </button>
          {plan === null && isEditor ? (
            <>
              <span className="sep" />
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const created = await createPurchasePlan(year)
                    setYear(created.year)
                  }, 'План создан')
                }
              >
                Создать план на {year}
              </button>
            </>
          ) : null}
        </div>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {plan === null ? (
        <p className="hint" data-testid="purchase-no-plan">
          На {year} год плана закупок сырья нет.
          {isEditor
            ? ' План создаётся на основании финально согласованного годового плана продаж за этот год.'
            : ' План создаёт директор по закупкам.'}
        </p>
      ) : (
        <>
          <div className="purchase-summary" data-testid="purchase-plan-card">
            <span>{plan.created_by_name}</span>
            <span className={`badge status-${plan.status}`} data-testid="purchase-status">
              {plan.status_title}
            </span>
            <span>позиций: {plan.positions.length}</span>
            <span>строк: {drafts.length}</span>
            <span className="total">сумма: {formatMoney(totalAmount.toFixed(2))} ₽</span>
            {plan.approved_by_name ? <span>утвердил: {plan.approved_by_name}</span> : null}
          </div>

          {source ? (
            <>
              {source.state === 'changed' || source.state === 'no_snapshot' ? (
                <div className="source-alert" data-testid="source-alert">
                  <div className="source-alert-head">
                    <strong>{source.title}</strong>
                    <span className="hint">
                      снимок: {formatDate(source.snapshot_at)} · годовой план:{' '}
                      {source.annual_status_title ?? '—'}
                    </span>
                  </div>
                  <p className="hint">
                    Затронуто позиций: {changedPositions.size}.{' '}
                    {plan.status === 'approved'
                      ? isExecutive
                        ? 'План утверждён: верните его в работу, чтобы директор по закупкам поправил строки сырья.'
                        : 'План утверждён: запросите пересмотр, чтобы вернуть его в работу и поправить строки сырья.'
                      : 'Проверьте строки сырья и примите изменения к сведению — после этого план можно отправлять на согласование.'}
                  </p>
                  <div className="toolbar">
                    {canRequestRevision ? (
                      <button
                        type="button"
                        className="primary"
                        disabled={busy}
                        data-testid="source-request-revision"
                        onClick={() =>
                          run(
                            () =>
                              requestPurchasePlanRevision(
                                plan.id,
                                rejectReason || 'план продаж пересмотрен',
                              ),
                            'Запрос на пересмотр отправлен',
                          )
                        }
                      >
                        Запросить пересмотр
                      </button>
                    ) : null}
                    {canAcknowledge ? (
                      <button
                        type="button"
                        className="primary"
                        disabled={busy}
                        data-testid="source-ack"
                        onClick={() =>
                          void run(
                            () => acknowledgePurchasePlanSource(plan.id),
                            'Изменения плана продаж приняты к сведению',
                          )
                        }
                      >
                        Принять к сведению
                      </button>
                    ) : null}
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setShowChanges(!showChanges)}
                    >
                      {showChanges ? 'Скрыть изменения' : 'Показать изменения'}
                    </button>
                  </div>
                  {showChanges ? <ChangesTable changes={source.changes} onGo={goTo} /> : null}
                </div>
              ) : (
                <div className="source-info" data-testid="source-info">
                  <strong>{source.title}</strong>
                  <span className="hint">
                    {source.state === 'ok'
                      ? `снимок от ${formatDate(source.snapshot_at)}`
                      : `годовой план: ${source.annual_status_title ?? 'не согласован'}`}
                  </span>
                </div>
              )}
              <HistoryBlock events={source.history} />
            </>
          ) : null}

          {source?.revision_requested_at ? (
            <p className="hint warn" data-testid="revision-requested">
              {isExecutive
                ? `Директор по закупкам просит пересмотреть план (${
                    source.revision_requested_by_name ?? '—'
                  }, ${formatDate(source.revision_requested_at)}). Верните план в работу, чтобы он
                  его поправил.`
                : `Запрос на пересмотр отправлен исполнительному директору (${formatDate(
                    source.revision_requested_at,
                  )}).`}
            </p>
          ) : null}

          <div className="toolbar">
            {canEdit ? (
              <button type="button" className="primary" disabled={busy} onClick={save}>
                Сохранить
              </button>
            ) : null}
            {canEdit ? (
              <button
                type="button"
                disabled={busy || !canSubmit}
                title={
                  plan.source.state === 'changed'
                    ? 'Сначала примите изменения плана продаж'
                    : undefined
                }
                onClick={submit}
              >
                Отправить на согласование
              </button>
            ) : null}
            {canApprove ? (
              <button
                type="button"
                className="primary"
                disabled={busy || plan.source.state === 'changed'}
                onClick={() => run(() => approvePurchasePlan(plan.id), 'План утверждён')}
              >
                Утвердить
              </button>
            ) : null}
            {canApprove || canReopen ? (
              <input
                aria-label="Причина"
                placeholder="Причина"
                value={rejectReason}
                onChange={(event) => setRejectReason(event.target.value)}
              />
            ) : null}
            {canApprove ? (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await rejectPurchasePlan(plan.id, rejectReason)
                    setRejectReason('')
                  }, 'План возвращён на доработку')
                }
              >
                Вернуть на доработку
              </button>
            ) : null}
            {canReopen ? (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await reopenPurchasePlan(plan.id, rejectReason)
                    setRejectReason('')
                  }, 'План возвращён в работу')
                }
              >
                Вернуть в работу
              </button>
            ) : null}
            {canDelete ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  if (confirm('Удалить план закупок сырья?')) {
                    void run(() => deletePurchasePlan(plan.id), 'План удалён')
                  }
                }}
              >
                Удалить
              </button>
            ) : null}
            {isExecutive && plan.status === 'draft' ? (
              <span className="hint">Просмотр: план ещё заполняет закупщик</span>
            ) : null}
            {isEditor && plan.status === 'approved' ? (
              <span className="hint">План утверждён — правки недоступны</span>
            ) : null}
          </div>

          <fieldset className="sched-switch">
            <legend className="sr-only">Вид графика заказа</legend>
            <span className="hint">График заказа:</span>
            {SCHEDULE_MODES.map((mode) => (
              <button
                key={mode.id}
                type="button"
                className={scheduleMode === mode.id ? 'mini active' : 'mini'}
                aria-pressed={scheduleMode === mode.id}
                onClick={() => setScheduleMode(mode.id)}
              >
                {mode.title}
              </button>
            ))}
          </fieldset>

          <div className="purchase-table">
            <table className="plan-grid" data-testid="purchase-table">
              <thead>
                <tr>
                  <th scope="col">Сырьё</th>
                  <th scope="col">Страна</th>
                  <th scope="col" className="num">
                    Кол-во (год)
                  </th>
                  <th scope="col" className="num">
                    Цена, ₽
                  </th>
                  <th scope="col" className="num">
                    Сумма, ₽
                  </th>
                  <th scope="col">Поставщик</th>
                  <th scope="col">График заказа</th>
                  <th scope="col" aria-label="Действия" />
                </tr>
              </thead>
              {plan.positions.map((position) => {
                const rows = drafts.filter((row) => row.salesProductId === position.product_id)
                return (
                  <tbody key={position.product_id}>
                    <tr
                      className={`need-row${flashId === position.product_id ? ' flash' : ''}`}
                      id={`position-${position.product_id}`}
                      data-testid={`position-${position.code}`}
                    >
                      <td colSpan={8}>
                        <div className="need-head">
                          <span className="need-total">
                            {formatQuantity(position.total)}
                            <small>{position.unit}</small>
                          </span>
                          <span className="need-title-block">
                            <span className="need-title">
                              {position.code} · {position.name}
                            </span>
                          </span>
                          {position.changed ? (
                            <span className="badge need-changed">изменено</span>
                          ) : null}
                          {position.status === 'added' ? (
                            <span className="badge need-added">новая позиция</span>
                          ) : null}
                          {position.status === 'removed' ? (
                            <span className="badge need-removed">
                              позиции больше нет в плане продаж
                            </span>
                          ) : null}
                          {position.status === 'orphan' ? (
                            <span className="badge need-removed">вне плана продаж</span>
                          ) : null}
                          <span className={position.decomposed ? 'need-state ok' : 'need-state'}>
                            {position.decomposed ? 'разложено' : 'не разложено'}
                          </span>
                          {canEdit ? (
                            <button
                              type="button"
                              className="mini"
                              aria-label={`Добавить сырьё ${position.code}`}
                              onClick={() => addRow(position)}
                            >
                              + Добавить сырьё
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                    {rows.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="hint" data-testid={`empty-${position.code}`}>
                          Сырьё не добавлено.
                        </td>
                      </tr>
                    ) : (
                      rows.map((row, index) => {
                        const supplier = suppliers.find((item) => item.id === row.supplierId)
                        const schedule = splitPreview(
                          toMilli(row.quantity),
                          position,
                          row.deliveryDays,
                          plan.year,
                          toMilli(row.productStockQuantity),
                        )
                        const price = normalize(row.priceRub)
                        const quantity = normalize(row.quantity)
                        const sum =
                          price !== '' && QTY_PATTERN.test(quantity)
                            ? Number(price) * Number(quantity)
                            : null
                        const label = `${position.code} ${index + 1}`
                        return (
                          <tr key={row.key} data-testid={`purchase-row-${row.key}`}>
                            <td>
                              {canEdit ? (
                                <select
                                  className="plan-select"
                                  aria-label={`Сырьё ${label}`}
                                  title={row.productName || undefined}
                                  value={row.productId}
                                  onChange={(event) => {
                                    const chosen = products.find(
                                      (item) => item.id === event.target.value,
                                    )
                                    updateRow(row.key, {
                                      productId: event.target.value,
                                      productName: chosen?.name ?? '',
                                    })
                                  }}
                                >
                                  <option value="">— сырьё —</option>
                                  {row.productId &&
                                  !products.some((item) => item.id === row.productId) ? (
                                    <option value={row.productId}>
                                      {row.productName} (отключён)
                                    </option>
                                  ) : null}
                                  {products.map((product) => (
                                    <option key={product.id} value={product.id}>
                                      {product.code} · {product.name} ({product.unit})
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                row.productName
                              )}
                            </td>
                            <td>
                              {canEdit ? (
                                <select
                                  aria-label={`Страна ${label}`}
                                  value={row.countryId}
                                  onChange={(event) => {
                                    const chosen = countries.find(
                                      (item) => item.id === event.target.value,
                                    )
                                    updateRow(row.key, {
                                      countryId: event.target.value,
                                      countryName: chosen?.name ?? '',
                                      deliveryDays: chosen?.delivery_days ?? 30,
                                    })
                                  }}
                                >
                                  <option value="">— страна —</option>
                                  {row.countryId &&
                                  !countries.some((item) => item.id === row.countryId) ? (
                                    <option value={row.countryId}>
                                      {row.countryName} (отключена)
                                    </option>
                                  ) : null}
                                  {countries.map((item) => (
                                    <option key={item.id} value={item.id}>
                                      {item.name} · {item.delivery_days} дн
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <>
                                  {row.countryName || '—'}
                                  {row.deliveryDays ? (
                                    <span className="unit"> · {row.deliveryDays} дн</span>
                                  ) : null}
                                </>
                              )}
                            </td>
                            <td className="num">
                              {canEdit ? (
                                <input
                                  className="cell"
                                  aria-label={`Количество ${label}`}
                                  value={row.quantity}
                                  onChange={(event) =>
                                    updateRow(row.key, { quantity: event.target.value })
                                  }
                                />
                              ) : (
                                formatQuantity(row.quantity)
                              )}
                              {row.id ? (
                                <span
                                  className="fact-line"
                                  data-testid={`fact-${row.key}`}
                                  title="Остаток по последнему отчёту 1С и приход по связанным поступлениям"
                                >
                                  {Number(row.productStockQuantity) > 0 ? (
                                    <>готовой {formatQuantity(row.productStockQuantity)} · </>
                                  ) : null}
                                  {Number(row.stockQuantity) > 0 ? (
                                    <>
                                      на складе {formatQuantity(row.stockQuantity)}
                                      {row.stockDate
                                        ? ` · ${formatDate(row.stockDate).slice(0, 5)}`
                                        : ''}{' '}
                                      ·{' '}
                                    </>
                                  ) : null}
                                  пришло {formatQuantity(row.factQuantity)}
                                </span>
                              ) : null}
                            </td>
                            <td className="num">
                              {canEdit ? (
                                <input
                                  className="cell"
                                  aria-label={`Цена ${label}`}
                                  value={row.priceRub}
                                  onChange={(event) =>
                                    updateRow(row.key, { priceRub: event.target.value })
                                  }
                                />
                              ) : (
                                formatMoney(row.priceRub || null)
                              )}
                            </td>
                            <td className="num">
                              {sum === null ? '—' : formatMoney(sum.toFixed(2))}
                            </td>
                            <td
                              className="supplier-cell purchase-supplier"
                              title={row.supplierName || undefined}
                            >
                              {canEdit ? (
                                <select
                                  className="plan-select"
                                  aria-label={`Поставщик ${label}`}
                                  title={row.supplierName || undefined}
                                  value={row.supplierId}
                                  onChange={(event) => {
                                    const chosen = suppliers.find(
                                      (item) => item.id === event.target.value,
                                    )
                                    updateRow(row.key, {
                                      supplierId: event.target.value,
                                      supplierName: chosen?.name ?? '',
                                    })
                                  }}
                                >
                                  <option value="">—</option>
                                  {row.supplierId &&
                                  !suppliers.some((item) => item.id === row.supplierId) ? (
                                    <option value={row.supplierId}>{row.supplierName}</option>
                                  ) : null}
                                  {suppliers.map((item) => (
                                    <option key={item.id} value={item.id}>
                                      {item.name}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                row.supplierName || supplier?.name || '—'
                              )}
                            </td>
                            <td>
                              {position.status === 'orphan' ? (
                                '—'
                              ) : schedule.length === 0 ? (
                                <span className="hint" data-testid={`no-raw-${row.key}`}>
                                  сырьё не нужно: потребность закрыта готовой продукцией
                                  {Number(row.productStockQuantity) > 0
                                    ? ` (${formatQuantity(row.productStockQuantity)} кг)`
                                    : ''}
                                </span>
                              ) : scheduleMode === 'summary' ? (
                                <ScheduleView
                                  rows={scheduleRows(
                                    schedule,
                                    row.coverageMonths,
                                    row.stockQuantity,
                                  )}
                                  mode="summary"
                                  expanded={openSchedule.includes(row.key)}
                                  onToggle={() => toggleSchedule(row.key)}
                                  year={plan.year}
                                  extra={extraFacts(row, schedule)}
                                />
                              ) : (
                                <span className="hint">график ниже</span>
                              )}
                            </td>
                            <td>
                              {canEdit ? (
                                <button
                                  type="button"
                                  className="row-remove"
                                  aria-label={`Убрать ${label}`}
                                  title="Убрать строку"
                                  onClick={() => removeRow(row.key)}
                                >
                                  ×
                                </button>
                              ) : null}
                            </td>
                          </tr>
                        )
                      })
                    )}
                    {rows.map((row) => {
                      const schedule = splitPreview(
                        toMilli(row.quantity),
                        position,
                        row.deliveryDays,
                        plan.year,
                        toMilli(row.productStockQuantity),
                      )
                      const expanded = openSchedule.includes(row.key)
                      if (schedule.length === 0) return null
                      if (scheduleMode === 'summary' && !expanded) return null
                      return (
                        <tr key={`${row.key}-schedule`} className="schedule-wide">
                          <td colSpan={8}>
                            <div className="sched-wide-head">
                              <b>{row.productName || 'Сырьё'}</b>
                              {row.countryName ? ` · ${row.countryName}` : ''}
                              {scheduleMode === 'summary' ? null : (
                                <button
                                  type="button"
                                  className="mini"
                                  onClick={() => toggleSchedule(row.key)}
                                >
                                  {expanded ? 'Скрыть таблицу' : 'Показать таблицей'}
                                </button>
                              )}
                            </div>
                            <ScheduleView
                              rows={scheduleRows(schedule, row.coverageMonths, row.stockQuantity)}
                              mode={scheduleMode}
                              wide
                              tableOnly
                              expanded={expanded}
                              onToggle={() => toggleSchedule(row.key)}
                              year={plan.year}
                              extra={extraFacts(row, schedule)}
                            />
                            {scheduleMode !== 'summary' && expanded ? (
                              <ScheduleTable
                                rows={scheduleRows(schedule, row.coverageMonths, row.stockQuantity)}
                                year={plan.year}
                                extra=""
                              />
                            ) : null}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                )
              })}
            </table>
          </div>
        </>
      )}
    </section>
  )
}
