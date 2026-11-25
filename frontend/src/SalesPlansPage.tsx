import { useCallback, useEffect, useRef, useState } from 'react'
import {
  approveSalesPlanCorrection,
  type Counterparty,
  can,
  canManageAll,
  createSalesPlan,
  createSalesPlanCorrection,
  deleteSalesPlan,
  deleteSalesPlanCorrection,
  errorMessage,
  fetchCounterparties,
  fetchManagers,
  fetchPlanningProducts,
  fetchSalesPlanCorrections,
  fetchSalesPlans,
  formatQuantity,
  MONTH_SHORT,
  MONTH_TITLES,
  type Product,
  rejectSalesPlan,
  rejectSalesPlanCorrection,
  type SalesPlan,
  type SalesPlanCorrection,
  type SalesPlanCorrectionItemIn,
  type SalesPlanDraftRowIn,
  type SalesPlanItemIn,
  type SessionUser,
  salesPlanAction,
  saveSalesPlanCorrectionItems,
  saveSalesPlanItems,
  scopeFor,
  submitSalesPlanCorrection,
} from './api'
import { MonthlyPlanTab } from './MonthlyPlanTab'
import { PageHelp } from './PageHelp'
import { SearchSelect } from './SearchSelect'

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
  // Клиенты и позиции, добавленные в черновик до ввода количеств.
  for (const client of plan.draft_clients ?? []) {
    drafts[client.client_id] = drafts[client.client_id] ?? []
  }
  for (const saved of plan.draft_rows ?? []) {
    const rows = drafts[saved.client_id] ?? []
    if (!rows.some((candidate) => candidate.productId === saved.product_id)) {
      rows.push({
        productId: saved.product_id,
        code: saved.product_code,
        name: saved.product_name,
        unit: saved.unit,
        months: {},
      })
    }
    drafts[saved.client_id] = rows
  }
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

/** Состав черновика для автосохранения: клиенты и позиции, даже пустые. */
function draftRowsOf(drafts: Drafts): SalesPlanDraftRowIn[] {
  const seen = new Set<string>()
  const rows: SalesPlanDraftRowIn[] = []
  for (const [clientId, clientRows] of Object.entries(drafts)) {
    for (const row of clientRows) {
      const key = `${clientId}|${row.productId}`
      if (seen.has(key)) continue
      seen.add(key)
      rows.push({ client_id: clientId, product_id: row.productId })
    }
  }
  return rows
}

function draftClientsOf(drafts: Drafts): string[] {
  return Object.keys(drafts)
}

type DraftPayload = {
  items: SalesPlanItemIn[]
  rows: SalesPlanDraftRowIn[]
  clients: string[]
}

/**
 * Полный снимок черновика. Количества — только заполненные; состав строк и
 * клиентов уходит всегда, поэтому пустые позиции не исчезают при сохранении.
 */
