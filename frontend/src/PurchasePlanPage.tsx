import { useCallback, useEffect, useState } from 'react'
import {
  approvePurchasePlan,
  type Counterparty,
  createPurchasePlan,
  deletePurchasePlan,
  errorMessage,
  fetchCounterparties,
  fetchProducts,
  fetchPurchasePlans,
  fetchStock,
  formatMoney,
  formatQuantity,
  MONTH_TITLES,
  type Product,
  type PurchasePlan,
  type PurchasePlanItemIn,
  rejectPurchasePlan,
  reopenPurchasePlan,
  type SessionUser,
  savePurchasePlanItems,
  submitPurchasePlan,
} from './api'

const QTY_PATTERN = /^\d+(?:[.,]\d{1,3})?$/
const PRICE_PATTERN = /^\d+(?:[.,]\d{1,2})?$/

function normalize(raw: string): string {
  return raw.trim().replace(',', '.')
}

/** «100.000» → «100», «250.50» → «250.5»: в поле лишние нули не нужны. */
function trimZeros(raw: string): string {
  return raw.includes('.') ? raw.replace(/\.?0+$/, '') : raw
}

/** Тот же расчёт, что на сервере: месяц заказа от срока логистики. */
function orderMonth(month: number, deliveryDays: number): number {
  return Math.max(1, month - Math.ceil(deliveryDays / 30))
}

type DraftRow = {
  key: string
  productId: string
  productCode: string
  productName: string
  unit: string
  month: number
  quantity: string
  priceRub: string
  supplierId: string
  supplierName: string
  deliveryDays: string
  /** Месяц заморожен или план уже не черновик — строку не правим и не отправляем. */
  locked: boolean
}

function draftsFromPlan(plan: PurchasePlan): DraftRow[] {
  return plan.items.map((item) => ({
    key: item.id,
    productId: item.product_id,
    productCode: item.product_code,
    productName: item.product_name,
    unit: item.unit,
    month: item.month,
    quantity: trimZeros(item.quantity),
    priceRub: item.price_rub === null ? '' : trimZeros(item.price_rub),
    supplierId: item.supplier_id ?? '',
    supplierName: item.supplier_name ?? '',
    deliveryDays: String(item.delivery_days),
    locked: !plan.editable_months.includes(item.month),
  }))
}

