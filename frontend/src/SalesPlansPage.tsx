import { useCallback, useEffect, useState } from 'react'
import {
  approveSalesPlanCorrection,
  type Counterparty,
  createSalesPlan,
  createSalesPlanCorrection,
  deleteSalesPlan,
  deleteSalesPlanCorrection,
  errorMessage,
  fetchCounterparties,
  fetchProducts,
  fetchSalesPlanCorrections,
  fetchSalesPlans,
  fetchUsers,
  formatQuantity,
  MONTH_SHORT,
  MONTH_TITLES,
  type Product,
  rejectSalesPlan,
  rejectSalesPlanCorrection,
  type SalesPlan,
  type SalesPlanCorrection,
  type SalesPlanCorrectionItemIn,
  type SalesPlanItemIn,
  type SessionUser,
  salesPlanAction,
  saveSalesPlanCorrectionItems,
  saveSalesPlanItems,
  submitSalesPlanCorrection,
} from './api'

type DraftRow = {
  productId: string
  code: string
  name: string
  unit: string
  months: Record<number, string>
}

/** Черновики строк по клиентам: ключ — id клиента. */
type Drafts = Record<string, DraftRow[]>

const QTY_PATTERN = /^\d+(?:[.,]\d{1,3})?$/

function normalize(raw: string): string {
  return raw.trim().replace(',', '.')
}

/** «10.000» → «10», «15.500» → «15.5»: в поле ввода лишние нули не нужны. */
function trimQuantity(raw: string): string {
  return raw.includes('.') ? raw.replace(/\.?0+$/, '') : raw
}

function draftsFromPlan(plan: SalesPlan): Drafts {
  const drafts: Drafts = {}
  for (const item of plan.items) {
    const rows = drafts[item.client_id] ?? []
    let row = rows.find((candidate) => candidate.productId === item.product_id)
    if (!row) {
      row = {
        productId: item.product_id,
        code: item.product_code,
        name: item.product_name,
        unit: item.unit,
        months: {},
      }
      rows.push(row)
    }
    if (Number(item.quantity) !== 0) row.months[item.month] = trimQuantity(item.quantity)
    drafts[item.client_id] = rows
  }
  for (const rows of Object.values(drafts)) {
    rows.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  }
  return drafts
}

function correctionKey(clientId: string, productId: string, month: number): string {
  return `${clientId}|${productId}|${month}`
}

/** Полная копия плана для корректировки: план + правки черновика. */
function draftsFromCorrection(plan: SalesPlan, correction: SalesPlanCorrection): Drafts {
  const drafts = draftsFromPlan(plan)
  const editable = new Set(plan.editable_months)
  for (const item of correction.items) {
    if (!editable.has(item.month)) continue
    const rows = drafts[item.client_id] ?? []
    let row = rows.find((candidate) => candidate.productId === item.product_id)
    if (!row) {
      row = {
        productId: item.product_id,
        code: item.product_code,
        name: item.product_name,
        unit: item.unit,
        months: {},
      }
      rows.push(row)
    }
    if (Number(item.quantity) > 0) {
      row.months[item.month] = trimQuantity(item.quantity)
    } else {
      delete row.months[item.month]
    }
    drafts[item.client_id] = rows
  }
  for (const [clientId, rows] of Object.entries(drafts)) {
    const kept = rows.filter((row) => Object.keys(row.months).length > 0)
    if (kept.length === 0) {
      delete drafts[clientId]
    } else {
      drafts[clientId] = kept.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
    }
  }
  return drafts
}

/**
 * Полный набор строк корректировки. Для каждой строки плана на редактируемых
 * месяцах присылаем значение или 0 (удаление), поэтому сервер видит полную копию
 * и заменяет ею редактируемые месяцы, а не только перечисленные изменения.
 */