function buildDraftPayload(
  plan: SalesPlan,
  drafts: Drafts,
  clientName: (id: string) => string,
  onError?: (message: string) => void,
): DraftPayload | null {
  const items: SalesPlanItemIn[] = []
  for (const [currentClientId, clientRows] of Object.entries(drafts)) {
    for (const row of clientRows) {
      for (const month of plan.editable_months) {
        const raw = normalize(row.months[month] ?? '')
        if (raw === '') continue
        if (!QTY_PATTERN.test(raw)) {
          onError?.(
            `Количество «${row.months[month]}» в строке ${row.name} (${clientName(currentClientId)}) — не число`,
          )
          return null
        }
        // Ноль — это очистка ячейки. Строка останется в составе черновика.
        if (Number(raw) === 0) continue
        items.push({
          client_id: currentClientId,
          product_id: row.productId,
          month,
          quantity: raw,
        })
      }
    }
  }

  const rows = draftRowsOf(drafts)
  const clients = draftClientsOf(drafts)
  if (rows.length === 0 && plan.items.length > 0) {
    // Защита от гонки загрузки: форма не должна отправить пустой состав
    // вместо уже сохранённых строк.
    onError?.('Состав плана не загрузился — обновите страницу, чтобы не потерять строки')
    return null
  }
  return { items, rows, clients }
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

function PlanModeTabs({
  mode,
  onChange,
}: {
  mode: 'year' | 'month'
  onChange: (mode: 'year' | 'month') => void
}) {
  return (
    <div className="mode-tabs" role="tablist" aria-label="Режим планирования">
      <button
        type="button"
        role="tab"
        aria-selected={mode === 'year'}
        className={mode === 'year' ? 'mode-tab active' : 'mode-tab'}
        onClick={() => onChange('year')}
      >
        Год
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={mode === 'month'}
        className={mode === 'month' ? 'mode-tab active' : 'mode-tab'}
        onClick={() => onChange('month')}
      >
        Месяц
      </button>
    </div>
  )
}

export function SalesPlansPage({ user, focus }: { user: SessionUser; focus?: string[] }) {
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(focus?.[0] ? Number(focus[0]) : thisYear)
  const [plans, setPlans] = useState<SalesPlan[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(focus?.[1] ?? null)
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
  const [mode, setMode] = useState<'year' | 'month'>('year')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [savedAt, setSavedAt] = useState<Date | null>(null)

  const draftsRef = useRef<Drafts>({})
  const clientsRef = useRef<Counterparty[]>([])
  const planRef = useRef<SalesPlan | null>(null)
  const hydratedPlanIdRef = useRef<string | null>(null)
  const skipHydrateRef = useRef<string | null>(null)
  const dirtyRevisionRef = useRef(0)
  const savedRevisionRef = useRef(0)
  const canEditRef = useRef(false)
  const saveChainRef = useRef<Promise<unknown>>(Promise.resolve())

  // Право на всех даёт должность; личный статус менеджера — только свои планы.
  const mayManage = canManageAll(user, 'sales_plans', 'edit')
  const yearPlans = plans.filter((plan) => plan.year === year)
  const plan = yearPlans.find((row) => row.id === selectedId) ?? null
  const isOwner = plan !== null && plan.manager_id === user.id
  const canEdit =
    can(user, 'sales_plans', 'edit') &&
    plan !== null &&
    plan.status !== 'approved' &&
    (mayManage || (isOwner && ['draft', 'filling'].includes(plan.status)))

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
    fetchPlanningProducts()
      .then((rows) => setProducts(rows.filter((product) => product.is_active)))
      .catch(() => setProducts([]))
    fetchCounterparties({ role: 'customer', includeInactive: true })
      .then(setClients)
      .catch(() => setClients([]))
    if (mayManage) {
      fetchManagers()
        .then((rows) => {
          setManagers(rows)
          setManagerId((current) => current || (rows[0]?.id ?? ''))
        })
        .catch(() => setManagers([]))
    }
  }, [reload, mayManage])

  useEffect(() => {
    planRef.current = plan
    if (plan && skipHydrateRef.current === plan.id) {
      // Это ответ автосохранения, а не другой план: не перетираем то, что
      // человек успел изменить, пока запрос летел.
      skipHydrateRef.current = null
      return
    }
    const next = plan ? draftsFromPlan(plan) : {}
    draftsRef.current = next
    hydratedPlanIdRef.current = plan?.id ?? null
    dirtyRevisionRef.current = 0
    savedRevisionRef.current = 0
    setSaveState('idle')
    setSavedAt(null)
    setDrafts(next)
    setClientId((current) => {
      if (current && next[current]) return current
      return Object.keys(next)[0] ?? ''
    })
  }, [plan])

  useEffect(() => {
    clientsRef.current = clients
  }, [clients])

  useEffect(() => {
    canEditRef.current = canEdit
  }, [canEdit])

  /** Сохранение черновика: запросы идут строго по очереди, последний снимок — свежий. */
  const requestSave = useCallback(async (reportErrors = false): Promise<boolean> => {
    const runSave = async (): Promise<boolean> => {
      const currentPlan = planRef.current
      if (!currentPlan || !canEditRef.current) return false
      if (hydratedPlanIdRef.current !== currentPlan.id) return false
      if (dirtyRevisionRef.current === savedRevisionRef.current && !reportErrors) return true
      const revision = dirtyRevisionRef.current
      const payload = buildDraftPayload(
        currentPlan,
        draftsRef.current,
        (id) => clientsRef.current.find((row) => row.id === id)?.name ?? 'Клиент',
        reportErrors ? setError : undefined,
      )
      if (!payload) return false
      setSaveState('saving')
      try {
        const updated = await saveSalesPlanItems(
          currentPlan.id,
          payload.items,
          payload.rows,
          payload.clients,
        )
        savedRevisionRef.current = revision
        skipHydrateRef.current = updated.id
        setPlans((current) => current.map((row) => (row.id === updated.id ? updated : row)))
        setSaveState('saved')
        setSavedAt(new Date())
        setError(null)
        return true
      } catch (err) {
        setSaveState('error')
        setError(errorMessage(err))
        return false
      }
    }
    const task = saveChainRef.current.then(runSave, runSave)
    saveChainRef.current = task.then(
      () => undefined,
      () => undefined,
    )
    return task
  }, [])

  // Каждое изменение черновика уходит на сервер само: добавление клиента,
  // позиции и ввод количеств. Пауза в наборе склеивает символы в один запрос.
  useEffect(() => {
    // Сами данные черновика лежат в ref; зависимость от drafts нужна,
    // чтобы эффект перезапускал таймер на каждое изменение.
    void drafts
    if (!canEdit || !plan || hydratedPlanIdRef.current !== plan.id) return
    if (dirtyRevisionRef.current === savedRevisionRef.current) return
    const timer = window.setTimeout(() => {
      if (dirtyRevisionRef.current !== savedRevisionRef.current) void requestSave()
    }, 600)
    return () => window.clearTimeout(timer)
  }, [drafts, canEdit, plan, requestSave])

  // Уход со страницы не должен терять последнее действие.
  useEffect(() => {
    return () => {
      if (dirtyRevisionRef.current !== savedRevisionRef.current) void requestSave()
    }
  }, [requestSave])

  useEffect(() => {
    if (!plan || !can(user, 'corrections', 'view')) {
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
  }, [plan, user])

  const run = async (action: () => Promise<unknown>, _message?: string) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const editable = plan?.editable_months ?? []
  const rows = clientId ? (drafts[clientId] ?? []) : []

  const updateDrafts = (updater: (current: Drafts) => Drafts, immediate = false) => {
    setDrafts((current) => {
      const next = updater(current)
      draftsRef.current = next
      return next
    })
    dirtyRevisionRef.current += 1
    if (immediate) {
      // Даём React применить состояние, затем сохраняем добавленный состав.
      window.setTimeout(() => void requestSave(), 0)
    }
  }

  const setRows = (updater: (current: DraftRow[]) => DraftRow[]) => {
    updateDrafts((current) => ({
      ...current,
      [clientId]: updater(current[clientId] ?? []),
    }))
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
    if (rows.some((row) => row.productId === product.id)) return
    updateDrafts(
      (current) => ({
        ...current,
        [clientId]: [
          ...(current[clientId] ?? []),
          {
            productId: product.id,
            code: product.code,
            name: product.name,
            unit: product.unit,
            months: {},
          },
        ],
      }),
      true,
    )
    setProductToAdd('')
  }

  const addClientToPlan = () => {
    if (!clientToAdd) return
    updateDrafts((current) => ({ ...current, [clientToAdd]: current[clientToAdd] ?? [] }), true)
    setClientId(clientToAdd)
    setClientToAdd('')
  }

  const saveExplicitly = () => {
    setError(null)
    void requestSave(true)
  }

  const submitPlan = async () => {
    if (!plan) return
    const saved = await requestSave(true)
    if (!saved) return
    await run(() => salesPlanAction(plan.id, 'submit'))
  }

  /** Итог строки — сумма месяцев: единица измерения у строки одна, складывать корректно. */
  const rowQuantity = (row: DraftRow): number =>
    editable.reduce((sum, month) => sum + Number(normalize(row.months[month] ?? '') || 0), 0)

  const planClients = Object.keys(drafts)
  const canSubmit =
    can(user, 'sales_plans', 'submit') &&
    plan !== null &&
    (mayManage || isOwner) &&
    ['draft', 'filling'].includes(plan.status)
  const canApprove =
    can(user, 'sales_plans', 'approve') && plan !== null && plan.status === 'on_review'
  const canDelete =
    can(user, 'sales_plans', 'delete') &&
    plan !== null &&
    ['draft', 'filling'].includes(plan.status) &&
    (mayManage || isOwner)

  const openCorrection =
    corrections.find((row) => row.status === 'draft' || row.status === 'on_review') ?? null
  const canProposeCorrection =
    can(user, 'corrections', 'propose') &&
    (scopeFor(user, 'corrections', 'propose') === 'all' || isOwner)
  const canCreateCorrection =
    plan !== null && canProposeCorrection && plan.status === 'approved' && openCorrection === null
  const correctionEditable =
    correction !== null && correction.status === 'draft' && canProposeCorrection
  const canReviewCorrection = correction !== null && correction.status === 'on_review' && mayManage

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

  if (mode === 'month') {
    return (
      <section>
        <header className="page-head">
          <h1>Планирование продаж</h1>
          <PageHelp>
            Год — утверждённый план и корректировки. Месяц — пересмотр месяца: окно с 23-го числа
            предыдущего месяца по его последний день. Причина обязательна при снижении ниже годового
            плана; повышение — по желанию. Позицию можно обнулить или добавить.
          </PageHelp>
          <div className="toolbar">
            <button type="button" onClick={() => setYear(year - 1)} aria-label="Предыдущий год">
              ←
            </button>
            <strong>{year}</strong>
            <button type="button" onClick={() => setYear(year + 1)} aria-label="Следующий год">
              →
            </button>
          </div>
        </header>
        <PlanModeTabs mode={mode} onChange={setMode} />
        <MonthlyPlanTab user={user} year={year} managers={managers} />
      </section>
    )
  }

  return (
    <section>
      <header className="page-head">
        <h1>Планирование продаж</h1>
        <PageHelp>
          Годовой план на менеджера: клиент × товар × месяц, только количество. Утверждает
          коммерческий директор. Утверждённый план нельзя править напрямую — создайте корректировку:
          в ней можно менять объёмы и состав позиций.
        </PageHelp>
        <div className="toolbar">
          <button type="button" onClick={() => setYear(year - 1)} aria-label="Предыдущий год">
            ←
          </button>
          <strong data-testid="plan-year">{year}</strong>
          <button type="button" onClick={() => setYear(year + 1)} aria-label="Следующий год">
            →
          </button>
          <span className="sep" />
          {mayManage ? (
            <>
              <span className="hint">План для:</span>
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
          ) : can(user, 'sales_plans', 'edit') ? (
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

      <PlanModeTabs mode={mode} onChange={setMode} />

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="plan-list">
        {yearPlans.length === 0 ? (
          <div className="empty-state" data-testid="no-plans">
            <strong>На {year} год планов нет</strong>
            <span>Создайте план продаж кнопкой выше — он появится здесь.</span>
          </div>
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
                строк:{' '}
                {row.draft_rows?.length ??
                  new Set(row.items.map((item) => `${item.client_id}|${item.product_id}`)).size}
                , клиентов:{' '}
                {row.draft_clients?.length ?? new Set(row.items.map((item) => item.client_id)).size}
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
                disabled={busy || saveState === 'saving'}
                onClick={saveExplicitly}
              >
                Сохранить
              </button>
            ) : null}
            {canEdit && saveState !== 'idle' ? (
              <span
                className={saveState === 'error' ? 'hint warn' : 'hint saved'}
                data-testid="draft-save-state"
                role="status"
              >
                {saveState === 'saving'
                  ? 'Сохраняем…'
                  : saveState === 'error'
                    ? 'Не сохранено — проверьте ошибку'
                    : `Черновик сохранён${savedAt ? ` в ${savedAt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}` : ''}`}
              </span>
            ) : null}
            {canSubmit ? (
              <button type="button" disabled={busy} onClick={() => void submitPlan()}>
                Отправить на проверку
              </button>
            ) : null}
            {mayManage && plan.status === 'draft' ? (
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
                    {mayManage ? 'Исправить утверждённый план' : 'Предложить корректировку'}
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
                        <SearchSelect
                          label="Добавить клиента в корректировку"
                          value={correctionClientToAdd}
                          onChange={setCorrectionClientToAdd}
                          disabled={busy}
                          placeholder="Начните вводить клиента"
                          emptyText="Клиент не найден"
                          options={activeClients
                            .filter(
                              (row) =>
                                !correctionClients.includes(row.id) ||
                                row.id === correctionClientToAdd,
                            )
                            .map((row) => ({ value: row.id, label: row.name }))}
                        />
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
                        <SearchSelect
                          label="Добавить товар в корректировку"
                          value={correctionProductToAdd}
                          onChange={setCorrectionProductToAdd}
                          disabled={busy || !correctionClientId}
                          wide
                          placeholder="Код или название позиции"
                          emptyText="Позиция не найдена"
                          options={products
                            .filter(
                              (product) =>
                                !correctionRows.some((row) => row.productId === product.id),
                            )
                            .map((product) => ({
                              value: product.id,
                              label: `${product.code} · ${product.name}`,
                              keywords: product.code,
                            }))}
                        />
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
              ) : null}
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
                <SearchSelect
                  label="Добавить клиента"
                  value={clientToAdd}
                  onChange={setClientToAdd}
                  disabled={!canEdit}
                  placeholder="Начните вводить клиента"
                  emptyText="Клиент не найден"
                  options={activeClients
                    .filter((row) => !planClients.includes(row.id) || row.id === clientToAdd)
                    .map((row) => ({ value: row.id, label: row.name }))}
                />
                <button type="button" disabled={!clientToAdd || !canEdit} onClick={addClientToPlan}>
                  Добавить
                </button>
              </div>

              <div className="toolbar">
                <SearchSelect
                  label="Добавить товар"
                  value={productToAdd}
                  onChange={setProductToAdd}
                  disabled={!canEdit || !clientId}
                  wide
                  placeholder="Код или название позиции"
                  emptyText="Позиция не найдена"
                  options={products
                    .filter((product) => !rows.some((row) => row.productId === product.id))
                    .map((product) => ({
                      value: product.id,
                      label: `${product.code} · ${product.name}`,
                      keywords: product.code,
                    }))}
                />
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
