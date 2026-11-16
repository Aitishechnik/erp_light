import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PurchasePlan, PurchasePlanPosition } from './api'
import { PurchaseConsumptionView } from './PurchaseConsumptionView'
import type { ConsumptionDraft } from './purchaseConsumption'

const MIX: PurchasePlanPosition = {
  product_id: 'fin-1',
  code: 'FIN-1',
  name: 'Смесь ореховая, 100 гр',
  unit: 'шт',
  total: '300.000',
  months: [
    { month: 1, quantity: '100.000' },
    { month: 2, quantity: '200.000' },
  ],
  decomposed: true,
  status: 'ok',
  changed: false,
}

const NOUGA: PurchasePlanPosition = {
  product_id: 'fin-2',
  code: 'FIN-2',
  name: 'Нуга ореховая',
  unit: 'шт',
  total: '50.000',
  months: [{ month: 3, quantity: '50.000' }],
  decomposed: true,
  status: 'ok',
  changed: false,
}

function plan(positions: PurchasePlanPosition[] = [MIX, NOUGA]): PurchasePlan {
  return {
    id: 'plan-1',
    year: 2027,
    positions,
    closed_months: [],
  } as unknown as PurchasePlan
}

function draft(overrides: Partial<ConsumptionDraft> = {}): ConsumptionDraft {
  return {
    key: 'row-1',
    salesProductId: 'fin-1',
    productId: 'raw-1',
    productCode: 'RAW-1',
    productName: 'Орех грецкий, вес',
    countryName: 'Таиланд',
    norm: '1.5',
    quantity: '30.000',
    unit: 'кг',
    alternativeOfId: null,
    ...overrides,
  }
}

const DRAFTS: ConsumptionDraft[] = [
  draft(),
  draft({
    key: 'row-2',
    salesProductId: 'fin-2',
    norm: '2',
    countryName: 'Китай',
  }),
  draft({
    key: 'row-3',
    productId: 'raw-2',
    productCode: 'RAW-2',
    productName: 'Миндаль, вес',
    countryName: 'Иран',
    norm: '1',
    alternativeOfId: 'row-1',
  }),
  draft({
    key: 'row-4',
    salesProductId: 'fin-2',
    productId: 'raw-3',
    productCode: 'RAW-3',
    productName: 'Пекан, вес',
    countryName: 'Турция',
    norm: '',
  }),
]

describe('PurchaseConsumptionView', () => {
  it('показывает сырьё карточками, а под ним продукцию и нормы', () => {
    render(<PurchaseConsumptionView plan={plan()} drafts={DRAFTS} />)

    const card = screen.getByTestId('consumption-card-RAW-1')
    expect(card).toHaveTextContent('позиций: 2 · строк: 2')
    expect(within(card).getByText(/FIN-1 · Смесь ореховая, 100 гр/)).toBeInTheDocument()
    expect(within(card).getByText(/FIN-2 · Нуга ореховая/)).toBeInTheDocument()
    expect(card).toHaveTextContent('1,5')
    expect(card).toHaveTextContent('450')
    // Второй продукт: 50 шт × 2 = 100 кг.
    const nougaRow = within(card)
      .getByText(/FIN-2 · Нуга ореховая/)
      .closest('tr')
    expect(nougaRow).toHaveTextContent('100')
    expect(screen.getByTestId('consumption-count')).toHaveTextContent('Сырья: 3 · строк: 4')
  })

  it('помечает альтернативное сырьё и строки без нормы', () => {
    render(<PurchaseConsumptionView plan={plan()} drafts={DRAFTS} />)

    expect(screen.getByTestId('consumption-card-RAW-2')).toHaveTextContent('альтернатива')
    const pecan = screen.getByTestId('consumption-card-RAW-3')
    expect(pecan).toHaveTextContent('без нормы: 1')
    expect(within(pecan).getByText('не задана')).toBeInTheDocument()
    expect(within(pecan).queryByRole('button', { name: /Расход по месяцам/ })).toBeNull()
  })

  it('раскрывает расход по месяцам у выбранной строки', async () => {
    const user = userEvent.setup()
    const { container } = render(<PurchaseConsumptionView plan={plan()} drafts={DRAFTS} />)

    await user.click(screen.getByTestId('months-toggle-row-1'))
    expect(screen.getByTestId('months-toggle-row-1')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/расход по месяцам, кг/)).toBeInTheDocument()
    const strip = container.querySelector('.months-strip')
    expect(strip?.querySelectorAll('li')).toHaveLength(12)
    expect(strip).toHaveTextContent('янв150')
    expect(strip).toHaveTextContent('фев300')
    expect(strip).toHaveTextContent('—')
    // Годовая потребность повторяется в шапке панели.
    expect(screen.getByText(/за год:/)).toHaveTextContent('450')

    await user.click(screen.getByTestId('months-toggle-row-1'))
    expect(screen.queryByText(/расход по месяцам, кг/)).toBeNull()
  })

  it('ищет по сырью и по продукции, счётчик показывает «из»', async () => {
    const user = userEvent.setup()
    render(<PurchaseConsumptionView plan={plan()} drafts={DRAFTS} />)
    const search = screen.getByLabelText('Поиск по сырью или продукции')

    await user.type(search, 'Миндаль')
    expect(screen.getByTestId('consumption-card-RAW-2')).toBeInTheDocument()
    expect(screen.queryByTestId('consumption-card-RAW-1')).toBeNull()
    expect(screen.getByTestId('consumption-count')).toHaveTextContent('из 3')

    await user.clear(search)
    await user.type(search, 'Нуга')
    // Сырьё без совпадения в названии показывает только подходящие строки.
    const raw = screen.getByTestId('consumption-card-RAW-1')
    expect(raw).toHaveTextContent('Нуга ореховая')
    expect(raw).not.toHaveTextContent('Смесь ореховая')
    expect(raw).toHaveTextContent('позиций: 1 · строк: 1')
    expect(screen.getByTestId('consumption-card-RAW-3')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Сбросить' }))
    expect(screen.getByTestId('consumption-count')).toHaveTextContent('Сырья: 3 · строк: 4')
  })

  it('объясняет пустой поиск и пустой план', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<PurchaseConsumptionView plan={plan()} drafts={DRAFTS} />)

    await user.type(screen.getByLabelText('Поиск по сырью или продукции'), 'абракадабра')
    expect(screen.getByTestId('consumption-no-match')).toBeInTheDocument()
    expect(screen.getByTestId('consumption-count')).toHaveTextContent('Сырья: 0 из 3')

    rerender(<PurchaseConsumptionView plan={plan()} drafts={[]} />)
    expect(screen.getByTestId('consumption-empty')).toBeInTheDocument()
  })
})
