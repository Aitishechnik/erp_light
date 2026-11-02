import { useEffect, useState } from 'react'
import {
  fetchStock,
  formatDate,
  formatMoney,
  formatQuantity,
  PRODUCT_KIND_LABELS,
  type StockRow,
} from './api'

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; rows: StockRow[] }

export function StockPage() {
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetchStock(controller.signal)
      .then((rows) => setState({ status: 'ready', rows }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : 'Не удалось загрузить остатки',
        })
      })
    return () => controller.abort()
  }, [])

  const totalValue =
    state.status === 'ready'
      ? state.rows.reduce((sum, row) => sum + Number(row.value_rub || 0), 0)
      : 0

  return (
    <section>
      <header className="page-head">
        <h1>Партии и остатки</h1>
        {state.status === 'ready' ? (
          <div className="page-stats">
            <span>
              Партий: <strong>{state.rows.length}</strong>
            </span>
            <span>
              Стоимость остатка:{' '}
              <strong data-testid="total-value">{formatMoney(String(totalValue))} ₽</strong>
            </span>
          </div>
        ) : null}
      </header>

      {state.status === 'loading' ? <p className="hint">Загрузка остатков…</p> : null}

      {state.status === 'error' ? (
        <p className="error" role="alert">
          {state.message}
        </p>
      ) : null}

      {state.status === 'ready' && state.rows.length === 0 ? (
        <p className="hint" data-testid="empty-state">
          Данных пока нет. Загрузите выгрузку из 1С или создайте партию вручную.
        </p>
      ) : null}

      {state.status === 'ready' && state.rows.length > 0 ? (
        <table data-testid="stock-table">
          <thead>
            <tr>
              <th scope="col">Партия</th>
              <th scope="col">Дата</th>
              <th scope="col">Код</th>
              <th scope="col">Наименование</th>
              <th scope="col">Вид</th>
              <th scope="col" className="num">
                Остаток
              </th>
              <th scope="col">Ед.</th>
              <th scope="col" className="num">
                Себест. ед., ₽
              </th>
              <th scope="col" className="num">
                Стоимость, ₽
              </th>
            </tr>
          </thead>
          <tbody>
            {state.rows.map((row) => (
              <tr key={row.batch_item_id}>
                <td>{row.batch_number}</td>
                <td>{formatDate(row.batch_date)}</td>
                <td>{row.product_code}</td>
                <td>{row.product_name}</td>
                <td>{PRODUCT_KIND_LABELS[row.product_kind] ?? row.product_kind}</td>
                <td className="num">{formatQuantity(row.quantity_on_hand)}</td>
                <td>{row.unit}</td>
                <td className="num">{formatMoney(row.unit_cost)}</td>
                <td className="num">{formatMoney(row.value_rub)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}
