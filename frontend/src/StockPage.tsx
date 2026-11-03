import { useEffect, useMemo, useState } from 'react'
import {
  fetchStock,
  formatDate,
  formatMoney,
  formatQuantity,
  PRODUCT_KIND_LABELS,
  type StockRow,
} from './api'
import { SortableTh } from './SortableTh'
import { type SortState, sortRows, toggleSort } from './tableSort'

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; rows: StockRow[] }

/** По умолчанию — по номеру партии: так их и заводит 1С. */
const DEFAULT_SORT: SortState = { column: 'batch', direction: 'asc' }

export function StockPage() {
  const [state, setState] = useState<State>({ status: 'loading' })
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT)

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

  const rows = state.status === 'ready' ? state.rows : []
  const sorted = useMemo(
    () =>
      sortRows(rows, sort, (row, column) => {
        if (column === 'date') return row.batch_date
        if (column === 'code') return row.product_code
        if (column === 'name') return row.product_name
        if (column === 'kind') return PRODUCT_KIND_LABELS[row.product_kind] ?? row.product_kind
        if (column === 'qty') return Number(row.quantity_on_hand)
        if (column === 'unit') return row.unit
        if (column === 'cost') return Number(row.unit_cost)
        if (column === 'value') return Number(row.value_rub)
        return row.batch_number
      }),
    [rows, sort],
  )

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
              <SortableTh
                column="batch"
                title="Партия"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="date"
                title="Дата"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="code"
                title="Код"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="name"
                title="Наименование"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="kind"
                title="Вид"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="qty"
                title="Остаток"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
                className="num"
              />
              <SortableTh
                column="unit"
                title="Ед."
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="cost"
                title="Себест. ед., ₽"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
                className="num"
              />
              <SortableTh
                column="value"
                title="Стоимость, ₽"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
                className="num"
              />
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
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