function collectCorrectionItems(
  plan: SalesPlan,
  drafts: Drafts,
  onError: (message: string) => void,
): SalesPlanCorrectionItemIn[] | null {
  const editable = plan.editable_months
  const planKeys = new Map<string, { clientId: string; productId: string; month: number }>()
  for (const item of plan.items) {
    if (!editable.includes(item.month)) continue
    planKeys.set(correctionKey(item.client_id, item.product_id, item.month), {
      clientId: item.client_id,
      productId: item.product_id,
      month: item.month,
    })
  }

  const items: SalesPlanCorrectionItemIn[] = []
  const sent = new Set<string>()
  for (const [clientId, rows] of Object.entries(drafts)) {
    for (const row of rows) {
      for (const month of editable) {
        const key = correctionKey(clientId, row.productId, month)
        const raw = normalize(row.months[month] ?? '')
        if (raw === '') {
          if (planKeys.has(key)) {
            items.push({ client_id: clientId, product_id: row.productId, month, quantity: '0' })
            sent.add(key)
          }
          continue
        }
        if (!QTY_PATTERN.test(raw)) {
          onError(`Количество «${row.months[month]}» в строке ${row.name} — не число`)
          return null
        }
        if (Number(raw) > 0) {
          items.push({ client_id: clientId, product_id: row.productId, month, quantity: raw })
          sent.add(key)
        } else if (planKeys.has(key)) {
          items.push({ client_id: clientId, product_id: row.productId, month, quantity: '0' })
          sent.add(key)
        }
      }
    }
  }
  for (const [key, parts] of planKeys) {
    if (sent.has(key)) continue
    items.push({
      client_id: parts.clientId,
      product_id: parts.productId,
      month: parts.month,
      quantity: '0',
    })
  }
  return items
}

/** Сколько строк черновика отличаются от утверждённого плана (для подсказки). */
function countCorrectionChanges(plan: SalesPlan, drafts: Drafts): number {
  const items = collectCorrectionItems(plan, drafts, () => {})
  if (items === null) return 0
  const planQuantities = new Map<string, string>()
  for (const item of plan.items) {
    if (!plan.editable_months.includes(item.month)) continue
    planQuantities.set(correctionKey(item.client_id, item.product_id, item.month), item.quantity)
  }
  return items.filter((item) => {
    const key = correctionKey(item.client_id, item.product_id, item.month)
    return Number(item.quantity) !== Number(planQuantities.get(key) ?? 0)
  }).length
}

