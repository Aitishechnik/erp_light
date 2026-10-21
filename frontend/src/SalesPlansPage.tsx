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

/** Строка предложения корректировки: новое количество для клиента × товара × месяца. */
type PatchRow = {
  key: string
  clientId: string
  productId: string
  month: number
  quantity: string
}

const QTY_PATTERN = /^\d+(?:[.,]\d{1,3})?$/

function normalize(raw: string): string {
  return raw.trim().replace(',', '.')
}

/** «10.000» → «10», «15.500» → «15.5»: в поле ввода лишние нули не нужны. */
function trimQuantity(raw: string): string {
  return raw.includes('.') ? raw.replace(/\.?0+$/, '') : raw
}

function patchRowsFromCorrection(correction: SalesPlanCorrection): PatchRow[] {
  return correction.items.map((item) => ({
    key: item.id,
    clientId: item.client_id,
    productId: item.product_id,
    month: item.month,
    quantity: trimQuantity(item.quantity),
  }))
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
  const [patchRows, setPatchRows] = useState<PatchRow[]>([])
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
    if (!plan || !(isOwner || isCommercialDirector)) {
      setCorrections([])
      setCorrection(null)
      setPatchRows([])
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
        setPatchRows(open?.status === 'draft' ? patchRowsFromCorrection(open) : [])
      })
      .catch(() => {
        setCorrections([])
        setCorrection(null)
        setPatchRows([])
      })
  }, [plan, isOwner, isCommercialDirector])

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
    (isCommercialDirector || (isOwner && ['draft', 'filling'].includes(plan.status)))
  const canSubmit = plan !== null && isOwner && ['draft', 'filling'].includes(plan.status)
  const canApprove = plan !== null && isCommercialDirector && plan.status === 'on_review'
  const canDelete =
    plan !== null && ['draft', 'filling'].includes(plan.status) && (isCommercialDirector || isOwner)

  const openCorrection =
    corrections.find((row) => row.status === 'draft' || row.status === 'on_review') ?? null
  const canCreateCorrection =
    plan !== null && isOwner && plan.status === 'approved' && openCorrection === null
  const correctionEditable = correction !== null && correction.status === 'draft' && isOwner
  const canReviewCorrection =
    correction !== null && correction.status === 'on_review' && isCommercialDirector

  const currentQuantity = (row: PatchRow): string => {
    const item = plan?.items.find(
      (candidate) =>
        candidate.client_id === row.clientId &&
        candidate.product_id === row.productId &&
        candidate.month === row.month,
    )
    return item ? trimQuantity(item.quantity) : '0'
  }

  const addPatchRow = () => {
    const client = activeClients[0]?.id ?? ''
    const product = products[0]?.id ?? ''
    const month = editable[0] ?? 1
    setPatchRows((current) => [
      ...current,
      {
        key: `patch-${Date.now()}-${current.length}`,
        clientId: client,
        productId: product,
        month,
        quantity: '',
      },
    ])
  }

  const updatePatchRow = (key: string, patch: Partial<PatchRow>) => {
    setPatchRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  const removePatchRow = (key: string) => {
    setPatchRows((current) => current.filter((row) => row.key !== key))
  }

  const collectPatch = (): SalesPlanCorrectionItemIn[] | null => {
    const items: SalesPlanCorrectionItemIn[] = []
    for (const row of patchRows) {
      if (!row.clientId || !row.productId) {
        setError('В корректировке выберите клиента и товар')
        return null
      }
      const quantity = normalize(row.quantity)
      if (!QTY_PATTERN.test(quantity)) {
        setError(`Количество «${row.quantity}» — неотрицательное число`)
        return null
      }
      items.push({
        client_id: row.clientId,
        product_id: row.productId,
        month: row.month,
        quantity,
      })
    }
    return items
  }

  const startCorrection = () => {
    if (!plan) return
    void run(async () => {
      const created = await createSalesPlanCorrection(plan.id)
      setCorrections((current) => [created, ...current])
      setCorrection(created)
      setPatchRows([])
    }, 'Черновик корректировки создан')
  }

  const saveCorrection = () => {
    if (!correction) return
    const items = collectPatch()
    if (!items) return
    void run(async () => {
      const updated = await saveSalesPlanCorrectionItems(correction.id, items)
      setCorrection(updated)
      setPatchRows(patchRowsFromCorrection(updated))
    }, 'Корректировка сохранена')
  }

  const sendCorrection = () => {
    if (!correction) return
    const items = collectPatch()
    if (!items) return
    void run(async () => {
      await saveSalesPlanCorrectionItems(correction.id, items)
      await submitSalesPlanCorrection(correction.id)
    }, 'Корректировка отправлена коммерческому директору')
  }

  const cancelCorrection = () => {
    if (!correction) return
    if (!confirm('Отменить корректировку?')) return
    void run(async () => {
      await deleteSalesPlanCorrection(correction.id)
      setCorrection(null)
      setPatchRows([])
    }, 'Корректировка отменена')
  }

  const approveCorrection = () => {
    if (!correction) return
    void run(
      () => approveSalesPlanCorrection(correction.id),
      'Корректировка утверждена — годовой план отдела требует повторного утверждения ГД',
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
                    Предложить корректировку
                  </button>
                ) : null}
              </div>

              {correction ? (
                <>
                  {correction.review_reason ? (
                    <p className="hint warn">Причина отклонения: {correction.review_reason}</p>
                  ) : null}

                  {correctionEditable ? (
                    <>
                      <div className="purchase-table">
                        <table data-testid="correction-table">
                          <thead>
                            <tr>
                              <th scope="col">Клиент</th>
                              <th scope="col">Товар</th>
                              <th scope="col">Месяц</th>
                              <th scope="col" className="num">
                                Сейчас
                              </th>
                              <th scope="col" className="num">
                                Новое
                              </th>
                              <th scope="col" aria-label="Действия" />
                            </tr>
                          </thead>
                          <tbody>
                            {patchRows.length === 0 ? (
                              <tr>
                                <td colSpan={6} className="hint">
                                  Добавьте изменение: клиент, товар, месяц и новое количество.
                                </td>
                              </tr>
                            ) : (
                              patchRows.map((row, index) => {
                                const product = products.find(
                                  (candidate) => candidate.id === row.productId,
                                )
                                return (
                                  <tr key={row.key}>
                                    <td>
                                      <select
                                        aria-label={`Клиент корректировки ${index + 1}`}
                                        value={row.clientId}
                                        onChange={(event) =>
                                          updatePatchRow(row.key, {
                                            clientId: event.target.value,
                                          })
                                        }
                                      >
                                        {activeClients.map((client) => (
                                          <option key={client.id} value={client.id}>
                                            {client.name}
                                          </option>
                                        ))}
                                      </select>
                                    </td>
                                    <td>
                                      <select
                                        aria-label={`Товар корректировки ${index + 1}`}
                                        value={row.productId}
                                        onChange={(event) =>
                                          updatePatchRow(row.key, {
                                            productId: event.target.value,
                                          })
                                        }
                                      >
                                        {products.map((candidate) => (
                                          <option key={candidate.id} value={candidate.id}>
                                            {candidate.code} · {candidate.name}
                                          </option>
                                        ))}
                                      </select>
                                    </td>
                                    <td>
                                      <select
                                        aria-label={`Месяц корректировки ${index + 1}`}
                                        value={row.month}
                                        onChange={(event) =>
                                          updatePatchRow(row.key, {
                                            month: Number(event.target.value),
                                          })
                                        }
                                      >
                                        {editable.map((month) => (
                                          <option key={month} value={month}>
                                            {MONTH_TITLES[month - 1]}
                                          </option>
                                        ))}
                                      </select>
                                    </td>
                                    <td className="num">
                                      {formatQuantity(currentQuantity(row))}
                                      {product ? ` ${product.unit}` : ''}
                                    </td>
                                    <td className="num">
                                      <input
                                        className="cell"
                                        aria-label={`Новое количество ${index + 1}`}
                                        value={row.quantity}
                                        onChange={(event) =>
                                          updatePatchRow(row.key, {
                                            quantity: event.target.value,
                                          })
                                        }
                                      />
                                    </td>
                                    <td>
                                      <button
                                        type="button"
                                        className="mini"
                                        aria-label={`Убрать изменение ${index + 1}`}
                                        onClick={() => removePatchRow(row.key)}
                                      >
                                        Убрать
                                      </button>
                                    </td>
                                  </tr>
                                )
                              })
                            )}
                          </tbody>
                        </table>
                      </div>
                      <div className="toolbar">
                        <button type="button" disabled={busy} onClick={addPatchRow}>
                          Добавить изменение
                        </button>
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
                          disabled={busy || patchRows.length === 0}
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
                          {correction.items.map((item) => (
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
                          ))}
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
                      Изменения применены к плану. Годовой план отдела нужно утвердить заново у ГД.
                    </p>
                  ) : null}
                </>
              ) : (
                <p className="hint">
                  Утверждённый план нельзя править напрямую — предложите корректировку.
                </p>
              )}
            </div>
          ) : null}

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
                            onChange={(event) => setMonth(row.productId, month, event.target.value)}
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
      ) : null}
    </section>
  )
}
