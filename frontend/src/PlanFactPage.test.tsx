import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlanFactDetail, PlanFactMonth, PlanFactSummary, SessionUser } from './api'
import { mockApi } from './apiMock'
import { PlanFactPage, tone } from './PlanFactPage'

const SALES: SessionUser = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Менеджер по продажам',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

const MONTHS: PlanFactMonth[] = Array.from({ length: 12 }, (_, index) => ({
  year: 2026,
  month: index + 1,
  annual_quantity: '1000.000',
  monthly_quantity: index < 5 ? '1100.000' : '1000.000',
  fact_quantity: index < 4 ? '900.000' : '0.000',
  fact_loaded: index < 4,
  revised: index < 5,
  monthly_state: index < 5 ? 'approved' : 'none',
  month_closed: index < 3,
  window_start: '2026-01-23',
  window_end: '2026-01-31',
  window_state: 'closed',
}))

const SUMMARY: PlanFactSummary = {
  year: 2026,
  annual_total: '12000.000',
  monthly_total: '12500.000',
  fact_total: '3600.000',
  months: MONTHS,
}

const DETAIL: PlanFactDetail = {
  year: 2026,
  month: 4,
  annual_quantity: '150.000',
  monthly_quantity: '150.000',
  fact_quantity: '130.000',
  rows: [
    {
      client_id: 'c-1',
      client_name: 'ООО Ромашка',
      manager_id: 'sm-1',
      manager_name: 'Менеджер по продажам',
      product_id: 'p-1',
      product_name: 'Изюм',
      unit: 'кг',
      annual_quantity: '100.000',
      monthly_quantity: '110.000',
      fact_quantity: '90.000',
      plan_reason: 'Клиент подтвердил доп. объём',
      fact_reason: 'Товар не пришёл вовремя',
      is_new: false,
      removed: false,
    },
    {
      client_id: 'c-1',
      client_name: 'ООО Ромашка',
      manager_id: 'sm-1',
      manager_name: 'Менеджер по продажам',
      product_id: 'p-2',
      product_name: 'Курага',
      unit: 'кг',
      annual_quantity: '50.000',
      monthly_quantity: '0.000',
      fact_quantity: '0.000',
      plan_reason: 'Сеть вывела позицию из торговой матрицы',
      fact_reason: null,
      is_new: false,
      removed: true,
    },
    {
      client_id: 'c-1',
      client_name: 'ООО Ромашка',
      manager_id: 'sm-1',
      manager_name: 'Менеджер по продажам',
      product_id: 'p-3',
      product_name: 'Киви',
      unit: 'кг',
      annual_quantity: '0.000',
      monthly_quantity: '40.000',
      fact_quantity: '40.000',
      plan_reason: 'Новая позиция по запросу сети',
      fact_reason: null,
      is_new: true,
      removed: false,
    },
    {
      client_id: 'c-2',
      client_name: 'ООО Поле',
      manager_id: 'sm-1',
      manager_name: 'Менеджер по продажам',
      product_id: 'p-4',
      product_name: 'Новинка',
      unit: 'кг',
      annual_quantity: '0.000',
      monthly_quantity: '0.000',
      fact_quantity: '20000.000',
      plan_reason: null,
      fact_reason: null,
      is_new: false,
      removed: false,
    },
  ],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('tone', () => {
  it('красит любое отклонение по знаку, даже когда плана нет', () => {
    expect(tone(1)).toBe('delta-good')
    expect(tone(20000)).toBe('delta-good')
    expect(tone(-1)).toBe('delta-bad')
    expect(tone(0)).toBe('')
    expect(tone(null)).toBe('muted')
  })
})

describe('PlanFactPage', () => {
  it('показывает сводку года и раскрывает месяц с двумя причинами', async () => {
    mockApi({
      '/api/v1/plan-fact/2026/4': { body: DETAIL },
      '/api/v1/plan-fact?year=2026': { body: SUMMARY },
    })
    render(<PlanFactPage user={SALES} initialYear={2026} />)

    expect(await screen.findByText(/12\s*000(,\d+)?\s*кг/)).toBeInTheDocument()
    expect(screen.getByText(/12\s*500(,\d+)?\s*кг/)).toBeInTheDocument()

    await userEvent.click(screen.getByText('Апрель'))
    await waitFor(() => expect(screen.getByText('Курага')).toBeInTheDocument())

    expect(screen.getByText('выведена')).toBeInTheDocument()
    expect(screen.getByText('новая')).toBeInTheDocument()
    expect(screen.getByText('Сеть вывела позицию из торговой матрицы')).toBeInTheDocument()
    expect(screen.getByText('Товар не пришёл вовремя')).toBeInTheDocument()

    const abovePlan = screen.getByText('+20 000,00')
    expect(abovePlan.className).toContain('delta-good')
  })

  it('месяц без пересмотра помечен как непересмотренный', async () => {
    mockApi({ '/api/v1/plan-fact?year=2026': { body: SUMMARY } })
    render(<PlanFactPage user={SALES} initialYear={2026} />)

    const rows = await screen.findAllByText('не пересматривался')
    expect(rows.length).toBeGreaterThan(0)
  })
})