export function SalesPlansPage({ user }: { user: SessionUser }) {
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(thisYear)
  const [plans, setPlans] = useState<SalesPlan[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Drafts>({})
  const [clientId, setClientId] = useState<string>('')
  const [products, setProducts] = useState<Product[]>([])
  const [clients, setClients] = useState<Counterparty[]>([])
  const [managers, setManagers] = useState<SessionUser[]>([])
  const [managerId, setManagerId] = useState('')
  const [productToAdd, setProductToAdd] = useState('')
  const [clientToAdd, setClientToAdd] = useState('')
  const [rejectReason, setRejectReason] = useState('')
  const [corrections, setCorrections] = useState<SalesPlanCorrection[]>([])
  const [correction, setCorrection] = useState<SalesPlanCorrection | null>(null)
  const [correctionDrafts, setCorrectionDrafts] = useState<Drafts>({})
  const [correctionClientId, setCorrectionClientId] = useState('')
  const [correctionClientToAdd, setCorrectionClientToAdd] = useState('')
  const [correctionProductToAdd, setCorrectionProductToAdd] = useState('')
  const [correctionReason, setCorrectionReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isCommercialDirector = user.role === 'commercial_director'
  const isExecutive = user.role === 'executive_director'
  const yearPlans = plans.filter((plan) => plan.year === year)
  const plan = yearPlans.find((row) => row.id === selectedId) ?? null
  const isOwner = plan !== null && plan.manager_id === user.id

  const clientName = (id: string): string => clients.find((row) => row.id === id)?.name ?? 'Клиент'
  const activeClients = clients.filter((row) => row.is_active)

  const reload = useCallback(async () => {
    try {
      const loaded = await fetchSalesPlans()
      setPlans(loaded)
      setSelectedId((current) =>
        current && loaded.some((row) => row.id === current) ? current : (loaded[0]?.id ?? null),
      )
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void reload()
    fetchProducts()
      .then((rows) => setProducts(rows.filter((product) => product.is_active)))
      .catch(() => setProducts([]))
    fetchCounterparties({ role: 'customer', includeInactive: true })
      .then(setClients)
      .catch(() => setClients([]))
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
    const next = plan ? draftsFromPlan(plan) : {}
    setDrafts(next)
    setClientId((current) => {
      if (current && next[current]) return current
      return Object.keys(next)[0] ?? ''
    })
  }, [plan])

  useEffect(() => {
    if (!plan || !(isOwner || isCommercialDirector || isExecutive)) {
      setCorrections([])
      setCorrection(null)
      setCorrectionDrafts({})
      setCorrectionClientId('')
      return
    }
    fetchSalesPlanCorrections(plan.id)
      .then((rows) => {
        setCorrections(rows)
        const open =
          rows.find((row) => row.status === 'draft' || row.status === 'on_review') ??
          rows[0] ??
          null
        setCorrection(open)
        const next = open?.status === 'draft' ? draftsFromCorrection(plan, open) : {}
        setCorrectionDrafts(next)
        setCorrectionClientId((current) =>
          current && next[current] ? current : (Object.keys(next)[0] ?? ''),
        )
      })
      .catch(() => {
        setCorrections([])
        setCorrection(null)
        setCorrectionDrafts({})
        setCorrectionClientId('')
      })
  }, [plan, isOwner, isCommercialDirector, isExecutive])

  const run = async (action: () => Promise<unknown>, message?: string) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await action()
      await reload()
      if (message) setNotice(message)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const editable = plan?.editable_months ?? []
  const rows = clientId ? (drafts[clientId] ?? []) : []

  const setRows = (updater: (current: DraftRow[]) => DraftRow[]) => {
    setDrafts((current) => ({ ...current, [clientId]: updater(current[clientId] ?? []) }))
  }

  const collectItems = (): SalesPlanItemIn[] | null => {
    const items: SalesPlanItemIn[] = []
    for (const [currentClientId, clientRows] of Object.entries(drafts)) {
      for (const row of clientRows) {
        for (const month of editable) {
          const raw = normalize(row.months[month] ?? '')
          if (raw === '') continue
          if (!QTY_PATTERN.test(raw)) {
            setError(
              `Количество «${row.months[month]}» в строке ${row.name} (${clientName(currentClientId)}) — не число`,
            )
            return null
          }
          items.push({
            client_id: currentClientId,
            product_id: row.productId,
            month,
            quantity: raw,
          })
        }
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

  const addRow = () => {
    const product = products.find((row) => row.id === productToAdd)
    if (!product || !clientId) return
    setRows((current) => [
      ...current,
      {
        productId: product.id,
        code: product.code,
        name: product.name,
        unit: product.unit,
        months: {},
      },
    ])
    setProductToAdd('')
  }

  const addClientToPlan = () => {
    if (!clientToAdd) return
    setDrafts((current) => ({ ...current, [clientToAdd]: current[clientToAdd] ?? [] }))
    setClientId(clientToAdd)
    setClientToAdd('')
  }

  /** Итог строки — сумма месяцев: единица измерения у строки одна, складывать корректно. */
  const rowQuantity = (row: DraftRow): number =>
    editable.reduce((sum, month) => sum + Number(normalize(row.months[month] ?? '') || 0), 0)

  const planClients = Object.keys(drafts)
  const canEdit =
    plan !== null &&
    plan.status !== 'approved' &&
    (isCommercialDirector || (isOwner && ['draft', 'filling'].includes(plan.status)))
  const canSubmit = plan !== null && isOwner && ['draft', 'filling'].includes(plan.status)
  const canApprove = plan !== null && isCommercialDirector && plan.status === 'on_review'
  const canDelete =
    plan !== null && ['draft', 'filling'].includes(plan.status) && (isCommercialDirector || isOwner)

  const openCorrection =
    corrections.find((row) => row.status === 'draft' || row.status === 'on_review') ?? null
  const canProposeCorrection = isOwner || isCommercialDirector || isExecutive
  const canCreateCorrection =
    plan !== null && canProposeCorrection && plan.status === 'approved' && openCorrection === null
  const correctionEditable =
    correction !== null && correction.status === 'draft' && canProposeCorrection
  const canReviewCorrection =
    correction !== null && correction.status === 'on_review' && isCommercialDirector

  const correctionEditableMonths = plan?.editable_months ?? []
  const correctionClients = Object.keys(correctionDrafts)
  const correctionRows = correctionClientId ? (correctionDrafts[correctionClientId] ?? []) : []
  const correctionChanged =
    correction?.items.filter((item) => Number(item.quantity) !== Number(item.current_quantity)) ??
    []
  const correctionDraftChanged =
    plan && correction?.status === 'draft' ? countCorrectionChanges(plan, correctionDrafts) : 0

  const setCorrectionRows = (updater: (current: DraftRow[]) => DraftRow[]) => {
    setCorrectionDrafts((current) => ({
      ...current,
      [correctionClientId]: updater(current[correctionClientId] ?? []),
    }))
  }

  const setCorrectionMonth = (productId: string, month: number, value: string) => {
    setCorrectionRows((current) =>
      current.map((row) =>
        row.productId === productId ? { ...row, months: { ...row.months, [month]: value } } : row,
      ),
    )
  }

  const addCorrectionClient = () => {
    if (!correctionClientToAdd) return
    setCorrectionDrafts((current) => ({
      ...current,
      [correctionClientToAdd]: current[correctionClientToAdd] ?? [],
    }))
    setCorrectionClientId(correctionClientToAdd)
    setCorrectionClientToAdd('')
  }

  const removeCorrectionClient = () => {
    if (!correctionClientId) return
    const hasFrozen = (correctionDrafts[correctionClientId] ?? []).some((row) =>
      Object.keys(row.months).some((month) => !correctionEditableMonths.includes(Number(month))),
    )
    if (hasFrozen) {
      setError('У клиента есть замороженные месяцы — удалить его из корректировки нельзя')
      return
    }
    if (!confirm(`Убрать клиента «${clientName(correctionClientId)}» из корректировки?`)) return
    setCorrectionDrafts((current) => {
      const next = { ...current }
      delete next[correctionClientId]
      return next
    })
    setCorrectionClientId('')
  }

  const addCorrectionRow = () => {
    const product = products.find((row) => row.id === correctionProductToAdd)
    if (!product || !correctionClientId) return
    if (correctionRows.some((row) => row.productId === product.id)) return
    setCorrectionRows((current) => [
      ...current,
      {
        productId: product.id,
        code: product.code,
        name: product.name,
        unit: product.unit,
        months: {},
      },
    ])
    setCorrectionProductToAdd('')
  }

  const removeCorrectionRow = (productId: string) => {
    const row = correctionRows.find((candidate) => candidate.productId === productId)
    const hasFrozen =
      row !== undefined &&
      Object.keys(row.months).some((month) => !correctionEditableMonths.includes(Number(month)))
    if (hasFrozen) {
      setError('У позиции есть замороженные месяцы — удалить её из корректировки нельзя')
      return
    }
    setCorrectionRows((current) => current.filter((candidate) => candidate.productId !== productId))
  }

  const correctionRowQuantity = (row: DraftRow): number =>
    correctionEditableMonths.reduce(
      (sum, month) => sum + Number(normalize(row.months[month] ?? '') || 0),
      0,
    )

  const startCorrection = () => {
    if (!plan) return
    void run(async () => {
      const created = await createSalesPlanCorrection(plan.id)
      setCorrections((current) => [created, ...current])
      setCorrection(created)
      const next = draftsFromCorrection(plan, created)
      setCorrectionDrafts(next)
      setCorrectionClientId(Object.keys(next)[0] ?? '')
    }, 'Черновик корректировки создан')
  }

  const saveCorrection = () => {
    if (!plan || !correction) return
    const items = collectCorrectionItems(plan, correctionDrafts, setError)
    if (!items) return
    void run(async () => {
      const updated = await saveSalesPlanCorrectionItems(correction.id, items)
      setCorrection(updated)
      const next = draftsFromCorrection(plan, updated)
      setCorrectionDrafts(next)
      setCorrectionClientId((current) =>
        current && next[current] ? current : (Object.keys(next)[0] ?? ''),
      )
    }, 'Корректировка сохранена')
  }

  const sendCorrection = () => {
    if (!plan || !correction) return
    const items = collectCorrectionItems(plan, correctionDrafts, setError)
    if (!items) return
    void run(async () => {
      await saveSalesPlanCorrectionItems(correction.id, items)
      const submitted = await submitSalesPlanCorrection(correction.id)
      setCorrection(submitted)
      setCorrectionDrafts({})
      setCorrectionClientId('')
    }, 'Корректировка отправлена коммерческому директору')
  }

  const cancelCorrection = () => {
    if (!correction) return
    if (!confirm('Отменить корректировку?')) return
    void run(async () => {
      await deleteSalesPlanCorrection(correction.id)
      setCorrection(null)
      setCorrectionDrafts({})
      setCorrectionClientId('')
    }, 'Корректировка отменена')
  }

  const approveCorrection = () => {
    if (!correction) return
    void run(
      () => approveSalesPlanCorrection(correction.id),
      'Корректировка утверждена — годовой план отдела требует повторного согласования',
    )
  }

  const rejectCorrection = () => {
    if (!correction) return
    void run(async () => {
      await rejectSalesPlanCorrection(correction.id, correctionReason)
      setCorrectionReason('')
    }, 'Корректировка отклонена')
  }

  return (
    <section>
      <header className="page-head">
        <h1>Планирование продаж</h1>
        <p className="hint">
          Годовой план на менеджера: клиент × товар × месяц, только количество. Утверждает
          коммерческий директор.
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
          ) : user.role === 'sales_manager' ? (
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
          ) : null}
        </div>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="hint saved" data-testid="sales-plan-notice">
          {notice}
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
              <span className="plan-card-sum">
                строк: {row.items.length}, клиентов:{' '}
                {new Set(row.items.map((item) => item.client_id)).size}
              </span>
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
          </div>

          {plan.notes ? <p className="hint">Примечания: {plan.notes}</p> : null}

          {correction || canCreateCorrection ? (
            <div className="correction-box" data-testid="correction-box">
              <div className="toolbar">
                <h2>Корректировка утверждённого плана</h2>
                {correction ? (
                  <span className={`badge status-${correction.status}`}>
                    {correction.status_title}
                  </span>
                ) : null}
                <span className="sep" />
                {canCreateCorrection ? (
                  <button
                    type="button"
                    className="primary"
                    disabled={busy}
                    onClick={startCorrection}
                  >
                    {isCommercialDirector
                      ? 'Исправить утверждённый план'
                      : 'Предложить корректировку'}
                  </button>
                ) : null}
              </div>

              {correction ? (
                <>
                  {correction.review_reason ? (
                    <p className="hint warn">Причина отклонения: {correction.review_reason}</p>
                  ) : null}
                  <p className="hint">
                    Полная копия плана: можно менять объёмы, добавлять и удалять клиентов и товары.
                    Замороженные месяцы недоступны.
                  </p>

                  {correctionEditable ? (
                    <>
                      <div className="toolbar">
                        <span className="hint">Клиент:</span>
                        {correctionClients.length === 0 ? (
                          <span className="hint" data-testid="correction-no-clients">
                            в корректировке нет клиентов — добавьте клиента
                          </span>
                        ) : (
                          correctionClients.map((id) => (
                            <button
                              key={id}
                              type="button"
                              className={id === correctionClientId ? 'chip active' : 'chip'}
                              onClick={() => setCorrectionClientId(id)}
                            >
                              {clientName(id)}
                            </button>
                          ))
                        )}
                        <span className="sep" />
                        <select
                          aria-label="Добавить клиента в корректировку"
                          value={correctionClientToAdd}
                          onChange={(event) => setCorrectionClientToAdd(event.target.value)}
                          disabled={busy}
                        >
                          <option value="">— добавить клиента —</option>
                          {activeClients
                            .filter(
                              (row) =>
                                !correctionClients.includes(row.id) ||
                                row.id === correctionClientToAdd,
                            )
                            .map((row) => (
                              <option key={row.id} value={row.id}>
                                {row.name}
                              </option>
                            ))}
                        </select>
                        <button
                          type="button"
                          disabled={busy || !correctionClientToAdd}
                          onClick={addCorrectionClient}
                        >
                          Добавить
                        </button>
                        <button
                          type="button"
                          disabled={busy || !correctionClientId}
                          onClick={removeCorrectionClient}
                        >
                          Убрать клиента
                        </button>
                      </div>

                      <div className="toolbar">
                        <select
                          aria-label="Добавить товар в корректировку"
                          value={correctionProductToAdd}
                          onChange={(event) => setCorrectionProductToAdd(event.target.value)}
                          disabled={busy || !correctionClientId}
                        >
                          <option value="">— выберите товар —</option>
                          {products
                            .filter(
                              (product) =>
                                !correctionRows.some((row) => row.productId === product.id),
                            )
                            .map((product) => (
                              <option key={product.id} value={product.id}>
                                {product.code} · {product.name}
                              </option>
                            ))}
                        </select>
                        <button
                          type="button"
                          disabled={busy || !correctionProductToAdd || !correctionClientId}
                          onClick={addCorrectionRow}
                        >
                          Добавить строку
                        </button>
                        <span className="sep" />
                        <span className="hint" data-testid="correction-current-client">
                          {correctionClientId
                            ? `Строки клиента: ${clientName(correctionClientId)}`
                            : 'клиент не выбран'}
                        </span>
                        <span className="hint" data-testid="correction-changed-count">
                          изменено строк: {correctionDraftChanged}
                        </span>
                      </div>

                      <table className="plan-table" data-testid="correction-table">
                        <thead>
                          <tr>
                            <th scope="col">Товар</th>
                            {MONTH_SHORT.map((title, index) => (
                              <th
                                key={title}
                                scope="col"
                                className="num"
                                title={MONTH_TITLES[index]}
                              >
                                {title}
                              </th>
                            ))}
                            <th scope="col" className="num">
                              Итого
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {correctionRows.length === 0 ? (
                            <tr>
                              <td colSpan={14} className="hint" data-testid="correction-empty">
                                {correctionClientId
                                  ? 'У клиента пока нет строк — добавьте товар.'
                                  : 'Добавьте клиента в корректировку.'}
                              </td>
                            </tr>
                          ) : (
                            correctionRows.map((row) => (
                              <tr key={row.productId}>
                                <td>
                                  {row.code} · {row.name}
                                  <span className="unit">, {row.unit}</span>
                                  <button
                                    type="button"
                                    className="mini correction-remove"
                                    aria-label={`Убрать строку ${row.name}`}
                                    title="Убрать строку"
                                    disabled={busy}
                                    onClick={() => removeCorrectionRow(row.productId)}
                                  >
                                    Убрать
                                  </button>
                                </td>
                                {MONTH_SHORT.map((title, index) => {
                                  const month = index + 1
                                  const frozen = !correctionEditableMonths.includes(month)
                                  return (
                                    <td key={title} className="num">
                                      <input
                                        className="cell"
                                        aria-label={`Корректировка ${row.code} ${MONTH_TITLES[index]}`}
                                        title={frozen ? 'Месяц заморожен' : MONTH_TITLES[index]}
                                        value={row.months[month] ?? ''}
                                        disabled={busy || frozen}
                                        onChange={(event) =>
                                          setCorrectionMonth(
                                            row.productId,
                                            month,
                                            event.target.value,
                                          )
                                        }
                                      />
                                    </td>
                                  )
                                })}
                                <td className="num" data-testid={`correction-total-${row.code}`}>
                                  {formatQuantity(String(correctionRowQuantity(row)))} {row.unit}
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>

                      <div className="toolbar">
                        <button
                          type="button"
                          className="primary"
                          disabled={busy}
                          onClick={saveCorrection}
                        >
                          Сохранить
                        </button>
                        <button
                          type="button"
                          disabled={busy || correctionDraftChanged === 0}
                          onClick={sendCorrection}
                        >
                          Отправить коммерческому директору
                        </button>
                        <button type="button" disabled={busy} onClick={cancelCorrection}>
                          Отменить
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="purchase-table">
                      <table data-testid="correction-readonly">
                        <thead>
                          <tr>
                            <th scope="col">Клиент</th>
                            <th scope="col">Товар</th>
                            <th scope="col">Месяц</th>
                            <th scope="col" className="num">
                              Было
                            </th>
                            <th scope="col" className="num">
                              Стало
                            </th>
                            <th scope="col">Примечание</th>
                          </tr>
                        </thead>
                        <tbody>
                          {correctionChanged.length === 0 ? (
                            <tr>
                              <td colSpan={6} className="hint">
                                Изменений нет.
                              </td>
                            </tr>
                          ) : (
                            correctionChanged.map((item) => (
                              <tr key={item.id}>
                                <td>{item.client_name}</td>
                                <td>
                                  {item.product_code} · {item.product_name}
                                  <span className="unit">, {item.unit}</span>
                                </td>
                                <td>{MONTH_TITLES[item.month - 1]}</td>
                                <td className="num">
                                  {formatQuantity(item.current_quantity)} {item.unit}
                                </td>
                                <td className="num">
                                  {Number(item.quantity) === 0
                                    ? 'удалить'
                                    : `${formatQuantity(item.quantity)} ${item.unit}`}
                                </td>
                                <td>{item.notes ?? '—'}</td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {canReviewCorrection ? (
                    <div className="toolbar">
                      <button
                        type="button"
                        className="primary"
                        disabled={busy}
                        onClick={approveCorrection}
                      >
                        Утвердить корректировку
                      </button>
                      <input
                        aria-label="Причина отклонения"
                        placeholder="Причина отклонения"
                        value={correctionReason}
                        onChange={(event) => setCorrectionReason(event.target.value)}
                      />
                      <button type="button" disabled={busy} onClick={rejectCorrection}>
                        Отклонить
                      </button>
                    </div>
                  ) : null}

                  {correction.status === 'approved' ? (
                    <p className="hint saved">
                      Изменения применены к плану.
                      {correction.annual_needs_reapproval
                        ? ' Годовой план отдела нужно отправить на финальное согласование заново.'
                        : ''}
                    </p>
                  ) : null}
                  {correction.status === 'rejected' ? (
                    <p className="hint warn">
                      Корректировка отклонена, план не изменён. Можно создать новую.
                    </p>
                  ) : null}
                </>
              ) : (
                <p className="hint">
                  Утверждённый план нельзя править напрямую — создайте корректировку: в ней можно
                  менять объёмы и состав позиций.
                </p>
              )}
            </div>
          ) : null}

          {correctionEditable ? null : (
            <>
              <div className="toolbar">
                <span className="hint">Клиент:</span>
                {planClients.length === 0 ? (
                  <span className="hint" data-testid="plan-no-clients">
                    в плане пока нет клиентов — добавьте клиента
                  </span>
                ) : (
                  planClients.map((id) => (
                    <button
                      key={id}
                      type="button"
                      className={id === clientId ? 'chip active' : 'chip'}
                      onClick={() => setClientId(id)}
                    >
                      {clientName(id)}
                    </button>
                  ))
                )}
                <span className="sep" />
                <select
                  aria-label="Добавить клиента"
                  value={clientToAdd}
                  onChange={(event) => setClientToAdd(event.target.value)}
                  disabled={!canEdit}
                >
                  <option value="">— добавить клиента —</option>
                  {activeClients
                    .filter((row) => !planClients.includes(row.id) || row.id === clientToAdd)
                    .map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.name}
                      </option>
                    ))}
                </select>
                <button type="button" disabled={!clientToAdd || !canEdit} onClick={addClientToPlan}>
                  Добавить
                </button>
              </div>

              <div className="toolbar">
                <select
                  aria-label="Добавить товар"
                  value={productToAdd}
                  onChange={(event) => setProductToAdd(event.target.value)}
                  disabled={!canEdit || !clientId}
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
                <span className="sep" />
                <span className="hint" data-testid="current-client">
                  {clientId ? `Строки клиента: ${clientName(clientId)}` : 'клиент не выбран'}
                </span>
              </div>

              <table className="plan-table" data-testid="plan-table">
                <thead>
                  <tr>
                    <th scope="col">Товар</th>
                    {MONTH_SHORT.map((title, index) => (
                      <th key={title} scope="col" className="num" title={MONTH_TITLES[index]}>
                        {title}
                      </th>
                    ))}
                    <th scope="col" className="num">
                      Итого
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 ? (
                    <tr>
                      <td colSpan={14} className="hint" data-testid="plan-empty">
                        {clientId
                          ? 'Строк по этому клиенту пока нет — добавьте товар.'
                          : 'Добавьте клиента в план.'}
                      </td>
                    </tr>
                  ) : (
                    rows.map((row) => (
                      <tr key={row.productId}>
                        <td>
                          {row.code} · {row.name}
                          <span className="unit">, {row.unit}</span>
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
                                onChange={(event) =>
                                  setMonth(row.productId, month, event.target.value)
                                }
                              />
                            </td>
                          )
                        })}
                        <td className="num" data-testid={`row-total-${row.code}`}>
                          {formatQuantity(String(rowQuantity(row)))} {row.unit}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </>
          )}
        </>
      ) : null}
    </section>
  )
}
