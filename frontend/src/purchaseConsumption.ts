import type { PurchasePlan, PurchasePlanPosition } from './api'

/**
 * Зеркальный вид плана закупок: расход сырья по готовой продукции.
 *
 * Строка плана закупок — это «позиция продаж × сырьё × страна» с нормой расхода.
 * Здесь те же строки перевёрнуты: сначала сырьё, под ним готовая продукция.
 * Потребность = план продаж позиции × норма; по закрытым месяцам берётся факт
 * продаж, как в самом плане. Считаем из черновика, поэтому цифры совпадают с
 * таблицей плана на экране, даже если правки ещё не сохранены.
 */

export type ConsumptionDraft = {
  key: string
  salesProductId: string
  productId: string
  productCode: string
  productName: string
  countryName: string
  /** Норма расхода: единиц сырья на единицу позиции, пусто — не задана. */
  norm: string
  /** Закупаемое количество, не влияет на потребность — только на план. */
  quantity: string
  unit: string
  alternativeOfId: string | null
}

export type ConsumptionMonth = {
  month: number
  /** Продажи позиции в месяце: по плану, в закрытом месяце — по факту. */
  planned: number
  /** Расход сырья в месяце: продажи × норма. */
  quantity: number
}

export type ConsumptionLine = {
  key: string
  code: string
  name: string
  /** Единица готовой продукции: в ней измеряется норма. */
  unit: string
  country: string
  norm: number | null
  /** Годовая потребность сырья; null, если норма не задана. */
  need: number | null
  monthly: ConsumptionMonth[]
  alternative: boolean
  orphan: boolean
}

export type ConsumptionGroup = {
  productId: string
  code: string
  name: string
  /** Единица сырья: в ней считается потребность. */
  unit: string
  lines: ConsumptionLine[]
  products: number
  missingNorm: number
  alternativeOnly: boolean
}

const MILLI = 1000

function round3(value: number): number {
  return Math.round(value * MILLI) / MILLI
}

function parseNumber(raw: string): number | null {
  const text = raw.trim().replace(',', '.')
  if (text === '') return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

/** Месяцы потребности: закрытые — по факту продаж, остальные — по плану. */
function plannedMonths(
  position: PurchasePlanPosition | undefined,
  closed: Set<number>,
): Map<number, number> {
  const result = new Map<number, number>()
  if (!position) return result
  const facts = new Map(
    (position.fact_months ?? []).map((row) => [row.month, Number(row.quantity)]),
  )
  for (const row of position.months) {
    const value = closed.has(row.month) ? (facts.get(row.month) ?? 0) : Number(row.quantity)
    result.set(row.month, Number.isFinite(value) ? value : 0)
  }
  return result
}

/** Все 12 месяцев: месяцы без продаж остаются в списке с нулём. */
function monthlyRows(planned: Map<number, number>, norm: number): ConsumptionMonth[] {
  const result: ConsumptionMonth[] = []
  for (let month = 1; month <= 12; month += 1) {
    const value = planned.get(month) ?? 0
    result.push({ month, planned: value, quantity: round3(value * norm) })
  }
  return result
}

/** Сводка по строкам группы: сколько позиций, у скольких нет нормы. */
export function summarizeLines(lines: ConsumptionLine[]): {
  products: number
  missingNorm: number
  alternativeOnly: boolean
} {
  return {
    products: new Set(lines.map((line) => `${line.code} · ${line.name}`)).size,
    missingNorm: lines.filter((line) => line.norm === null).length,
    alternativeOnly: lines.every((line) => line.alternative),
  }
}

export function buildConsumption(
  plan: PurchasePlan,
  drafts: ConsumptionDraft[],
): ConsumptionGroup[] {
  const closed = new Set(plan.closed_months ?? [])
  const positions = new Map(plan.positions.map((row) => [row.product_id, row]))
  const groups = new Map<string, ConsumptionGroup>()

  for (const draft of drafts) {
    if (draft.productId === '') continue
    const position = positions.get(draft.salesProductId)
    const planned = plannedMonths(position, closed)
    const planUnits = [...planned.values()].reduce((sum, value) => sum + value, 0)
    const parsed = parseNumber(draft.norm)
    const norm = parsed !== null && parsed > 0 ? parsed : null
    const need = norm === null ? null : round3(planUnits * norm)

    const line: ConsumptionLine = {
      key: draft.key,
      code: position?.code ?? '',
      name: position?.name ?? '',
      unit: position?.unit ?? '',
      country: draft.countryName,
      norm,
      need,
      monthly: norm === null ? [] : monthlyRows(planned, norm),
      alternative: draft.alternativeOfId !== null,
      orphan: position === undefined || position.status === 'orphan',
    }

    const group = groups.get(draft.productId)
    if (group) {
      group.lines.push(line)
    } else {
      groups.set(draft.productId, {
        productId: draft.productId,
        code: draft.productCode,
        name: draft.productName,
        unit: draft.unit,
        lines: [line],
        products: 0,
        missingNorm: 0,
        alternativeOnly: true,
      })
    }
  }

  const result = [...groups.values()]
  for (const group of result) {
    group.lines.sort(
      (left, right) =>
        left.name.localeCompare(right.name, 'ru') ||
        Number(left.alternative) - Number(right.alternative) ||
        left.country.localeCompare(right.country, 'ru'),
    )
    Object.assign(group, summarizeLines(group.lines))
  }
  result.sort(
    (left, right) =>
      left.name.localeCompare(right.name, 'ru') || left.code.localeCompare(right.code),
  )
  return result
}
