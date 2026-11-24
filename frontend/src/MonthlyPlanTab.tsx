import { type ReactNode, useEffect, useState } from 'react'
import {
  ApiError,
  approveMonthlyPlan,
  type Counterparty,
  errorMessage,
  fetchCounterparties,
  fetchMonthlyPlan,
  fetchMonthlyPlanHistory,
  fetchPlanningProducts,
  fetchUsers,
  formatDate,
  formatQuantity,
  MONTH_TITLES,
  type MonthlyPlan,
  type MonthlyPlanEvent,
  type MonthlyPlanItemIn,
  type Product,
  type SessionUser,
  saveMonthlyPlan,
  scopeOf,
} from './api'

type Draft = { quantity: string; reason: string }
type Drafts = Record<string, Draft>

const QTY_PATTERN = /^\d+(?:[.,]\d{1,3})?$/

function keyOf(clientId: string, productId: string): string {
  return `${clientId}|${productId}`
}

function splitKey(key: string): [string, string] {
  const [clientId = '', productId = ''] = key.split('|')
  return [clientId, productId]
}

function normalize(raw: string): string {
  return raw.trim().replace(',', '.')
}

function trimQuantity(raw: string): string {
  return raw.includes('.') ? raw.replace(/\.?0+$/, '') : raw
}

function draftsFrom(plan: MonthlyPlan): Drafts {
  const drafts: Drafts = {}
  for (const item of plan.items) {
    drafts[keyOf(item.client_id, item.product_id)] = {
      quantity: trimQuantity(item.quantity).replace('.', ','),
      reason: item.reason ?? '',
    }
  }
  return drafts
}

/** Предыдущий месяц для подписи «окно откроется 23 …». */
function previousMonthTitle(month: number): string {
  return MONTH_TITLES[(month + 10) % 12] ?? ''
}