export function PurchasePlanPage({ user }: { user: SessionUser }) {
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(thisYear)
  const [plans, setPlans] = useState<PurchasePlan[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [suppliers, setSuppliers] = useState<Counterparty[]>([])
  const [stockByCode, setStockByCode] = useState<Record<string, string>>({})
  const [drafts, setDrafts] = useState<DraftRow[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')

  const [productToAdd, setProductToAdd] = useState('')
  const [monthToAdd, setMonthToAdd] = useState('')
  const [qtyToAdd, setQtyToAdd] = useState('')
  const [priceToAdd, setPriceToAdd] = useState('')
  const [supplierToAdd, setSupplierToAdd] = useState('')
  const [deliveryToAdd, setDeliveryToAdd] = useState('30')

  const plan = plans.find((row) => row.year === year) ?? null
  const editable = plan?.editable_months ?? []
  const isEditor = user.role === 'purchase_director' || user.role === 'import_manager'
  const isExecutive = user.role === 'executive_director'
  const canEdit = plan !== null && plan.status === 'draft' && isEditor
  const canSubmit = canEdit && drafts.some((row) => !row.locked)
  const canApprove = plan !== null && plan.status === 'on_review' && isExecutive
  const canReopen = plan !== null && plan.status === 'approved' && isExecutive
  const canDelete = plan !== null && plan.status === 'draft' && user.role === 'purchase_director'

  const reload = useCallback(async () => {
    try {
      setPlans(await fetchPurchasePlans())
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void reload()
    fetchProducts()
      .then((rows) => setProducts(rows.filter((row) => row.is_active && row.kind === 'raw')))
      .catch(() => setProducts([]))
    fetchCounterparties()
      .then((rows) =>
        setSuppliers(
          rows.filter((row) => row.is_active && (row.is_local_supplier || row.is_import_supplier)),
        ),
      )
      .catch(() => setSuppliers([]))
    fetchStock()
      .then((rows) => {
        const totals: Record<string, number> = {}
        for (const row of rows) {
          if (row.product_kind !== 'raw') continue
          totals[row.product_code] = (totals[row.product_code] ?? 0) + Number(row.quantity_on_hand)
        }
        setStockByCode(
          Object.fromEntries(Object.entries(totals).map(([code, qty]) => [code, String(qty)])),
        )
      })
      .catch(() => setStockByCode({}))
  }, [reload])

  useEffect(() => {
    setDrafts(plan ? draftsFromPlan(plan) : [])
    setRejectReason('')
  }, [plan])

  useEffect(() => {
    const current = new Date().getMonth() + 1
    setMonthToAdd(String(editable.includes(current) ? current : (editable[0] ?? 1)))
  }, [editable])

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

  const updateRow = (key: string, patch: Partial<DraftRow>) => {
    setDrafts((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)))
    setSaved(null)
  }

  const removeRow = (key: string) => {
    setDrafts((current) => current.filter((row) => row.key !== key))
    setSaved(null)
  }

  const addRow = () => {
    const product = products.find((row) => row.id === productToAdd)
    if (!product || !monthToAdd) return
    const quantity = normalize(qtyToAdd)
    if (!QTY_PATTERN.test(quantity) || Number(quantity) <= 0) {
      setError('Количество — число больше нуля')
      return
    }
    const price = normalize(priceToAdd)
    if (price !== '' && !PRICE_PATTERN.test(price)) {
      setError('Цена — неотрицательное число')
      return
    }
    const delivery = deliveryToAdd.trim() === '' ? 30 : Number(deliveryToAdd)
    if (!Number.isInteger(delivery) || delivery < 0 || delivery > 365) {
      setError('Срок логистики — целое число дней от 0 до 365')
      return
    }
    const supplier = suppliers.find((row) => row.id === supplierToAdd)
    setDrafts((current) => [
      ...current,
      {
        key: `new-${Date.now()}-${current.length}`,
        productId: product.id,
        productCode: product.code,
        productName: product.name,
        unit: product.unit,
        month: Number(monthToAdd),
        quantity,
        priceRub: price,
        supplierId: supplier?.id ?? '',
        supplierName: supplier?.name ?? '',
        deliveryDays: String(delivery),
        locked: false,
      },
    ])
    setProductToAdd('')
    setQtyToAdd('')
    setPriceToAdd('')
    setSupplierToAdd('')
    setDeliveryToAdd('30')
    setError(null)
    setSaved(null)
  }

  const collectItems = (): PurchasePlanItemIn[] | null => {
    const items: PurchasePlanItemIn[] = []
    for (const row of drafts) {
      if (row.locked || !editable.includes(row.month)) continue
      const quantity = normalize(row.quantity)
      if (!QTY_PATTERN.test(quantity) || Number(quantity) <= 0) {
        setError(`Количество «${row.quantity}» в строке ${row.productName} — не число больше нуля`)
        return null
      }
      const price = normalize(row.priceRub)
      if (price !== '' && !PRICE_PATTERN.test(price)) {
        setError(`Цена «${row.priceRub}» в строке ${row.productName} — не число`)
        return null
      }
      const delivery = row.deliveryDays.trim() === '' ? 30 : Number(row.deliveryDays)
      if (!Number.isInteger(delivery) || delivery < 0 || delivery > 365) {
        setError(`Срок «${row.deliveryDays}» в строке ${row.productName} — не число дней`)
        return null
      }
      items.push({
        product_id: row.productId,
        month: row.month,
        quantity,
        price_rub: price === '' ? null : price,
        supplier_id: row.supplierId || null,
        delivery_days: delivery,
      })
    }
    return items
  }

  const save = () => {
    if (!plan) return
    const items = collectItems()
    if (items) void run(() => savePurchasePlanItems(plan.id, items), 'План сохранён')
  }

  const totalAmount = drafts.reduce(
    (sum, row) => sum + Number(normalize(row.priceRub) || 0) * Number(normalize(row.quantity) || 0),
    0,
  )
  const stockFor = (row: DraftRow): string => {
    const quantity = stockByCode[row.productCode]
    return quantity === undefined ? '—' : `${formatQuantity(quantity)} ${row.unit}`
  }

  return (
    <section>
      <header className="page-head">
        <h1>План закупок сырья</h1>
        <p className="hint">
          Ручной годовой план: сырьё × месяц, цена в рублях. Утверждает исполнительный директор.
        </p>
        <div className="toolbar">
          <button
            type="button"
            aria-label="Предыдущий год"
            disabled={busy}
            onClick={() => {
              setYear(year - 1)
              setSaved(null)
            }}
          >
            ←
          </button>
          <strong data-testid="purchase-year">{year}</strong>
          <button
            type="button"
            aria-label="Следующий год"
            disabled={busy}
            onClick={() => {
              setYear(year + 1)
              setSaved(null)
            }}
          >
            →
          </button>
          {plan === null && isEditor ? (
            <>
              <span className="sep" />
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const created = await createPurchasePlan(year)
                    setYear(created.year)
                  }, 'План создан')
                }
              >
                Создать план на {year}
              </button>
            </>
          ) : null}
        </div>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p className="hint saved" data-testid="purchase-saved">
          {saved}
        </p>
      ) : null}

      {plan === null ? (
        <p className="hint" data-testid="purchase-no-plan">
          На {year} год плана закупок сырья нет.
        </p>
      ) : (
        <>
          <div className="purchase-summary" data-testid="purchase-plan-card">
            <span>{plan.created_by_name}</span>
            <span className={`badge status-${plan.status}`} data-testid="purchase-status">
              {plan.status_title}
            </span>
            <span>позиций: {drafts.length}</span>
            <span className="total">сумма: {formatMoney(totalAmount.toFixed(2))} ₽</span>
            {plan.approved_by_name ? <span>утвердил: {plan.approved_by_name}</span> : null}
          </div>
          {plan.notes ? <p className="hint">Примечания: {plan.notes}</p> : null}

          <div className="toolbar">
            {canEdit ? (
              <button type="button" className="primary" disabled={busy} onClick={save}>
                Сохранить
              </button>
            ) : null}
            {canSubmit ? (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(() => submitPurchasePlan(plan.id), 'План отправлен на утверждение')
                }
              >
                Отправить на утверждение
              </button>
            ) : null}
            {canApprove ? (
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={() => run(() => approvePurchasePlan(plan.id), 'План утверждён')}
              >
                Утвердить
              </button>
            ) : null}
            {canApprove || canReopen ? (
              <input
                aria-label="Причина"
                placeholder="Причина"
                value={rejectReason}
                onChange={(event) => setRejectReason(event.target.value)}
              />
            ) : null}
            {canApprove ? (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await rejectPurchasePlan(plan.id, rejectReason)
                    setRejectReason('')
                  }, 'План возвращён на доработку')
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
                    await reopenPurchasePlan(plan.id, rejectReason)
                    setRejectReason('')
                  }, 'План возвращён в работу')
                }
              >
                Вернуть в работу
              </button>
            ) : null}
            {canDelete ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  if (confirm('Удалить план закупок сырья?')) {
                    void run(() => deletePurchasePlan(plan.id), 'План удалён')
                  }
                }}
              >
                Удалить
              </button>
            ) : null}
            {isExecutive && plan.status === 'draft' ? (
              <span className="hint">Просмотр: план ещё заполняет закупщик</span>
            ) : null}
          </div>

          {canEdit ? (
            <div className="inline-form">
              <span className="hint">Добавить строку:</span>
              <select
                aria-label="Товар новой строки"
                value={productToAdd}
                onChange={(event) => setProductToAdd(event.target.value)}
              >
                <option value="">— сырьё —</option>
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.code} · {product.name} ({product.unit})
                  </option>
                ))}
              </select>
              <select
                aria-label="Месяц новой строки"
                value={monthToAdd}
                onChange={(event) => setMonthToAdd(event.target.value)}
              >
                {editable.map((month) => (
                  <option key={month} value={month}>
                    {MONTH_TITLES[month - 1]}
                  </option>
                ))}
              </select>
              <input
                aria-label="Количество новой строки"
                placeholder="Кол-во"
                value={qtyToAdd}
                onChange={(event) => setQtyToAdd(event.target.value)}
              />
              <input
                aria-label="Цена новой строки"
                placeholder="Цена, ₽"
                value={priceToAdd}
                onChange={(event) => setPriceToAdd(event.target.value)}
              />
              <select
                aria-label="Поставщик новой строки"
                value={supplierToAdd}
                onChange={(event) => setSupplierToAdd(event.target.value)}
              >
                <option value="">— поставщик —</option>
                {suppliers.map((supplier) => (
                  <option key={supplier.id} value={supplier.id}>
                    {supplier.name}
                  </option>
                ))}
              </select>
              <input
                aria-label="Срок логистики новой строки"
                type="number"
                min={0}
                max={365}
                value={deliveryToAdd}
                onChange={(event) => setDeliveryToAdd(event.target.value)}
              />
              <button
                type="button"
                disabled={busy || !productToAdd || !monthToAdd}
                onClick={addRow}
              >
                Добавить строку
              </button>
            </div>
          ) : null}

          <div className="purchase-table">
            <table data-testid="purchase-table">
              <thead>
                <tr>
                  <th scope="col">Товар</th>
                  <th scope="col">Месяц</th>
                  <th scope="col" className="num">
                    Кол-во
                  </th>
                  <th scope="col" className="num">
                    Цена, ₽
                  </th>
                  <th scope="col" className="num">
                    Сумма, ₽
                  </th>
                  <th scope="col">Поставщик</th>
                  <th scope="col" className="num">
                    Срок, дн
                  </th>
                  <th scope="col">Месяц заказа</th>
                  <th scope="col" className="num">
                    Остаток
                  </th>
                  <th scope="col" aria-label="Действия" />
                </tr>
              </thead>
              <tbody>
                {drafts.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="hint" data-testid="purchase-empty">
                      Строк пока нет — добавьте сырьё.
                    </td>
                  </tr>
                ) : (
                  drafts.map((row) => {
                    const rowEditable = canEdit && !row.locked && editable.includes(row.month)
                    const supplier = suppliers.find((item) => item.id === row.supplierId)
                    return (
                      <tr key={row.key} data-testid={`purchase-row-${row.key}`}>
                        <td>
                          {row.productCode} · {row.productName}
                          <span className="unit">, {row.unit}</span>
                        </td>
                        <td>
                          {rowEditable ? (
                            <select
                              aria-label={`Месяц ${row.productCode} ${MONTH_TITLES[row.month - 1]}`}
                              value={row.month}
                              onChange={(event) =>
                                updateRow(row.key, { month: Number(event.target.value) })
                              }
                            >
                              {editable.map((month) => (
                                <option key={month} value={month}>
                                  {MONTH_TITLES[month - 1]}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span title={row.locked ? 'Месяц заморожен' : undefined}>
                              {MONTH_TITLES[row.month - 1]}
                            </span>
                          )}
                        </td>
                        <td className="num">
                          {rowEditable ? (
                            <input
                              className="cell"
                              aria-label={`Количество ${row.productCode} ${MONTH_TITLES[row.month - 1]}`}
                              value={row.quantity}
                              onChange={(event) =>
                                updateRow(row.key, { quantity: event.target.value })
                              }
                            />
                          ) : (
                            formatQuantity(row.quantity)
                          )}
                        </td>
                        <td className="num">
                          {rowEditable ? (
                            <input
                              className="cell"
                              aria-label={`Цена ${row.productCode} ${MONTH_TITLES[row.month - 1]}`}
                              value={row.priceRub}
                              onChange={(event) =>
                                updateRow(row.key, { priceRub: event.target.value })
                              }
                            />
                          ) : (
                            formatMoney(row.priceRub || null)
                          )}
                        </td>
                        <td className="num">
                          {formatMoney(
                            (
                              Number(normalize(row.priceRub) || 0) *
                              Number(normalize(row.quantity) || 0)
                            ).toFixed(2),
                          )}
                        </td>
                        <td>
                          {rowEditable ? (
                            <select
                              aria-label={`Поставщик ${row.productCode} ${MONTH_TITLES[row.month - 1]}`}
                              value={row.supplierId}
                              onChange={(event) => {
                                const chosen = suppliers.find(
                                  (item) => item.id === event.target.value,
                                )
                                updateRow(row.key, {
                                  supplierId: event.target.value,
                                  supplierName: chosen?.name ?? '',
                                })
                              }}
                            >
                              <option value="">—</option>
                              {suppliers.map((item) => (
                                <option key={item.id} value={item.id}>
                                  {item.name}
                                </option>
                              ))}
                            </select>
                          ) : (
                            row.supplierName || supplier?.name || '—'
                          )}
                        </td>
                        <td className="num">
                          {rowEditable ? (
                            <input
                              className="cell"
                              type="number"
                              min={0}
                              max={365}
                              aria-label={`Срок ${row.productCode} ${MONTH_TITLES[row.month - 1]}`}
                              value={row.deliveryDays}
                              onChange={(event) =>
                                updateRow(row.key, { deliveryDays: event.target.value })
                              }
                            />
                          ) : (
                            row.deliveryDays
                          )}
                        </td>
                        <td>
                          {MONTH_TITLES[orderMonth(row.month, Number(row.deliveryDays || 0)) - 1]}
                        </td>
                        <td className="num">{stockFor(row)}</td>
                        <td>
                          {rowEditable ? (
                            <button
                              type="button"
                              className="mini"
                              aria-label={`Убрать ${row.productCode} ${MONTH_TITLES[row.month - 1]}`}
                              onClick={() => removeRow(row.key)}
                            >
                              Убрать
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
