import { Fragment, useCallback, useEffect, useState } from 'react'
import {
  acknowledgePurchasePlanSource,
  approvePurchasePlan,
  type Country,
  createPurchasePlan,
  deletePurchasePlan,
  errorMessage,
  fetchCountries,
  fetchProducts,
  fetchPurchasePlans,
  formatDate,
  formatMoney,
  formatQuantity,
  isAdmin,
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
import { PageHelp } from './PageHelp'

const QTY_PATTERN = /^\d+(?:[.,]\d{1,3})?$/
const NORM_PATTERN = /^\d+(?:[.,]\d{1,4})?$/
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
  /** Основная строка для альтернативы; пусто у обычной строки. */
  alternativeOfId: string | null
  salesProductId: string
  productId: string
  productName: string
  countryId: string
  countryName: string
  deliveryDays: number
  quantity: string
  /** Норма расхода: единиц сырья на единицу позиции, пусто — не задана. */
  norm: string
  priceRub: string
  notes: string
  unit: string
  /** Поступило по связанным поступлениям и процент исполнения. */
  factQuantity: string
  factShare: string
  /** Факт по месяцам прихода: месяц → количество. */
  factMonths: { month: number; quantity: string }[]
}

type PreviewEntry = {
  month: number
  quantityMilli: number
  orderYear: number
  orderMonth: number
  overdue: boolean
}

