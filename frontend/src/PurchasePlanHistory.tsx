import { useEffect, useMemo, useState } from 'react'
import { formatDate, MONTH_TITLES, type PurchasePlan, type PurchasePlanSignal } from './api'

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

/**
 * История изменений плана закупок отдельным видом: месяц, причина, автор и
 * «было → стало» по строкам. Вынесена с основного экрана, чтобы план и расход
 * сырья не тонули в длинной ленте.
 */
export function PurchasePlanHistory({ plan }: { plan: PurchasePlan }) {
  const signals = plan.signals ?? []
  const [openSignals, setOpenSignals] = useState<string[]>([])

  // Новое изменение раскрыто, остальные свёрнуты; «свернуть все» не разворачивает снова.
  useEffect(() => {
    if (signals.length === 0) return
    setOpenSignals((current) => {
      const known = new Set(signals.map((signal) => signal.id))
      const kept = current.filter((id) => known.has(id))
      const first = signals[0]
      return kept.length > 0 || first === undefined ? kept : [first.id]
    })
  }, [signals])

  const groups = useMemo(() => {
    const result = new Map<number, PurchasePlanSignal[]>()
    for (const signal of signals) {
      const key = signal.month ?? 0
      result.set(key, [...(result.get(key) ?? []), signal])
    }
    return [...result.entries()].map(([month, rows]) => ({
      month,
      signals: rows,
      added: rows.reduce(
        (total, signal) =>
          total +
          signal.lines.reduce((sum, line) => sum + (line.delta_kg ? Number(line.delta_kg) : 0), 0),
        0,
      ),
    }))
  }, [signals])

  return (
    <div className="history-view" data-testid="history-view">
      <div className="view-head">
        <h2>История изменений на {plan.year} год</h2>
        {signals.length > 0 ? (
          <span className="hint" data-testid="signal-count">
            Изменений: {signals.length}
          </span>
        ) : null}
        {openSignals.length > 0 ? (
          <button type="button" className="mini" onClick={() => setOpenSignals([])}>
            Свернуть все
          </button>
        ) : null}
      </div>

      {signals.length === 0 ? (
        <div className="empty-state" data-testid="history-empty">
          <strong>Изменений пока нет</strong>
          <span>Они появятся, когда план продаж пересмотрят или закроют месяц с отклонением.</span>
        </div>
      ) : (
        <section className="signal-history" data-testid="signal-history">
          {groups.map((group) => (
            <div className="signal-group" key={group.month}>
              {signals.length > 1 && group.month > 0 ? (
                <div className="signal-group-head">
                  <span>
                    {MONTH_TITLES[group.month - 1]} {plan.year}
                  </span>
                  <span className="hint">
                    изменений: {group.signals.length} · +{formatKg(group.added.toFixed(3))} кг
                  </span>
                </div>
              ) : null}
              {group.signals.map((signal) => {
                const isOpen = openSignals.includes(signal.id)
                const positions = new Set(signal.lines.map((line) => line.sales_product)).size
                const added = signal.lines.reduce(
                  (total, line) => total + (line.delta_kg ? Number(line.delta_kg) : 0),
                  0,
                )
                return (
                  <div className={isOpen ? 'signal-item open' : 'signal-item'} key={signal.id}>
                    <button
                      type="button"
                      className="signal-toggle"
                      aria-expanded={isOpen}
                      data-testid={`signal-toggle-${signal.id}`}
                      onClick={() =>
                        setOpenSignals((current) =>
                          current.includes(signal.id)
                            ? current.filter((id) => id !== signal.id)
                            : [...current, signal.id],
                        )
                      }
                    >
                      <span className="signal-caret">{isOpen ? '▾' : '▸'}</span>
                      <span className="signal-date">{formatDate(signal.created_at)}</span>
                      <span className="signal-month">
                        {signal.month
                          ? `${MONTH_TITLES[signal.month - 1]} ${plan.year}`
                          : 'месяц не указан'}
                      </span>
                      <span className="signal-reason">{signal.reason ?? 'изменение плана'}</span>
                      <span className="signal-stats">
                        {positions} поз. · {signal.lines.length} стр. · +
                        {formatKg(added.toFixed(3))} кг
                      </span>
                      <span className="signal-actor">{signal.actor_name ?? '—'}</span>
                    </button>
                    {isOpen ? (
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
                    ) : null}
                  </div>
                )
              })}
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