export function MonthlyPlanTab({
  user,
  year,
  managers,
}: {
  user: SessionUser
  year: number
  managers: SessionUser[]
}) {
  const isManager = scopeOf(user, 'monthly_plan') === 'own'
  const [managerId, setManagerId] = useState(isManager ? user.id : '')
  const [managerList, setManagerList] = useState<SessionUser[]>(managers)
  const [month, setMonth] = useState(1)
  const [plan, setPlan] = useState<MonthlyPlan | null>(null)
  const [drafts, setDrafts] = useState<Drafts>({})
  const [history, setHistory] = useState<MonthlyPlanEvent[]>([])
  const [clients, setClients] = useState<Counterparty[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [addClient, setAddClient] = useState('')
  const [addProduct, setAddProduct] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    setManagerList(managers)
  }, [managers])

  useEffect(() => {
    if (isManager) {
      setManagerId(user.id)
      return
    }
    if (managerList.length === 0) {
      fetchUsers('sales_manager')
        .then(setManagerList)
        .catch(() => setManagerList([]))
    }
  }, [isManager, managerList.length, user.id])

  useEffect(() => {
    if (!isManager && !managerId && managerList[0]) setManagerId(managerList[0].id)
  }, [isManager, managerId, managerList])

  useEffect(() => {
    const now = new Date()
    const next = now.getMonth() === 11 ? 1 : now.getMonth() + 2
    setMonth(year === now.getFullYear() ? next : 1)
  }, [year])

  useEffect(() => {
    fetchCounterparties({ role: 'customer', includeInactive: false })
      .then(setClients)
      .catch(() => setClients([]))
    fetchPlanningProducts()
      .then((rows) => setProducts(rows.filter((product) => product.is_active)))
      .catch(() => setProducts([]))
  }, [])

  useEffect(() => {
    if (!managerId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setNotice(null)
    fetchMonthlyPlan(year, month, managerId)
      .then((loaded) => {
        if (cancelled) return
        setPlan(loaded)
        setDrafts(draftsFrom(loaded))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setPlan(null)
        setDrafts({})
        if (err instanceof ApiError && err.status === 409) {
          setNotice(errorMessage(err))
        } else {
          setError(errorMessage(err))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    fetchMonthlyPlanHistory(year, month, managerId)
      .then((rows) => {
        if (!cancelled) setHistory(rows)
      })
      .catch(() => {
        if (!cancelled) setHistory([])
      })
    return () => {
      cancelled = true
    }
  }, [year, month, managerId])

  const editable = plan?.can_edit === true && !busy
  const annualByKey = new Map<string, string>()
  for (const item of plan?.items ?? []) {
    annualByKey.set(keyOf(item.client_id, item.product_id), item.annual_quantity)
  }
  const itemByKey = new Map(
    (plan?.items ?? []).map((item) => [keyOf(item.client_id, item.product_id), item]),
  )
  const clientName = (id: string): string =>
    clients.find((row) => row.id === id)?.name ??
    plan?.items.find((item) => item.client_id === id)?.client_name ??
    'Клиент'
  const productName = (id: string): string =>
    products.find((row) => row.id === id)?.name ??
    plan?.items.find((item) => item.product_id === id)?.product_name ??
    'Позиция'
  const annualOf = (key: string): number => Number(annualByKey.get(key) ?? '0')
  const monthlyOf = (draft: Draft | undefined): number =>
    Number(normalize(draft?.quantity ?? '') || 0)
  const isChanged = (key: string): boolean => {
    const draft = drafts[key]
    return monthlyOf(draft) !== annualOf(key)
  }

  const groups = new Map<string, string[]>()
  for (const key of Object.keys(drafts)) {
    const [clientId] = splitKey(key)
    const rows = groups.get(clientId) ?? []
    rows.push(key)
    groups.set(clientId, rows)
  }
  const groupRows = [...groups.entries()].sort((a, b) =>
    clientName(a[0]).localeCompare(clientName(b[0]), 'ru'),
  )

  const annualTotal = Object.keys(drafts).reduce((sum, key) => sum + annualOf(key), 0)
  const monthlyTotal = Object.keys(drafts).reduce((sum, key) => sum + monthlyOf(drafts[key]), 0)
  const changedLines = Object.keys(drafts).filter((key) => isChanged(key)).length
  const missingReasons = Object.keys(drafts).filter((key) => {
    const below = monthlyOf(drafts[key]) < annualOf(key)
    return below && !(drafts[key]?.reason ?? '').trim()
  }).length

  const setDraft = (key: string, patch: Partial<Draft>) => {
    setDrafts((current) => ({
      ...current,
      [key]: { ...(current[key] ?? { quantity: '', reason: '' }), ...patch },
    }))
  }

  const addRow = () => {
    if (!addClient || !addProduct) return
    const key = keyOf(addClient, addProduct)
    if (drafts[key]) {
      setError('Эта позиция уже есть в плане месяца')
      return
    }
    setDrafts((current) => ({ ...current, [key]: { quantity: '', reason: '' } }))
    setAddProduct('')
  }

  const save = async () => {
    if (!plan) return
    setError(null)
    const payload: MonthlyPlanItemIn[] = []
    for (const [key, draft] of Object.entries(drafts)) {
      const [clientId, productId] = splitKey(key)
      const raw = normalize(draft.quantity)
      const quantity = raw === '' ? '0' : raw
      const exists = itemByKey.has(key)
      if (!exists && raw === '') continue
      if (!QTY_PATTERN.test(quantity)) {
        setError(`Количество «${draft.quantity}» — не число`)
        return
      }
      const quantityNumber = Number(quantity)
      const changed = quantityNumber !== annualOf(key)
      if (quantityNumber < annualOf(key) && !draft.reason.trim()) {
        setError(
          `Укажите причину: «${clientName(clientId)}», ${productName(productId)} — цифра ниже годового плана`,
        )
        return
      }
      payload.push({
        client_id: clientId,
        product_id: productId,
        quantity,
        reason: changed && draft.reason.trim() ? draft.reason.trim() : null,
      })
    }
    setBusy(true)
    try {
      const saved = await saveMonthlyPlan(year, month, payload, plan.manager_id)
      setPlan(saved)
      setDrafts(draftsFrom(saved))
      setNotice('План месяца сохранён')
      const rows = await fetchMonthlyPlanHistory(year, month, plan.manager_id)
      setHistory(rows)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const approve = async () => {
    if (!plan) return
    setBusy(true)
    setError(null)
    try {
      const saved = await approveMonthlyPlan(year, month, plan.manager_id)
      setPlan(saved)
      setDrafts(draftsFrom(saved))
      setNotice('План месяца утверждён')
      const rows = await fetchMonthlyPlanHistory(year, month, plan.manager_id)
      setHistory(rows)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const windowHint = plan
    ? plan.window_state === 'open'
      ? `до ${formatDate(plan.window_end)}`
      : plan.window_state === 'closed'
        ? 'окно закрыто'
        : `окно откроется 23 ${previousMonthTitle(plan.month).toLowerCase()}`
    : ''

  return (
    <div data-testid="monthly-plan">
      <div className="toolbar monthly-toolbar">
        {!isManager ? (
          <select
            aria-label="Менеджер месяца"
            value={managerId}
            onChange={(event) => setManagerId(event.target.value)}
          >
            {managerList.map((row) => (
              <option key={row.id} value={row.id}>
                {row.full_name}
              </option>
            ))}
          </select>
        ) : null}
        <label className="check">
          Месяц
          <select
            aria-label="Месяц плана"
            value={month}
            onChange={(event) => setMonth(Number(event.target.value))}
          >
            {MONTH_TITLES.map((title, index) => (
              <option key={title} value={index + 1}>
                {title}
              </option>
            ))}
          </select>
        </label>
        {plan ? (
          <span
            className={
              plan.status === 'approved' ? 'badge status-approved' : 'badge status-filling'
            }
          >
            {plan.status_title}
          </span>
        ) : null}
        {windowHint ? <span className="hint">{windowHint}</span> : null}
        <div className="monthly-actions">
          {plan?.can_edit ? (
            <button type="button" className="primary" disabled={busy} onClick={() => void save()}>
              Сохранить
            </button>
          ) : null}
          {plan?.can_approve && plan.status === 'draft' ? (
            <button
              type="button"
              className="primary"
              disabled={busy || missingReasons > 0}
              title={missingReasons > 0 ? 'Есть снижение ниже плана без причины' : undefined}
              onClick={() => void approve()}
            >
              Утвердить
            </button>
          ) : null}
        </div>
      </div>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? <p className="hint">{notice}</p> : null}
      {loading ? <p className="hint">Загрузка плана месяца…</p> : null}

      {!loading && !plan ? (
        <div className="empty-state">
          <strong>План месяца ещё не открыт.</strong>
          <span>{notice ?? 'Выберите другой месяц.'}</span>
        </div>
      ) : null}

      {plan ? (
        <>
          <div className="kpis kpis-3 monthly-kpis">
            <div className="kpi">
              <span className="kpi-label">Годовой план на месяц</span>
              <span className="kpi-value">{formatQuantity(String(annualTotal))} кг</span>
              <span className="kpi-sub">из утверждённого годового плана</span>
            </div>
            <div className="kpi kpi-primary">
              <span className="kpi-label">Месячный план</span>
              <span className="kpi-value">{formatQuantity(String(monthlyTotal))} кг</span>
              <span className="kpi-sub">
                {monthlyTotal - annualTotal >= 0 ? '+' : ''}
                {formatQuantity(String(monthlyTotal - annualTotal))} к годовому
              </span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Изменено строк</span>
              <span className="kpi-value">
                {changedLines} из {Object.keys(drafts).length}
              </span>
              <span className={missingReasons > 0 ? 'kpi-sub delta-bad' : 'kpi-sub'}>
                {missingReasons > 0
                  ? `${missingReasons} снижений без причины`
                  : 'обязательные причины заполнены'}
              </span>
            </div>
          </div>

          <div className="table-scroll">
            <table className="monthly-table">
              <thead>
                <tr>
                  <th scope="col">Клиент / позиция</th>
                  <th scope="col" className="num">
                    Годовой план, кг
                  </th>
                  <th scope="col" className="num">
                    Месячный план, кг
                  </th>
                  <th scope="col" className="num">
                    Δ, кг
                  </th>
                  <th scope="col">Причина изменения</th>
                  <th scope="col">Изменено</th>
                </tr>
              </thead>
              <tbody>
                {groupRows.map(([clientId, keys]) => {
                  const groupAnnual = keys.reduce((sum, key) => sum + annualOf(key), 0)
                  const groupMonthly = keys.reduce((sum, key) => sum + monthlyOf(drafts[key]), 0)
                  const groupChanged = keys.filter((key) => isChanged(key)).length
                  return (
                    <FragmentGroup
                      key={clientId}
                      clientName={clientName(clientId)}
                      count={keys.length}
                      annual={groupAnnual}
                      monthly={groupMonthly}
                      changed={groupChanged}
                    >
                      {keys.map((key) => (
                        <MonthlyRow
                          key={key}
                          itemKey={key}
                          draft={drafts[key]}
                          item={itemByKey.get(key)}
                          productName={productName(splitKey(key)[1])}
                          annual={annualOf(key)}
                          changed={isChanged(key)}
                          editable={editable}
                          onChange={(patch) => setDraft(key, patch)}
                        />
                      ))}
                    </FragmentGroup>
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td>Итого · {Object.keys(drafts).length} строк</td>
                  <td className="num">{formatQuantity(String(annualTotal))}</td>
                  <td className="num">{formatQuantity(String(monthlyTotal))}</td>
                  <td className={`num ${monthlyTotal >= annualTotal ? 'delta-good' : 'delta-bad'}`}>
                    {monthlyTotal >= annualTotal ? '+' : ''}
                    {formatQuantity(String(monthlyTotal - annualTotal))}
                  </td>
                  <td>
                    <span className="badge">{changedLines} изменено</span>
                  </td>
                  <td>—</td>
                </tr>
              </tfoot>
            </table>
          </div>

          {editable ? (
            <div className="toolbar monthly-add">
              <select
                aria-label="Клиент новой позиции"
                value={addClient}
                onChange={(event) => setAddClient(event.target.value)}
              >
                <option value="">Клиент</option>
                {clients.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
              <select
                aria-label="Товар новой позиции"
                value={addProduct}
                onChange={(event) => setAddProduct(event.target.value)}
              >
                <option value="">Товар</option>
                {products.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.code} · {row.name}
                  </option>
                ))}
              </select>
              <button type="button" onClick={addRow} disabled={!addClient || !addProduct}>
                Добавить позицию
              </button>
              <span className="hint">Чтобы убрать позицию, поставьте 0 и укажите причину</span>
            </div>
          ) : null}

          <h2 className="section-title">История пересмотра</h2>
          {history.length === 0 ? (
            <p className="hint">Изменений ещё не было.</p>
          ) : (
            <div className="table-scroll">
              <table className="monthly-history">
                <thead>
                  <tr>
                    <th>Когда</th>
                    <th>Кто</th>
                    <th>Строка</th>
                    <th>Было → стало</th>
                    <th>Причина</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((row) => (
                    <tr
                      key={`${row.created_at}-${row.kind}-${row.product_id ?? ''}-${row.new_quantity ?? ''}`}
                    >
                      <td>{formatDate(row.created_at)}</td>
                      <td>{row.actor_name ?? 'Автоматически'}</td>
                      <td>
                        {row.client_name && row.product_name
                          ? `${row.client_name} · ${row.product_name}`
                          : row.kind_title}
                      </td>
                      <td>
                        {row.old_quantity === null
                          ? '—'
                          : `${formatQuantity(row.old_quantity)} → ${row.new_quantity ? formatQuantity(row.new_quantity) : '0'}`}
                      </td>
                      <td>{row.reason ?? row.kind_title}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </div>
  )
}

function FragmentGroup({
  clientName,
  count,
  annual,
  monthly,
  changed,
  children,
}: {
  clientName: string
  count: number
  annual: number
  monthly: number
  changed: number
  children: ReactNode
}) {
  return (
    <>
      <tr className="monthly-group">
        <td>
          {clientName} <span className="hint">· {count} позиций</span>
        </td>
        <td className="num">{formatQuantity(String(annual))}</td>
        <td className="num">{formatQuantity(String(monthly))}</td>
        <td className={`num ${monthly >= annual ? 'delta-good' : 'delta-bad'}`}>
          {monthly >= annual ? '+' : ''}
          {formatQuantity(String(monthly - annual))}
        </td>
        <td>
          {changed > 0 ? (
            <span className="badge">{changed} изменено</span>
          ) : (
            <span className="muted">—</span>
          )}
        </td>
        <td>—</td>
      </tr>
      {children}
    </>
  )
}

function MonthlyRow({
  itemKey,
  draft,
  item,
  productName,
  annual,
  changed,
  editable,
  onChange,
}: {
  itemKey: string
  draft: Draft | undefined
  item: MonthlyPlan['items'][number] | undefined
  productName: string
  annual: number
  changed: boolean
  editable: boolean
  onChange: (patch: Partial<Draft>) => void
}) {
  const monthly = Number(normalize(draft?.quantity ?? '') || 0)
  const delta = monthly - annual
  const isNew = item?.is_new === true
  const removed = annual > 0 && monthly === 0
  const rowClass = [
    changed ? 'monthly-changed' : '',
    isNew ? 'monthly-new' : '',
    removed ? 'monthly-removed' : '',
  ]
    .filter(Boolean)
    .join(' ')
  const deltaClass = delta > 0 ? 'delta-good' : delta < 0 ? 'delta-bad' : 'muted'
  return (
    <tr className={rowClass} data-key={itemKey}>
      <td className="monthly-product">
        {productName}
        {isNew ? <span className="badge">новая</span> : null}
        {removed ? <span className="badge">выведена</span> : null}
        {item && !productName.toLowerCase().includes(item.unit.toLowerCase()) ? (
          <span className="hint"> {item.unit}</span>
        ) : null}
      </td>
      <td className="num">{isNew && annual === 0 ? '—' : formatQuantity(String(annual))}</td>
      <td>
        <input
          className="cell monthly-qty"
          aria-label={`Количество ${productName}`}
          value={draft?.quantity ?? ''}
          disabled={!editable}
          onChange={(event) => onChange({ quantity: event.target.value })}
        />
      </td>
      <td className={`num ${deltaClass}`}>
        {delta === 0 ? '0' : `${delta > 0 ? '+' : ''}${formatQuantity(String(delta))}`}
      </td>
      <td>
        <input
          className="monthly-reason"
          aria-label={`Причина ${productName}`}
          value={draft?.reason ?? ''}
          disabled={!editable || !changed}
          placeholder={changed ? (monthly < annual ? 'Причина обязательна' : 'Необязательно') : '—'}
          onChange={(event) => onChange({ reason: event.target.value })}
        />
      </td>
      <td className="hint">
        {item && (changed || item.reason) ? formatDate(item.updated_at) : '—'}
      </td>
    </tr>
  )
}