/** Тот же расчёт, что на сервере: доли месяцев и месяц заказа от срока доставки. */
function splitPreview(
  annualMilli: number,
  position: PurchasePlanPosition | undefined,
  deliveryDays: number,
  planYear: number,
): PreviewEntry[] {
  if (!position || annualMilli <= 0) return []
  const shares = position.months
    .map((row) => ({ month: row.month, milli: toMilli(row.quantity) }))
    .filter((row) => row.milli > 0)
    .sort((left, right) => left.month - right.month)
  const total = shares.reduce((sum, row) => sum + row.milli, 0)
  if (total <= 0) return []

  const today = new Date()
  const shift = deliveryDays > 0 ? Math.ceil(deliveryDays / 30) : 0
  const result: PreviewEntry[] = []
  let remaining = annualMilli
  shares.forEach((share, index) => {
    const isLast = index === shares.length - 1
    let milli = isLast
      ? remaining
      : Math.min(Math.round((annualMilli * share.milli) / total), remaining)
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

/** Кг в истории изменений: всегда три знака и пробелы между тысячами. */
const KG_FORMAT = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
})

function formatKg(value: string | null): string {
  if (value === null) return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? KG_FORMAT.format(parsed) : value
}

/** Потребность по норме: продажи месяца × норма (тот же расчёт, что на сервере). */
function previewByNorm(
  norm: number,
  position: PurchasePlanPosition | undefined,
  deliveryDays: number,
  planYear: number,
): PreviewEntry[] {
  if (!position || !(norm > 0)) return []
  const today = new Date()
  const shift = deliveryDays > 0 ? Math.ceil(deliveryDays / 30) : 0
  const result: PreviewEntry[] = []
  for (const month of [...position.months].sort((left, right) => left.month - right.month)) {
    const sold = toMilli(month.quantity)
    if (sold <= 0) continue
    const milli = Math.round(sold * norm)
    if (milli <= 0) continue
    const orderIndex = planYear * 12 + month.month - 1 - shift
    const orderYear = Math.floor(orderIndex / 12)
    const orderMonth = (((orderIndex % 12) + 12) % 12) + 1
    result.push({
      month: month.month,
      quantityMilli: milli,
      orderYear,
      orderMonth,
      overdue:
        orderYear < today.getFullYear() ||
        (orderYear === today.getFullYear() && orderMonth < today.getMonth() + 1),
    })
  }
  return result
}

/** Как показывать график заказа: сводкой или кварталами. */
type ScheduleMode = 'summary' | 'quarters'

const SCHEDULE_MODES: { id: ScheduleMode; title: string }[] = [
  { id: 'summary', title: 'кратко' },
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

/** Сводка по сырью: строки плана с одним сырьём делят приходы и излишек. */
type GroupTotals = {
  rows: number
  positions: number
  /** Сколько альтернативных строк закрывают эту же потребность. */
  alternatives: number
  /** Сколько закрыли именно альтернативы. */
  alternativeUsed: number
  need: number
  fact: number
  covered: number
  remaining: number
  carry: number
  months: Set<number>
}

type Coverage = {
  byRow: Map<string, ScheduleRow[]>
  group: Map<string, GroupTotals>
  /** Расход альтернативы по месяцам: сколько её прихода ушло на основную потребность. */
  used: Map<string, { total: number; months: Map<number, number> }>
}

/** Строки с одним сырьём — один общий котёл; у новой строки без сырья свой. */
function groupKey(row: DraftRow): string {
  return row.productId ? `product:${row.productId}` : `row:${row.key}`
}

/** Поделить покрытие пропорционально потребности; остаток — большей доле. */
function allocateShare(needs: number[], covered: number): number[] {
  const total = needs.reduce((sum, need) => sum + need, 0)
  if (total <= 0 || covered <= 0) return needs.map(() => 0)
  const ratio = covered / total
  const parts = needs.map((need) => Math.min(Math.floor(ratio * need), need))
  let rest = covered - parts.reduce((sum, part) => sum + part, 0)
  const order = needs
    .map((need, index) => ({ index, left: ratio * need - Math.floor(ratio * need) }))
    .sort((left, right) => right.left - left.left || left.index - right.index)
  let cursor = 0
  while (rest > 0 && order.length > 0) {
    const target = order[cursor % order.length]
    if (target === undefined) break
    parts[target.index] = (parts[target.index] ?? 0) + 1
    rest -= 1
    cursor += 1
  }
  return parts
}

/** Тот же расчёт покрытия, что на сервере: сначала основное, затем альтернативы. */
function coverDrafts(
  drafts: DraftRow[],
  positions: PurchasePlanPosition[],
  planYear: number,
): Coverage {
  const byRow = new Map<string, ScheduleRow[]>()
  const group = new Map<string, GroupTotals>()
  const used = new Map<string, { total: number; months: Map<number, number> }>()

  const mains = drafts.filter((row) => row.alternativeOfId === null)
  const altsByMain = new Map<string, DraftRow[]>()
  for (const row of drafts) {
    if (row.alternativeOfId === null) continue
    const bucket = altsByMain.get(row.alternativeOfId) ?? []
    bucket.push(row)
    altsByMain.set(row.alternativeOfId, bucket)
  }

  const families = new Map<string, DraftRow[]>()
  for (const row of mains) {
    const key = groupKey(row)
    const bucket = families.get(key) ?? []
    bucket.push(row)
    families.set(key, bucket)
  }

  const today = new Date()
  const current = today.getFullYear() * 12 + today.getMonth()

  families.forEach((family, familyKey) => {
    const familyAlts = family.flatMap((row) => altsByMain.get(row.id ?? row.key) ?? [])
    const rows = [...family, ...familyAlts]
    const entries = new Map<string, PreviewEntry[]>()
    const fact = new Map<string, Map<number, number>>()
    const available = new Map<string, number>()
    for (const row of rows) {
      const position = positions.find((item) => item.product_id === row.salesProductId)
      entries.set(
        row.key,
        splitPreview(toMilli(row.quantity), position, row.deliveryDays, planYear),
      )
      const months = new Map<number, number>()
      for (const month of row.factMonths) {
        months.set(month.month, (months.get(month.month) ?? 0) + toMilli(month.quantity))
      }
      fact.set(row.key, months)
      available.set(row.key, 0)
      byRow.set(row.key, [])
    }
    for (const row of familyAlts) used.set(row.key, { total: 0, months: new Map() })

    const needMonths = new Set<number>()
    family.forEach((row) => {
      entries.get(row.key)?.forEach((entry) => {
        needMonths.add(entry.month)
      })
    })
    // Приход может прийти в месяц без потребности: он ждёт ближайшую потребность,
    // поэтому такие месяцы тоже участвуют в расчёте.
    const monthSet = new Set(needMonths)
    rows.forEach((row) => {
      fact.get(row.key)?.forEach((_quantity, month) => {
        monthSet.add(month)
      })
    })
    const months = [...monthSet].sort((left, right) => left - right)

    let coveredMilli = 0
    for (const month of months) {
      for (const row of rows) {
        available.set(row.key, (available.get(row.key) ?? 0) + (fact.get(row.key)?.get(month) ?? 0))
      }
      const participants = family
        .map((row) => ({ row, entry: entries.get(row.key)?.find((item) => item.month === month) }))
        .filter((item): item is { row: DraftRow; entry: PreviewEntry } => item.entry !== undefined)
      const needs = participants.map((item) => item.entry.quantityMilli)
      const needTotal = needs.reduce((sum, need) => sum + need, 0)

      // Сначала основное сырьё. Котёл общий: запас любой основной строки может
      // закрыть потребность другой, даже если у неё самой в этом месяце
      // потребности нет.
      const mainAvail = family.map((row) => available.get(row.key) ?? 0)
      const taken = Math.min(
        needTotal,
        mainAvail.reduce((sum, value) => sum + value, 0),
      )
      const spentMain = allocateShare(mainAvail, taken)
      family.forEach((row, index) => {
        available.set(row.key, (available.get(row.key) ?? 0) - (spentMain[index] ?? 0))
      })

      const shortfall = needTotal - taken
      const altAvail = familyAlts.map((row) => available.get(row.key) ?? 0)
      const altTaken = Math.min(
        shortfall,
        altAvail.reduce((sum, value) => sum + value, 0),
      )
      if (altTaken > 0) {
        const spentAlt = allocateShare(altAvail, altTaken)
        familyAlts.forEach((row, index) => {
          const part = spentAlt[index] ?? 0
          available.set(row.key, (available.get(row.key) ?? 0) - part)
          if (part > 0) {
            const entry = used.get(row.key)
            if (entry) {
              entry.months.set(month, (entry.months.get(month) ?? 0) + part)
              entry.total += part
            }
          }
        })
      }

      const covered = allocateShare(needs, taken + altTaken)
      const carry = [...available.values()].reduce((sum, value) => sum + value, 0) / 1000
      participants.forEach((item, index) => {
        const part = covered[index] ?? 0
        byRow.get(item.row.key)?.push({
          entry: item.entry,
          need: item.entry.quantityMilli / 1000,
          covered: part / 1000,
          remaining: (item.entry.quantityMilli - part) / 1000,
          carry,
          share: item.entry.quantityMilli > 0 ? (part / item.entry.quantityMilli) * 100 : 0,
          soon:
            !item.entry.overdue &&
            item.entry.orderYear * 12 + item.entry.orderMonth - 1 === current,
        })
      })
      coveredMilli += taken + altTaken
    }

    const needMilli = family.reduce((sum, row) => sum + toMilli(row.quantity), 0)
    const factMilli = rows.reduce(
      (sum, row) => sum + row.factMonths.reduce((acc, month) => acc + toMilli(month.quantity), 0),
      0,
    )
    const alternativeUsed = familyAlts.reduce(
      (sum, row) => sum + (used.get(row.key)?.total ?? 0),
      0,
    )
    const totals: GroupTotals = {
      rows: family.length,
      positions: new Set(family.map((row) => row.salesProductId)).size,
      alternatives: familyAlts.length,
      alternativeUsed: alternativeUsed / 1000,
      need: needMilli / 1000,
      fact: factMilli / 1000,
      covered: coveredMilli / 1000,
      remaining: Math.max(needMilli - coveredMilli, 0) / 1000,
      carry: [...available.values()].reduce((sum, value) => sum + value, 0) / 1000,
      months: monthSet,
    }
    group.set(familyKey, totals)
  })
  return { byRow, group, used }
}

function orderDate(row: ScheduleRow): string {
  return `01.${String(row.entry.orderMonth).padStart(2, '0')}.${row.entry.orderYear}`
}

function needMonth(row: ScheduleRow, year: number): string {
  return `${(MONTH_TITLES[row.entry.month - 1] ?? '').toLowerCase()} ${year}`
}

const QUARTER_TITLES = ['I квартал', 'II квартал', 'III квартал', 'IV квартал']

/** Месяцы графика одной строки — запасной вариант, когда сырьё у строки одно. */
function monthsOf(schedule: PreviewEntry[]): Set<number> {
  return new Set(schedule.map((entry) => entry.month))
}

/** Факт по месяцам, которых нет в графике сырья: показываем отдельной строкой. */
function extraFacts(row: DraftRow, months: Set<number>): string {
  const outside = row.factMonths.filter((month) => !months.has(month.month))
  if (outside.length === 0) return ''
  return `вне графика: ${outside
    .map((month) => `${monthShort(month.month)} ${formatQuantity(month.quantity)}`)
    .join(' · ')}`
}

/** Строка «по сырью»: приход общий, поэтому показываем котёл целиком. */
function GroupNote({ group, year, unit }: { group: GroupTotals; year: number; unit: string }) {
  const share = group.need > 0 ? (group.covered / group.need) * 100 : 0
  const rest =
    group.remaining > 0 ? `докупить ${formatQuantity(group.remaining.toFixed(3))} ${unit}` : ''
  const carry =
    group.carry > 0
      ? `излишек ${formatQuantity(group.carry.toFixed(3))} ${unit} на ${year + 1}`
      : ''
  const alternative =
    group.alternativeUsed > 0
      ? `в т. ч. альтернативой ${formatQuantity(group.alternativeUsed.toFixed(3))} ${unit}`
      : ''
  return (
    <span className="sched-group" data-testid="schedule-group">
      <span className="sched-group-line">
        по сырью ({group.positions} поз.
        {group.alternatives > 0 ? `, ${group.alternatives} альт.` : ''}): перекрыто{' '}
        {formatQuantity(group.covered.toFixed(3))} из {formatQuantity(group.need.toFixed(3))} {unit}{' '}
        ({formatQuantity(share.toFixed(1))} %)
      </span>
      <span className="sched-group-line">
        {[rest, carry, alternative].filter(Boolean).join(' · ')}
      </span>
    </span>
  )
}

/** Таблица месяцев: потребность, сколько нужно, к какому числу заказать и что пришло. */
function ScheduleTable({
  rows,
  year,
  extra,
  unit,
}: {
  rows: ScheduleRow[]
  year: number
  extra: string
  unit: string
}) {
  return (
    <table className="sched-table" data-testid="schedule-table">
      <thead>
        <tr>
          <th>Месяц потребности</th>
          <th>Нужно, {unit}</th>
          <th>Заказать к</th>
          <th>Перекрыто</th>
          <th>Докупить, {unit}</th>
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
                  title={`Перекрыто ${formatQuantity(row.covered.toFixed(3))} ${unit}`}
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

/** График заказа: сводка в строке или кварталы под ней — расчёт один. */
function ScheduleView({
  rows,
  mode,
  year,
  extra,
  unit,
  showCarry = true,
}: {
  rows: ScheduleRow[]
  mode: ScheduleMode
  year: number
  extra: string
  unit: string
  /** Излишек одной строки не показываем: по сырью он общий, его видно в сводке. */
  showCarry?: boolean
}) {
  const nearest = rows.find((row) => row.remaining > 0) ?? null
  const last = rows.length > 0 ? rows[rows.length - 1] : null
  const carry = last ? last.carry : 0
  const extraLine = extra ? <span className="month-fact extra">{extra}</span> : null

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
              <span className="q-sum">
                {formatQuantity(need.toFixed(3))} {unit}
              </span>
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
                    )} ${unit}`
                  : `перекрыто полностью (${formatQuantity(covered.toFixed(3))} ${unit})`}
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
          {formatQuantity(nearest.remaining.toFixed(3))} {unit}
          <span className="sched-need"> (потребность — {needMonth(nearest, year)})</span>
        </span>
      ) : (
        <span className="sched-done">Потребность закрыта до конца года</span>
      )}
      {showCarry && carry > 0 && last ? (
        <span className="sched-carry">
          излишек после {needMonth(last, year)} — {formatQuantity(carry.toFixed(3))} {unit},
          переносим на {year + 1} год
        </span>
      ) : null}
      {extraLine}
    </div>
  )
}

function draftsFromPlan(plan: PurchasePlan): DraftRow[] {
  return plan.items.map((item) => ({
    key: item.id,
    id: item.id,
    alternativeOfId: item.alternative_of_id,
    salesProductId: item.sales_product_id,
    productId: item.product_id,
    productName: item.product_name,
    countryId: item.country_id,
    countryName: item.country_name,
    deliveryDays: item.delivery_days,
    quantity: trimZeros(item.quantity),
    norm: item.norm === null || item.norm === undefined ? '' : trimZeros(item.norm),
    priceRub: item.price_rub === null ? '' : trimZeros(item.price_rub),
    notes: item.notes ?? '',
    unit: item.unit,
    factQuantity: item.fact_quantity,
    factShare: item.fact_share,
    factMonths: item.fact_months ?? [],
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
  /** У каждой позиции своя таблица: раскрытые строки помним по ключу. */
  const [openSchedule, setOpenSchedule] = useState<string[]>([])

  const toggleSchedule = (key: string) =>
    setOpenSchedule((current) =>
      current.includes(key) ? current.filter((row) => row !== key) : [...current, key],
    )
  const [plans, setPlans] = useState<PurchasePlan[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [countries, setCountries] = useState<Country[]>([])
  const [drafts, setDrafts] = useState<DraftRow[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showChanges, setShowChanges] = useState(false)
  const [flashId, setFlashId] = useState<string | null>(null)

  const plan = plans.find((row) => row.year === year) ?? null
  const isPurchaser = user.role === 'purchase_director' || user.role === 'import_manager'
  // Администратор (исполнительный директор) ведёт план наравне с закупщиками.
  const isEditor = isPurchaser || isAdmin(user)
  const isExecutive = user.role === 'executive_director'
  const yearEditable = (plan?.editable_months.length ?? 0) > 0
  const canEdit = plan !== null && plan.status === 'draft' && isEditor && yearEditable
  const canSubmit = canEdit && drafts.length > 0 && plan?.source.state !== 'changed'
  const canApprove = plan !== null && plan.status === 'on_review' && isExecutive
  const canReopen = plan !== null && plan.status === 'approved' && isExecutive
  const canDelete =
    plan !== null && plan.status === 'draft' && (user.role === 'purchase_director' || isAdmin(user))
  const sourceChanged = plan?.source.state === 'changed' || plan?.source.state === 'no_snapshot'
  const canRequestRevision =
    plan !== null &&
    plan.status === 'approved' &&
    isPurchaser &&
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
    fetchProducts({ kinds: ['raw'] })
      .then((rows) => setProducts(rows.filter((row) => row.is_active && row.kind === 'raw')))
      .catch(() => setProducts([]))
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
    // Альтернативы не отправляем вместе с основной: сервер повысит одну из них
    // до основной, чтобы потребность не исчезла вместе с убранным сырьём.
    setDrafts((current) => current.filter((row) => row.key !== key && row.alternativeOfId !== key))
  }

  const addRow = (position: PurchasePlanPosition) => {
    setDrafts((current) => [
      ...current,
      {
        key: `new-${position.product_id}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        id: null,
        alternativeOfId: null,
        salesProductId: position.product_id,
        productId: '',
        productName: '',
        countryId: '',
        countryName: '',
        deliveryDays: 30,
        quantity: '',
        norm: '',
        priceRub: '',
        notes: '',
        unit: '',
        factQuantity: '0',
        factShare: '0',
        factMonths: [],
      },
    ])
    setError(null)
  }

  const addAlternative = (main: DraftRow) => {
    if (main.id === null) return
    setDrafts((current) => [
      ...current,
      {
        key: `new-alt-${main.key}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        id: null,
        alternativeOfId: main.id,
        salesProductId: main.salesProductId,
        productId: '',
        productName: '',
        countryId: '',
        countryName: '',
        deliveryDays: 30,
        quantity: '',
        norm: '',
        priceRub: '',
        notes: '',
        unit: main.unit,
        factQuantity: '0',
        factShare: '0',
        factMonths: [],
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
      const norm = normalize(row.norm)
      if (norm !== '' && (!NORM_PATTERN.test(norm) || Number(norm) <= 0)) {
        setError(`Строка ${index + 1}: норма — число больше нуля (до 4 знаков)`)
        return null
      }
      const price = normalize(row.priceRub)
      if (price !== '' && !PRICE_PATTERN.test(price)) {
        setError(`Строка ${index + 1}: цена — неотрицательное число`)
        return null
      }
      items.push({
        id: row.id,
        alternative_of_id: row.alternativeOfId,
        sales_product_id: row.salesProductId,
        product_id: row.productId,
        country_id: row.countryId,
        quantity,
        norm: norm === '' ? null : norm,
        price_rub: price === '' ? null : price,
        notes: row.notes || null,
      })
    }
    return items
  }

  const save = () => {
    if (!plan) return
    const items = collectItems()
    if (items)
      void run(() => savePurchasePlanItems(plan.id, items, plan.updated_at), 'План сохранён')
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
    const items = collectItems()
    if (!items) return
    // Отправляем то, что на экране: сначала сохраняем строки, потом отправляем.
    // Иначе несохранённые правки молча терялись, а отправлялась старая версия.
    void run(async () => {
      await savePurchasePlanItems(plan.id, items, plan.updated_at)
      await submitPurchasePlan(plan.id)
    }, 'План отправлен на согласование')
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
  const coverage = coverDrafts(drafts, plan?.positions ?? [], plan?.year ?? year)

  return (
    <section>
      <header className="page-head">
        <h1>План закупок сырья</h1>
        <PageHelp>
          Годовой план строится из финально согласованного годового плана продаж. Позиция
          раскладывается на сырьё вручную: страна задаёт срок доставки, по нему считается месяц
          заказа. Утверждает исполнительный директор.
        </PageHelp>
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
        <div className="empty-state" data-testid="purchase-no-plan">
          <strong>На {year} год плана закупок сырья нет</strong>
          <span>
            {isEditor
              ? 'План создаётся на основании финально согласованного годового плана продаж за этот год.'
              : 'План создаёт директор по закупкам.'}
          </span>
        </div>
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

          {plan.notes ? (
            <p className="hint plan-notes" data-testid="plan-notes">
              {plan.notes}
            </p>
          ) : null}

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

          {plan.signals && plan.signals.length > 0 ? (
            <section className="signal-history" data-testid="signal-history">
              <h2 className="section-title">История изменений</h2>
              {plan.signals.map((signal) => (
                <div className="signal-block" key={signal.id}>
                  <p className="hint">
                    {formatDate(signal.created_at)} · {signal.reason ?? 'изменение плана'} ·{' '}
                    {signal.actor_name ?? '—'}
                  </p>
                  <div className="table-scroll">
                    <table className="signal-table">
                      <thead>
                        <tr>
                          <th scope="col">Позиция</th>
                          <th scope="col">Сырьё</th>
                          <th scope="col" className="num">
                            Было, кг
                          </th>
                          <th scope="col" className="num">
                            Стало, кг
                          </th>
                          <th scope="col" className="num">
                            Δ, кг
                          </th>
                          <th scope="col" className="num">
                            Ед.: план → факт
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {signal.lines.map((line) => (
                          <tr
                            key={`${signal.id}-${line.sales_product}-${line.product}-${line.alternative}`}
                          >
                            <td>{line.sales_product}</td>
                            <td>
                              {line.product}
                              {line.alternative ? ' (альтернатива)' : ''}
                            </td>
                            <td className="num">{formatKg(line.was_kg)}</td>
                            <td className="num">{formatKg(line.now_kg)}</td>
                            <td className="num">
                              {line.delta_kg ? `+${formatKg(line.delta_kg)}` : '—'}
                            </td>
                            <td className="num">
                              {formatKg(line.plan_units)} → {formatKg(line.fact_units)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </section>
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
            {isEditor && plan.status === 'approved' ? (
              <span className="status-chip" data-testid="plan-approved-chip">
                Утверждён
              </span>
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
                  <th scope="col">График заказа</th>
                  <th scope="col" aria-label="Действия" />
                </tr>
              </thead>
              {plan.positions.map((position) => {
                const rows = drafts.filter((row) => row.salesProductId === position.product_id)
                // Альтернатива показывается сразу под своей основной строкой.
                const ordered: DraftRow[] = []
                for (const row of rows.filter((item) => item.alternativeOfId === null)) {
                  ordered.push(row)
                  if (row.id !== null) {
                    ordered.push(...rows.filter((item) => item.alternativeOfId === row.id))
                  }
                }
                return (
                  <tbody key={position.product_id}>
                    <tr
                      className={`need-row${flashId === position.product_id ? ' flash' : ''}`}
                      id={`position-${position.product_id}`}
                      data-testid={`position-${position.code}`}
                    >
                      <td colSpan={7}>
                        <div className="need-head">
                          <span
                            className="need-total"
                            title="Итог по позиции плана продаж (готовая продукция)"
                          >
                            <span className="need-total-caption">итог позиции</span>
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
                        <td colSpan={7} className="hint" data-testid={`empty-${position.code}`}>
                          Сырьё не добавлено.
                        </td>
                      </tr>
                    ) : (
                      ordered.map((row, index) => {
                        const quantity = normalize(row.quantity)
                        const normText = normalize(row.norm)
                        const normValue = Number(normText)
                        const hasNorm =
                          normText !== '' && Number.isFinite(normValue) && normValue > 0
                        const schedule = hasNorm
                          ? previewByNorm(normValue, position, row.deliveryDays, plan.year)
                          : splitPreview(toMilli(quantity), position, row.deliveryDays, plan.year)
                        const needTotal = hasNorm ? Number(position.total) * normValue : 0
                        const planQuantity = Number(quantity)
                        const gap =
                          hasNorm && Number.isFinite(planQuantity) ? planQuantity - needTotal : 0
                        const price = normalize(row.priceRub)
                        const sum =
                          price !== '' && QTY_PATTERN.test(quantity)
                            ? Number(price) * Number(quantity)
                            : null
                        const label = `${position.code} ${index + 1}`
                        const isAlternative = row.alternativeOfId !== null
                        const alternativeUsed = (coverage.used.get(row.key)?.total ?? 0) / 1000
                        const group = coverage.group.get(groupKey(row))
                        const rowSchedule = coverage.byRow.get(row.key) ?? []
                        const grouped = (group?.rows ?? 1) > 1 || (group?.alternatives ?? 0) > 0
                        const expanded = openSchedule.includes(row.key)
                        // График «ниже» — сразу под своей строкой, а не в конце позиции.
                        const wideGrouped = (group?.rows ?? 1) > 1
                        // Таблица и кварталы — сразу под своей строкой, а не в конце позиции.
                        const showWide =
                          !isAlternative &&
                          schedule.length > 0 &&
                          (scheduleMode === 'quarters' || expanded)
                        const wideRow = showWide ? (
                          <tr className="schedule-wide">
                            <td colSpan={7}>
                              {scheduleMode === 'quarters' ? (
                                <>
                                  <div className="sched-wide-head">
                                    <b>{row.productName || 'Сырьё'}</b>
                                    {row.countryName ? ` · ${row.countryName}` : ''}
                                    {wideGrouped && group ? (
                                      <GroupNote
                                        group={group}
                                        year={plan.year}
                                        unit={row.unit || 'ед.'}
                                      />
                                    ) : null}
                                  </div>
                                  <ScheduleView
                                    rows={rowSchedule}
                                    mode="quarters"
                                    year={plan.year}
                                    extra={extraFacts(row, group?.months ?? monthsOf(schedule))}
                                    unit={row.unit || 'ед.'}
                                    showCarry={!wideGrouped}
                                  />
                                </>
                              ) : null}
                              {expanded ? (
                                <ScheduleTable
                                  rows={rowSchedule}
                                  year={plan.year}
                                  extra=""
                                  unit={row.unit || 'ед.'}
                                />
                              ) : null}
                            </td>
                          </tr>
                        ) : null
                        return (
                          <Fragment key={row.key}>
                            <tr
                              className={isAlternative ? 'alt-row' : undefined}
                              data-testid={`purchase-row-${row.key}`}
                            >
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
                                        unit: chosen?.unit ?? '',
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
                                {isAlternative ? (
                                  <span
                                    className="badge badge-alt"
                                    data-testid={`alt-badge-${row.key}`}
                                  >
                                    альтернатива
                                  </span>
                                ) : null}
                                {canEdit && !isAlternative && row.id ? (
                                  <button
                                    type="button"
                                    className="mini alt-add"
                                    aria-label={`Добавить альтернативу ${label}`}
                                    title="Альтернативное сырьё для этой строки: другой сорт, калибр или страна"
                                    onClick={() => addAlternative(row)}
                                  >
                                    + альтернатива
                                  </button>
                                ) : null}
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
                                  <>
                                    <input
                                      className="cell"
                                      aria-label={`Количество ${label}`}
                                      value={row.quantity}
                                      onChange={(event) =>
                                        updateRow(row.key, { quantity: event.target.value })
                                      }
                                    />
                                    <input
                                      className="cell norm-cell"
                                      aria-label={`Норма ${label}`}
                                      placeholder="норма"
                                      title="Норма расхода: единиц сырья на единицу позиции плана продаж"
                                      value={row.norm}
                                      onChange={(event) =>
                                        updateRow(row.key, { norm: event.target.value })
                                      }
                                    />
                                  </>
                                ) : (
                                  <>
                                    {formatQuantity(row.quantity)}
                                    {row.norm ? (
                                      <span className="norm-inline">
                                        норма {formatQuantity(row.norm)}
                                      </span>
                                    ) : null}
                                  </>
                                )}
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
                              <td>
                                {position.status === 'orphan' ? (
                                  '—'
                                ) : isAlternative ? (
                                  <span className="sched-summary" data-testid={`alt-${row.key}`}>
                                    <span className="sched-line">
                                      план {formatQuantity(row.quantity || '0')} · пришло{' '}
                                      {formatQuantity(row.factQuantity)}
                                      {alternativeUsed > 0
                                        ? ` · на покрытие ${formatQuantity(
                                            alternativeUsed.toFixed(3),
                                          )}`
                                        : ''}
                                    </span>
                                    {hasNorm ? (
                                      <span className="sched-line" data-testid={`need-${row.key}`}>
                                        потребность {formatQuantity(needTotal.toFixed(3))}{' '}
                                        {row.unit || 'ед.'} · {gap >= 0 ? 'запас' : 'дефицит'}{' '}
                                        {formatQuantity(Math.abs(gap).toFixed(3))}
                                      </span>
                                    ) : (
                                      <span className="hint">норма не задана</span>
                                    )}
                                    <span className="alt-note">
                                      закрывает потребность основной строки, когда основного сырья
                                      не хватает
                                    </span>
                                  </span>
                                ) : (
                                  <>
                                    {hasNorm ? (
                                      <span className="sched-line" data-testid={`need-${row.key}`}>
                                        потребность {formatQuantity(needTotal.toFixed(3))}{' '}
                                        {row.unit || 'ед.'} · {gap >= 0 ? 'запас' : 'дефицит'}{' '}
                                        {formatQuantity(Math.abs(gap).toFixed(3))}
                                      </span>
                                    ) : (
                                      <span className="hint">норма не задана</span>
                                    )}
                                    {scheduleMode === 'summary' ? (
                                      <ScheduleView
                                        rows={rowSchedule}
                                        mode="summary"
                                        year={plan.year}
                                        extra={extraFacts(row, group?.months ?? monthsOf(schedule))}
                                        unit={row.unit || 'ед.'}
                                        showCarry={!grouped}
                                      />
                                    ) : (
                                      <span className="hint sched-below">график ниже</span>
                                    )}
                                    {scheduleMode === 'summary' && grouped && group ? (
                                      <GroupNote
                                        group={group}
                                        year={plan.year}
                                        unit={row.unit || 'ед.'}
                                      />
                                    ) : null}
                                    <button
                                      type="button"
                                      className={
                                        openSchedule.includes(row.key)
                                          ? 'mini sched-toggle active'
                                          : 'mini sched-toggle'
                                      }
                                      aria-expanded={openSchedule.includes(row.key)}
                                      onClick={() => toggleSchedule(row.key)}
                                    >
                                      {openSchedule.includes(row.key)
                                        ? 'Скрыть таблицу'
                                        : 'Показать таблицей'}
                                    </button>
                                  </>
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
                            {wideRow}
                          </Fragment>
                        )
                      })
                    )}
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
