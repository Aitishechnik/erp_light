import { useCallback, useEffect, useState } from 'react'
import {
  type AnnualSalesPlan,
  annualSalesPlanAction,
  errorMessage,
  fetchAnnualSalesPlan,
  formatQuantity,
  MONTH_TITLES,
  rejectAnnualSalesPlan,
  reopenAnnualSalesPlan,
  type SessionUser,
} from './api'

export function AnnualSalesPlanPage({ user, focus }: { user: SessionUser; focus?: string[] }) {
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(focus?.[0] ? Number(focus[0]) : thisYear)
  const [annual, setAnnual] = useState<AnnualSalesPlan | null>(null)
  const [managerFilter, setManagerFilter] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const isCommercial = user.role === 'commercial_director'
  const isExecutive = user.role === 'executive_director'

  const reload = useCallback(async () => {
    try {
      setAnnual(await fetchAnnualSalesPlan(year))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [year])

  useEffect(() => {
    void reload()
  }, [reload])

  const run = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true)
    setError(null)
    setSaved(null)
    try {
      await action()
      await reload()
      setSaved(message)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (annual === null) {
    return (
      <section>
        <h1>Годовой план отдела продаж</h1>
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : (
          <p className="hint">Загрузка…</p>
        )}
      </section>
    )
  }

  const canSubmit =
    isCommercial &&
    annual.all_approved &&
    (annual.status === 'draft' || annual.status === 'revision')
  const canApprove = isExecutive && annual.status === 'on_review'
  const canReopen = isExecutive && annual.status === 'approved'
  const items = managerFilter
    ? annual.items.filter((row) => row.manager_id === managerFilter)
    : annual.items

  return (
    <section>
      <header className="page-head">
        <h1>Годовой план отдела продаж</h1>
        <p className="hint">
          Собирается из утверждённых планов всех менеджеров. Финально согласует генеральный
          директор; любое изменение плана менеджера требует повторного согласования.
        </p>
        <div className="toolbar">
          <button
            type="button"
            aria-label="Предыдущий год"
            disabled={busy}
            onClick={() => {
              setYear(year - 1)
              setSaved(null)
              setManagerFilter('')
            }}
          >
            ←
          </button>
          <strong data-testid="annual-year">{year}</strong>
          <button
            type="button"
            aria-label="Следующий год"
            disabled={busy}
            onClick={() => {
              setYear(year + 1)
              setSaved(null)
              setManagerFilter('')
            }}
          >
            →
          </button>
        </div>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p className="hint saved" data-testid="annual-saved">
          {saved}
        </p>
      ) : null}

      <div className="purchase-summary" data-testid="annual-status">
        <span className={`badge status-${annual.is_stale ? 'revision' : annual.status}`}>
          {annual.status_title}
        </span>
        {annual.submitted_by_name ? (
          <span>
            отправил: {annual.submitted_by_name}
            {annual.submitted_at ? ` · ${annual.submitted_at.slice(0, 10)}` : ''}
          </span>
        ) : null}
        {annual.approved_by_name ? (
          <span>
            утвердил: {annual.approved_by_name}
            {annual.approved_at ? ` · ${annual.approved_at.slice(0, 10)}` : ''}
          </span>
        ) : null}
        <span className="total">менеджеров: {annual.managers.length}</span>
      </div>

      {annual.is_stale ? (
        <p className="hint warn" data-testid="annual-stale">
          Состав или данные утверждённых планов изменились — нужно повторное финальное согласование.
        </p>
      ) : null}
      {annual.missing_managers.length > 0 ? (
        <p className="hint warn" data-testid="annual-missing">
          Нет утверждённого плана: {annual.missing_managers.join(', ')}. Отправить годовой план
          нельзя, пока планы не утверждены у всех активных менеджеров.
        </p>
      ) : null}
      {annual.notes ? <p className="hint">Примечания: {annual.notes}</p> : null}

      <div className="toolbar">
        {canSubmit ? (
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() =>
              run(
                () => annualSalesPlanAction(year, 'submit'),
                'План отправлен на финальное согласование',
              )
            }
          >
            Отправить на финальное согласование
          </button>
        ) : null}
        {canApprove ? (
          <button
            type="button"
            className="primary"
            disabled={busy || annual.is_stale}
            onClick={() =>
              run(() => annualSalesPlanAction(year, 'approve'), 'Годовой план финально согласован')
            }
          >
            Утвердить
          </button>
        ) : null}
        {canApprove || canReopen ? (
          <input
            aria-label="Причина"
            placeholder="Причина"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        ) : null}
        {canApprove ? (
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await rejectAnnualSalesPlan(year, reason)
                setReason('')
              }, 'Годовой план возвращён на доработку')
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
                await reopenAnnualSalesPlan(year, reason)
                setReason('')
              }, 'Годовой план возвращён в работу')
            }
          >
            Вернуть в работу
          </button>
        ) : null}
        {!isCommercial && !isExecutive ? (
          <span className="hint">Просмотр: финально согласует генеральный директор</span>
        ) : null}
      </div>

      <table data-testid="annual-managers">
        <thead>
          <tr>
            <th scope="col">Менеджер</th>
            <th scope="col">План</th>
            <th scope="col" className="num">
              Позиций
            </th>
            <th scope="col" className="num">
              Клиентов
            </th>
          </tr>
        </thead>
        <tbody>
          {annual.managers.map((row) => (
            <tr key={row.manager_id}>
              <td>{row.manager_name}</td>
              <td>
                <span className={`badge status-${row.plan_status ?? 'draft'}`}>
                  {row.plan_status_title ?? 'Плана нет'}
                </span>
              </td>
              <td className="num">{row.positions}</td>
              <td className="num">{row.clients}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="toolbar annual-items-head">
        <span className="hint">Утверждённые строки плана отдела</span>
        <span className="sep" />
        <select
          aria-label="Менеджер"
          value={managerFilter}
          onChange={(event) => setManagerFilter(event.target.value)}
        >
          <option value="">Все менеджеры</option>
          {annual.managers.map((row) => (
            <option key={row.manager_id} value={row.manager_id}>
              {row.manager_name}
            </option>
          ))}
        </select>
      </div>

      <div className="purchase-table">
        <table data-testid="annual-items">
          <thead>
            <tr>
              <th scope="col">Менеджер</th>
              <th scope="col">Клиент</th>
              <th scope="col">Товар</th>
              <th scope="col">Месяц</th>
              <th scope="col" className="num">
                Количество
              </th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={5} className="hint" data-testid="annual-empty">
                  Утверждённых строк пока нет.
                </td>
              </tr>
            ) : (
              items.map((row) => (
                <tr key={`${row.manager_id}-${row.client_id}-${row.product_id}-${row.month}`}>
                  <td>{row.manager_name}</td>
                  <td>{row.client_name}</td>
                  <td>
                    {row.product_code} · {row.product_name}
                    <span className="unit">, {row.unit}</span>
                  </td>
                  <td>{MONTH_TITLES[row.month - 1]}</td>
                  <td className="num">
                    {formatQuantity(row.quantity)} {row.unit}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
