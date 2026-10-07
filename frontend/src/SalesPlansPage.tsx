import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  createSalesPlan,
  deleteSalesPlan,
  fetchProducts,
  fetchSalesPlans,
  fetchUsers,
  formatMoney,
  MONTH_SHORT,
  MONTH_TITLES,
  type Product,
  rejectSalesPlan,
  type SalesPlan,
  type SalesPlanItemIn,
  type SessionUser,
  salesPlanAction,
  saveSalesPlanItems,
} from './api'

type DraftRow = {
  productId: string
  code: string
  name: string
  unit: string
  price: string
  months: Record<number, string>
}

const QTY_PATTERN = /^\d+(?:[.,]\d{1,3})?$/

function message(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return err instanceof Error ? err.message : 'Не удалось выполнить действие'
}

function normalize(raw: string): string {
  return raw.trim().replace(',', '.')
}

function draftFromPlan(plan: SalesPlan): DraftRow[] {
  const rows = new Map<string, DraftRow>()
  for (const item of plan.items) {
    let row = rows.get(item.product_id)
    if (!row) {
      row = {
        productId: item.product_id,
        code: item.product_code,
        name: item.product_name,
        unit: item.unit,
        price: item.price ?? '',
        months: {},
      }
      rows.set(item.product_id, row)
    }
    if (!row.price && item.price) row.price = item.price
    if (Number(item.quantity) !== 0) row.months[item.month] = item.quantity
  }
  return [...rows.values()].sort((a, b) => a.name.localeCompare(b.name, 'ru'))
}

