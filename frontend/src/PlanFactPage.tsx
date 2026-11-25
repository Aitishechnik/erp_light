import { type ReactNode, useEffect, useState } from 'react'
import {
  errorMessage,
  fetchManagers,
  fetchPlanFact,
  fetchPlanFactMonth,
  MONTH_SHORT,
  MONTH_TITLES,
  type PlanFactDetail,
  type PlanFactMonth,
  type PlanFactRow,
  type PlanFactSummary,
  type SessionUser,
  scopeFor,
} from './api'
import { PageHelp } from './PageHelp'

const QTY_FORMAT = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const INT_FORMAT = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

function formatQty(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? QTY_FORMAT.format(parsed) : String(value)
}

const BAR_ANNUAL = 'var(--accent-soft)'
const BAR_MONTHLY = 'var(--accent)'
const BAR_FACT = 'var(--good)'
const MUTED = 'var(--muted)'
const GRID = 'var(--border)'

function number(value: string | number | null | undefined): number {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function share(fact: number, plan: number): number | null {
  return plan > 0 ? (fact / plan) * 100 : null
}

function percent(value: number | null): string {
  if (value === null) return '—'
  return `${value.toFixed(1).replace('.', ',')} %`
}

/** Цвет отклонения: зелёный — факт выше плана, красный — ниже. Без плана — по знаку дельты. */
export function tone(delta: number | null): string {
  if (delta === null) return 'muted'
  if (delta > 0) return 'delta-good'
  if (delta < 0) return 'delta-bad'
  return ''
}

function percentTone(value: number | null, delta: number | null): string {
  if (value === null) return 'muted'
  return tone(delta)
}

function signed(value: number): string {
  const formatted = formatQty(String(Math.abs(value)))
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${formatted}`
}

function MonthStatus({ month }: { month: PlanFactMonth }) {
  if (month.month_closed) {
    return <span className="badge status-approved">закрыт</span>
  }
  if (month.monthly_state === 'approved') {
    return <span className="badge status-filling">месяц утверждён</span>
  }
  if (month.monthly_state === 'partial') {
    return <span className="badge status-on_review">пересмотрен частично</span>
  }
  if (month.window_state === 'open') {
    return <span className="badge status-on_review">окно пересмотра</span>
  }
  return <span className="badge">не пересматривался</span>
}

function Reasons({ row }: { row: PlanFactRow }) {
  if (!row.plan_reason && !row.fact_reason) return null
  return (
    <div className="reason-stack">
      {row.plan_reason ? (
        <span className="reason-line">
          <b>план</b>
          {row.plan_reason}
        </span>
      ) : null}
      {row.fact_reason ? (
        <span className="reason-line">
          <b>факт</b>
          {row.fact_reason}
        </span>
      ) : null}
    </div>
  )
}

function Chart({ months }: { months: PlanFactMonth[] }) {
  const width = 1000
  const height = 230
  const left = 58
  const right = 10
  const top = 10
  const bottom = 26
  const step = (width - left - right) / 12
  const max = Math.max(...months.map((row) => number(row.annual_quantity)), 1)
  const y = (value: number) => top + (height - top - bottom) * (1 - value / max)
  const plot = height - top - bottom

  return (
    <svg
      className="plan-fact-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Годовой план, месячный план и факт по месяцам"
    >
      {[0, 0.5, 1].map((part) => {
        const value = max * part
        return (
          <g key={part}>
            <line x1={left} x2={width - right} y1={y(value)} y2={y(value)} stroke={GRID} />
            <text x={left - 9} y={y(value) + 3.5} textAnchor="end" fontSize="10" fill={MUTED}>
              {INT_FORMAT.format(Math.round(value))}
            </text>
          </g>
        )
      })}
      {months.map((row, index) => {
        const center = left + step * (index + 0.5)
        const values: [string, number | null, string][] = [
          ['annual', number(row.annual_quantity), BAR_ANNUAL],
          [
            'monthly',
            row.monthly_state === 'none' ? null : number(row.monthly_quantity),
            BAR_MONTHLY,
          ],
          ['fact', row.fact_loaded ? number(row.fact_quantity) : null, BAR_FACT],
        ]
        const barWidth = 12
        const gap = 3
        const start = center - (barWidth * 3 + gap * 2) / 2
        return (
          <g key={row.month}>
            {values.map(([name, value, color], position) => {
              if (value === null) return null
              const barHeight = plot * (value / max)
              return (
                <rect
                  key={name}
                  x={start + position * (barWidth + gap)}
                  y={height - bottom - barHeight}
                  width={barWidth}
                  height={Math.max(barHeight, value === 0 ? 0 : 1)}
                  rx={2.5}
                  fill={color}
                />
              )
            })}
            <text x={center} y={height - 8} textAnchor="middle" fontSize="10.5" fill={MUTED}>
              {MONTH_SHORT[index]}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function Legend() {
  return (
    <div className="plan-fact-legend">
      <span>
        <i style={{ background: BAR_ANNUAL }} />
        Годовой план
      </span>
      <span>
        <i style={{ background: BAR_MONTHLY }} />
        Месячный план
      </span>
      <span>
        <i style={{ background: BAR_FACT }} />
        Факт
      </span>
    </div>
  )
}

function DetailPanel({
  detail,
  loading,
}: {
  detail: PlanFactDetail | null
  loading: boolean
}): ReactNode {
  const [open, setOpen] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (!detail) return
    setOpen(
      new Set(detail.rows.filter((row) => row.removed || row.is_new).map((row) => row.client_id)),
    )
  }, [detail])

  if (loading) return <p className="hint">Загрузка детализации…</p>
  if (!detail) return <p className="hint">Нет данных за этот месяц.</p>

  const groups = new Map<string, PlanFactRow[]>()
  for (const row of detail.rows) {
    const rows = groups.get(row.client_id) ?? []
    rows.push(row)
    groups.set(row.client_id, rows)
  }

  return (
    <div className="plan-fact-detail">
      <div className="plan-fact-detail-head">
        <strong>{MONTH_TITLES[detail.month - 1]} · детализация</strong>
        <span className="hint">клиент → позиция; в конце — две причины</span>
      </div>
      <table className="plan-fact-inner">
        <thead>
          <tr>
            <th>Клиент / позиция</th>
            <th className="num">Годовой</th>
            <th className="num">Месячный</th>
            <th className="num">Факт</th>
            <th className="num">% к месячному</th>
            <th className="num">Δ факт − месяц</th>
            <th>Причины</th>
          </tr>
        </thead>
        <tbody>
          {[...groups.entries()].map(([clientId, rows]) => {
            const annual = rows.reduce((sum, row) => sum + number(row.annual_quantity), 0)
            const monthly = rows.reduce((sum, row) => sum + number(row.monthly_quantity), 0)
            const fact = rows.reduce((sum, row) => sum + number(row.fact_quantity), 0)
            const value = share(fact, monthly)
            const delta = fact - monthly
            const expanded = open.has(clientId)
            return (
              <ClientGroup
                key={clientId}
                rows={rows}
                annual={annual}
                monthly={monthly}
                fact={fact}
                value={value}
                delta={delta}
                expanded={expanded}
                onToggle={() =>
                  setOpen((current) => {
                    const next = new Set(current)
                    if (next.has(clientId)) next.delete(clientId)
                    else next.add(clientId)
                    return next
                  })
                }
              />
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <td>Итого</td>
            <td className="num">{formatQty(detail.annual_quantity)}</td>
            <td className="num">{formatQty(detail.monthly_quantity)}</td>
            <td className="num">{formatQty(detail.fact_quantity)}</td>
            <td className="num">
              {percent(share(number(detail.fact_quantity), number(detail.monthly_quantity)))}
            </td>
            <td className="num">
              {signed(number(detail.fact_quantity) - number(detail.monthly_quantity))}
            </td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

function ClientGroup({
  rows,
  annual,
  monthly,
  fact,
  value,
  delta,
  expanded,
  onToggle,
}: {
  rows: PlanFactRow[]
  annual: number
  monthly: number
  fact: number
  value: number | null
  delta: number
  expanded: boolean
  onToggle: () => void
}) {
  const planReasons = rows.filter((row) => row.plan_reason).length
  const factReasons = rows.filter((row) => row.fact_reason).length
  return (
    <>
      <tr className="plan-fact-client" onClick={onToggle}>
        <td>
          <span className="caret">{expanded ? '▾' : '▸'}</span>
          {rows[0]?.client_name}
          <span className="hint"> · {rows.length} позиций</span>
        </td>
        <td className="num">{formatQty(String(annual))}</td>
        <td className="num">{formatQty(String(monthly))}</td>
        <td className="num">{formatQty(String(fact))}</td>
        <td className={`num ${percentTone(value, delta)}`}>{percent(value)}</td>
        <td className={`num ${tone(delta)}`}>{signed(delta)}</td>
        <td>
          {planReasons > 0 || factReasons > 0 ? (
            <span className="plan-fact-reason-count">
              {planReasons > 0 ? `план: ${planReasons}` : ''}
              {planReasons > 0 && factReasons > 0 ? ' · ' : ''}
              {factReasons > 0 ? `факт: ${factReasons}` : ''}
            </span>
          ) : null}
        </td>
      </tr>
      {expanded
        ? rows.map((row) => {
            const rowValue = share(number(row.fact_quantity), number(row.monthly_quantity))
            const rowDelta = number(row.fact_quantity) - number(row.monthly_quantity)
            return (
              <tr key={`${row.client_id}-${row.product_id}`} className="plan-fact-product">
                <td>
                  {row.product_name}
                  {row.is_new ? <span className="badge">новая</span> : null}
                  {row.removed ? <span className="badge">выведена</span> : null}
                  {row.product_name.toLowerCase().includes(row.unit.toLowerCase()) ? null : (
                    <span className="hint"> · {row.unit}</span>
                  )}
                </td>
                <td className="num">
                  {row.is_new && number(row.annual_quantity) === 0
                    ? '—'
                    : formatQty(row.annual_quantity)}
                </td>
                <td className="num">{formatQty(row.monthly_quantity)}</td>
                <td className="num">{formatQty(row.fact_quantity)}</td>
                <td className={`num ${percentTone(rowValue, rowDelta)}`}>{percent(rowValue)}</td>
                <td className={`num ${tone(rowDelta)}`}>
                  {rowDelta === 0 ? '0' : signed(rowDelta)}
                </td>
                <td>
                  <Reasons row={row} />
                </td>
              </tr>
            )
          })
        : null}
    </>
  )
}

export function PlanFactPage({ user, initialYear }: { user: SessionUser; initialYear?: number }) {
  const isManager = scopeFor(user, 'plan_fact', 'view') === 'own'
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(initialYear ?? thisYear)
  const [managerId, setManagerId] = useState('')
  const [managers, setManagers] = useState<SessionUser[]>([])
  const [summary, setSummary] = useState<PlanFactSummary | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [detail, setDetail] = useState<PlanFactDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (isManager) return
    fetchManagers()
      .then(setManagers)
      .catch(() => setManagers([]))
  }, [isManager])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setExpanded(null)
    setDetail(null)
    fetchPlanFact(year, managerId || null)
      .then((loaded) => {
        if (!cancelled) setSummary(loaded)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [year, managerId])

  const openMonth = async (month: number) => {
    if (expanded === month) {
      setExpanded(null)
      setDetail(null)
      return
    }
    setExpanded(month)
    setDetail(null)
    setDetailLoading(true)
    try {
      const loaded = await fetchPlanFactMonth(year, month, managerId || null)
      setDetail(loaded)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setDetailLoading(false)
    }
  }

  const months = summary?.months ?? []
  const annualTotal = number(summary?.annual_total)
  const monthlyTotal = number(summary?.monthly_total)
  const factTotal = number(summary?.fact_total)
  const approvedMonths = months.filter((row) => row.monthly_state === 'approved').length
  const loadedMonths = months.filter((row) => row.fact_loaded)
  const ytdMonthly = loadedMonths.reduce((sum, row) => sum + number(row.monthly_quantity), 0)
  const ytdFact = loadedMonths.reduce((sum, row) => sum + number(row.fact_quantity), 0)

  return (
    <section data-testid="plan-fact">
      <header className="page-head">
        <h1>План и факт</h1>
        <PageHelp>
          Годовой план — утверждённые планы менеджеров. Месячный план — пересмотр месяца; если месяц
          не пересматривали, он равен годовому. Факт — продажи из выгрузки 1С. Сравнение по
          количеству: цен в плане продаж нет. Раскройте месяц, чтобы увидеть клиентов, позиции и
          причины.
        </PageHelp>
        <div className="toolbar">
          <button type="button" onClick={() => setYear(year - 1)} aria-label="Предыдущий год">
            ←
          </button>
          <strong data-testid="plan-fact-year">{year}</strong>
          <button type="button" onClick={() => setYear(year + 1)} aria-label="Следующий год">
            →
          </button>
          {!isManager ? (
            <select
              aria-label="Менеджер"
              value={managerId}
              onChange={(event) => setManagerId(event.target.value)}
            >
              <option value="">Все менеджеры</option>
              {managers.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.full_name}
                </option>
              ))}
            </select>
          ) : null}
        </div>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <p className="hint">Загрузка сравнения…</p> : null}

      {summary ? (
        <>
          <div className="kpis kpis-3 plan-fact-kpis">
            <div className="kpi">
              <span className="kpi-label">Годовой план</span>
              <span className="kpi-value">{formatQty(String(annualTotal))} кг</span>
              <span className="kpi-sub">12 месяцев · утверждённые планы</span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Месячный план</span>
              <span className="kpi-value">{formatQty(String(monthlyTotal))} кг</span>
              <span className="kpi-sub">{approvedMonths} из 12 месяцев утверждены</span>
            </div>
            <div className="kpi kpi-primary">
              <span className="kpi-label">Факт с начала года</span>
              <span className="kpi-value">{formatQty(String(factTotal))} кг</span>
              <span className="kpi-sub">
                {percent(share(ytdFact, ytdMonthly))} месячного ·{' '}
                {percent(share(factTotal, annualTotal))} года
              </span>
            </div>
          </div>

          <div className="plan-fact-card">
            <div className="plan-fact-card-head">
              <h2 className="section-title">План и факт по месяцам</h2>
              <Legend />
            </div>
            <Chart months={months} />
          </div>

          <div className="table-scroll">
            <table className="plan-fact-table">
              <thead>
                <tr>
                  <th scope="col">Месяц</th>
                  <th scope="col" className="num">
                    Годовой план
                  </th>
                  <th scope="col" className="num">
                    Месячный план
                  </th>
                  <th scope="col" className="num">
                    Δ месяц − год
                  </th>
                  <th scope="col" className="num">
                    Факт
                  </th>
                  <th scope="col" className="num">
                    % к месячному
                  </th>
                  <th scope="col" className="num">
                    Δ факт − месяц
                  </th>
                  <th scope="col">Состояние</th>
                </tr>
              </thead>
              <tbody>
                {months.map((row) => {
                  const fact = row.fact_loaded ? number(row.fact_quantity) : null
                  const monthly = number(row.monthly_quantity)
                  const value = fact === null ? null : share(fact, monthly)
                  const delta = fact === null ? null : fact - monthly
                  const isOpen = expanded === row.month
                  return (
                    <MonthRow
                      key={row.month}
                      row={row}
                      fact={fact}
                      value={value}
                      delta={delta}
                      isOpen={isOpen}
                      detail={isOpen ? detail : null}
                      loading={isOpen && detailLoading}
                      onToggle={() => void openMonth(row.month)}
                    />
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td>Итого</td>
                  <td className="num">{formatQty(String(annualTotal))}</td>
                  <td className="num">{formatQty(String(monthlyTotal))}</td>
                  <td className="num">{signed(monthlyTotal - annualTotal)}</td>
                  <td className="num">{formatQty(String(factTotal))}</td>
                  <td className="num">{percent(share(ytdFact, ytdMonthly))}</td>
                  <td className="num">{signed(ytdFact - ytdMonthly)}</td>
                  <td>
                    <span className="badge">{approvedMonths} из 12</span>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="hint">
            Месяц без пересмотра равен годовому плану. Причины показываются в двух видах: почему
            изменили план и почему факт отличается от плана. Цвет: зелёный — факт не ниже плана,
            красный — ниже; «—» — плана нет или факта ещё нет.
          </p>
        </>
      ) : null}
    </section>
  )
}

function MonthRow({
  row,
  fact,
  value,
  delta,
  isOpen,
  detail,
  loading,
  onToggle,
}: {
  row: PlanFactMonth
  fact: number | null
  value: number | null
  delta: number | null
  isOpen: boolean
  detail: PlanFactDetail | null
  loading: boolean
  onToggle: () => void
}) {
  const annual = number(row.annual_quantity)
  const monthly = number(row.monthly_quantity)
  return (
    <>
      <tr className="plan-fact-month" onClick={onToggle}>
        <td>
          <span className="caret">{isOpen ? '▾' : '▸'}</span>
          {MONTH_TITLES[row.month - 1]}
        </td>
        <td className="num">{formatQty(row.annual_quantity)}</td>
        <td className="num">{formatQty(row.monthly_quantity)}</td>
        <td className="num">{signed(monthly - annual)}</td>
        <td className="num">{fact === null ? '—' : formatQty(String(fact))}</td>
        <td className={`num ${percentTone(value, delta)}`}>
          {fact === null ? '—' : percent(value)}
        </td>
        <td className={`num ${tone(delta)}`}>{fact === null ? '—' : signed(delta ?? 0)}</td>
        <td>
          <MonthStatus month={row} />
        </td>
      </tr>
      {isOpen ? (
        <tr className="plan-fact-expand">
          <td colSpan={8}>
            <DetailPanel detail={detail} loading={loading} />
          </td>
        </tr>
      ) : null}
    </>
  )
}
