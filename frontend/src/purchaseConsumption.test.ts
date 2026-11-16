import { describe, expect, it } from 'vitest'
import type { PurchasePlan, PurchasePlanPosition } from './api'
import { buildConsumption, type ConsumptionDraft } from './purchaseConsumption'

function position(overrides: Partial<PurchasePlanPosition> = {}): PurchasePlanPosition {
  return {
    product_id: 'fin-1',
    code: 'FIN-1',
    name: 'Смесь ореховая',
    unit: 'шт',
    total: '300.000',
    months: [
      { month: 1, quantity: '100.000' },
      { month: 2, quantity: '200.000' },
    ],
    decomposed: true,
    status: 'ok',
    changed: false,
    ...overrides,
  }
}

function plan(
  positions: PurchasePlanPosition[] = [position()],
  closedMonths: number[] = [],
): PurchasePlan {
  return { year: 2027, positions, closed_months: closedMonths } as unknown as PurchasePlan
}

function draft(overrides: Partial<ConsumptionDraft> = {}): ConsumptionDraft {
  return {
    key: 'row-1',
    salesProductId: 'fin-1',
    productId: 'raw-1',
    productCode: 'RAW-1',
    productName: 'Орех грецкий',
    countryName: 'Таиланд',
    norm: '1.5',
    quantity: '30.000',
    unit: 'кг',
    alternativeOfId: null,
    ...overrides,
  }
}

describe('buildConsumption', () => {
  it('считает потребность и раскладывает её по месяцам', () => {
    const [group] = buildConsumption(plan(), [draft()])
    expect(group).toBeDefined()
    if (!group) return
    const [line] = group.lines
    expect(line).toBeDefined()
    if (!line) return
    expect(line.norm).toBe(1.5)
    expect(line.need).toBe(450)
    expect(line.monthly).toHaveLength(12)
    expect(line.monthly[0]).toEqual({ month: 1, planned: 100, quantity: 150 })
    expect(line.monthly[1]).toEqual({ month: 2, planned: 200, quantity: 300 })
    expect(line.monthly[2]).toEqual({ month: 3, planned: 0, quantity: 0 })
  })

  it('объединяет продукцию одного сырья в одну группу', () => {
    const groups = buildConsumption(
      plan([position(), position({ product_id: 'fin-2', code: 'FIN-2', name: 'Нуга' })]),
      [draft(), draft({ key: 'row-2', salesProductId: 'fin-2' })],
    )
    expect(groups).toHaveLength(1)
    const [group] = groups
    expect(group?.products).toBe(2)
    expect(group?.lines.map((line) => line.name)).toEqual(['Нуга', 'Смесь ореховая'])
  })

  it('считает закрытый месяц по факту продаж', () => {
    const [group] = buildConsumption(
      plan([position({ fact_months: [{ month: 1, quantity: '80.000' }] })], [1]),
      [draft()],
    )
    const [line] = group?.lines ?? []
    // (80 + 200) × 1,5 = 420, а не 450 по плану января.
    expect(line?.need).toBe(420)
    expect(line?.monthly[0]).toEqual({ month: 1, planned: 80, quantity: 120 })
    expect(line?.monthly[1]).toEqual({ month: 2, planned: 200, quantity: 300 })
  })

  it('без нормы не выдумывает потребность и месяцы', () => {
    const [group] = buildConsumption(plan(), [draft({ norm: '' })])
    const [line] = group?.lines ?? []
    expect(line?.norm).toBeNull()
    expect(line?.need).toBeNull()
    expect(line?.monthly).toEqual([])
    expect(group?.missingNorm).toBe(1)
  })

  it('понимает норму с запятой и пропускает строку без сырья', () => {
    const groups = buildConsumption(plan(), [
      draft({ norm: '2,5' }),
      draft({ key: 'row-2', productId: '' }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]?.lines[0]?.need).toBe(750)
  })

  it('помечает альтернативу и группу из одних альтернатив', () => {
    const groups = buildConsumption(plan(), [draft({ alternativeOfId: 'main-1' })])
    expect(groups[0]?.alternativeOnly).toBe(true)
    expect(groups[0]?.lines[0]?.alternative).toBe(true)
  })

  it('основная строка и альтернатива в одной группе — группа не «только альтернатива»', () => {
    const groups = buildConsumption(plan(), [
      draft(),
      draft({ key: 'row-2', alternativeOfId: 'row-1' }),
    ])
    expect(groups[0]?.alternativeOnly).toBe(false)
    expect(groups[0]?.lines.filter((line) => line.alternative)).toHaveLength(1)
  })
})