export function SalesPlansPage({ user }: { user: SessionUser }) {
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(thisYear)
  const [plans, setPlans] = useState<SalesPlan[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [rows, setRows] = useState<DraftRow[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [managers, setManagers] = useState<SessionUser[]>([])
  const [managerId, setManagerId] = useState('')
  const [productToAdd, setProductToAdd] = useState('')
  const [rejectReason, setRejectReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isCommercialDirector = user.role === 'commercial_director'
  const isExecutive = user.role === 'executive_director'
  const yearPlans = plans.filter((plan) => plan.year === year)
  const plan = yearPlans.find((row) => row.id === selectedId) ?? null
  const isOwner = plan !== null && plan.manager_id === user.id

  const reload = useCallback(async () => {
    try {
      const loaded = await fetchSalesPlans()
      setPlans(loaded)
      setSelectedId((current) =>
        current && loaded.some((row) => row.id === current) ? current : (loaded[0]?.id ?? null),
      )
    } catch (err) {
      setError(message(err))
    }
  }, [])

  useEffect(() => {
    void reload()
    fetchProducts()
      .then(setProducts)
      .catch(() => setProducts([]))
    if (isCommercialDirector) {
      fetchUsers('sales_manager')
        .then((rows) => {
          setManagers(rows)
          setManagerId((current) => current || (rows[0]?.id ?? ''))
        })
        .catch(() => setManagers([]))
    }
  }, [reload, isCommercialDirector])

  useEffect(() => {
    setRows(plan ? draftFromPlan(plan) : [])
  }, [plan])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      await reload()
    } catch (err) {
      setError(message(err))
    } finally {
      setBusy(false)
    }
  }

  const editable = plan?.editable_months ?? []

  const collectItems = (): SalesPlanItemIn[] | null => {
    const items: SalesPlanItemIn[] = []
    for (const row of rows) {
      for (const month of editable) {
        const raw = normalize(row.months[month] ?? '')
        if (raw === '') continue
        if (!QTY_PATTERN.test(raw)) {
          setError(`Количество «${row.months[month]}» в строке ${row.name} — не число`)
          return null
        }
        const price = normalize(row.price)
        items.push({
          product_id: row.productId,
          month,
          quantity: raw,
          price: price === '' ? null : price,
        })
      }
    }
    return items
  }

  const setMonth = (productId: string, month: number, value: string) => {
    setRows((current) =>
      current.map((row) =>
        row.productId === productId ? { ...row, months: { ...row.months, [month]: value } } : row,
      ),
    )
  }

  const setPrice = (productId: string, value: string) => {
    setRows((current) =>
      current.map((row) => (row.productId === productId ? { ...row, price: value } : row)),
    )
  }

  const addRow = () => {
    const product = products.find((row) => row.id === productToAdd)
    if (!product) return
    setRows((current) => [
      ...current,
      {
        productId: product.id,
        code: product.code,
        name: product.name,
        unit: product.unit,
        price: '',
        months: {},
      },
    ])
    setProductToAdd('')
  }

  const rowTotal = (row: DraftRow): number => {
    const price = Number(normalize(row.price) || 0)
    return editable.reduce(
      (sum, month) => sum + Number(normalize(row.months[month] ?? '') || 0) * price,
      0,
    )
  }

  const total = rows.reduce((sum, row) => sum + rowTotal(row), 0)
  const canEdit =
    plan !== null &&
    (isCommercialDirector || (isOwner && ['draft', 'filling'].includes(plan.status)))
  const canSubmit = plan !== null && isOwner && ['draft', 'filling'].includes(plan.status)
  const canApprove = plan !== null && isCommercialDirector && plan.status === 'on_review'
  const canDelete =
    plan !== null && ['draft', 'filling'].includes(plan.status) && (isCommercialDirector || isOwner)

  return (
    <section>
      <header className="page-head">
        <h1>Планирование продаж</h1>
        <p className="hint">
          Годовой план на менеджера: товар × месяц. Утверждает коммерческий директор.
        </p>
        <div className="toolbar">
          <button type="button" onClick={() => setYear(year - 1)} aria-label="Предыдущий год">
            ←
          </button>
          <strong data-testid="plan-year">{year}</strong>
          <button type="button" onClick={() => setYear(year + 1)} aria-label="Следующий год">
            →
          </button>
          <span className="sep" />
          {isCommercialDirector ? (
            <>
              <select
                aria-label="Менеджер"
                value={managerId}
                onChange={(event) => setManagerId(event.target.value)}
              >
                {managers.map((manager) => (
                  <option key={manager.id} value={manager.id}>
                    {manager.full_name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="primary"
                disabled={busy || !managerId}
                onClick={() =>
                  run(() =>
                    createSalesPlan(year, managerId).then((created) => setSelectedId(created.id)),
                  )
                }
              >
                Создать план на {year}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() =>
                run(() => createSalesPlan(year).then((created) => setSelectedId(created.id)))
              }
            >
              Создать свой план на {year}
            </button>
          )}
        </div>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="plan-list">
        {yearPlans.length === 0 ? (
          <p className="hint" data-testid="no-plans">
            На {year} год планов нет.
          </p>
        ) : (
          yearPlans.map((row) => (
            <button
              key={row.id}
              type="button"
              className={row.id === selectedId ? 'plan-card active' : 'plan-card'}
              onClick={() => setSelectedId(row.id)}
            >
              <span className="plan-card-title">{row.manager_name}</span>
              <span className={`badge status-${row.status}`}>{row.status_title}</span>
              <span className="plan-card-sum">{formatMoney(row.total_amount)} ₽</span>
            </button>
          ))
        )}
      </div>

      {plan ? (
        <>
          <div className="toolbar">
            {canEdit ? (
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={() => {
                  const items = collectItems()
                  if (items) void run(() => saveSalesPlanItems(plan.id, items))
                }}
              >
                Сохранить
              </button>
            ) : null}
            {canSubmit ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => salesPlanAction(plan.id, 'submit'))}
              >
                Отправить на проверку
              </button>
            ) : null}
            {isCommercialDirector && plan.status === 'draft' ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => salesPlanAction(plan.id, 'send-to-fill'))}
              >
                Отправить на заполнение
              </button>
            ) : null}
            {canApprove ? (
              <>
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={() => run(() => salesPlanAction(plan.id, 'approve'))}
                >
                  Утвердить
                </button>
                <input
                  aria-label="Причина возврата"
                  placeholder="Причина возврата"
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await rejectSalesPlan(plan.id, rejectReason)
                      setRejectReason('')
                    })
                  }
                >
                  Вернуть на доработку
                </button>
              </>
            ) : null}
            {canDelete ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => deleteSalesPlan(plan.id))}
              >
                Удалить
              </button>
            ) : null}
            {isExecutive ? <span className="hint">Просмотр без правок</span> : null}
            <span className="sep" />
            <span className="hint">
              Всего по плану:{' '}
              <strong data-testid="plan-total">{formatMoney(String(total))} ₽</strong>
            </span>
          </div>

          {plan.notes ? <p className="hint">Примечания: {plan.notes}</p> : null}

          <div className="toolbar">
            <select
              aria-label="Добавить товар"
              value={productToAdd}
              onChange={(event) => setProductToAdd(event.target.value)}
            >
              <option value="">— выберите товар —</option>
              {products
                .filter((product) => !rows.some((row) => row.productId === product.id))
                .map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.code} · {product.name}
                  </option>
                ))}
            </select>
            <button type="button" disabled={!productToAdd || !canEdit} onClick={addRow}>
              Добавить строку
            </button>
          </div>

          <table className="plan-table" data-testid="plan-table">
            <thead>
              <tr>
                <th scope="col">Товар</th>
                <th scope="col" className="num">
                  Цена, ₽
                </th>
                {MONTH_SHORT.map((title, index) => (
                  <th key={title} scope="col" className="num" title={MONTH_TITLES[index]}>
                    {title}
                  </th>
                ))}
                <th scope="col" className="num">
                  Сумма, ₽
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={15} className="hint" data-testid="plan-empty">
                    Строк пока нет — добавьте товар.
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.productId}>
                    <td>
                      {row.code} · {row.name}
                      <span className="unit">, {row.unit}</span>
                    </td>
                    <td className="num">
                      <input
                        className="cell"
                        aria-label={`Цена ${row.code}`}
                        value={row.price}
                        disabled={!canEdit}
                        onChange={(event) => setPrice(row.productId, event.target.value)}
                      />
                    </td>
                    {MONTH_SHORT.map((title, index) => {
                      const month = index + 1
                      const frozen = !editable.includes(month)
                      return (
                        <td key={title} className="num">
                          <input
                            className="cell"
                            aria-label={`${row.code} ${MONTH_TITLES[index]}`}
                            title={frozen ? 'Месяц заморожен' : MONTH_TITLES[index]}
                            value={row.months[month] ?? ''}
                            disabled={!canEdit || frozen}
                            onChange={(event) => setMonth(row.productId, month, event.target.value)}
                          />
                        </td>
                      )
                    })}
                    <td className="num">{formatMoney(String(rowTotal(row)))}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </>
      ) : null}
    </section>
  )
}
