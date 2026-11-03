import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createProduct,
  errorMessage,
  fetchProduct,
  fetchProductsPage,
  PRODUCT_KIND_FILTER_TITLES,
  PRODUCT_KIND_LABELS,
  PRODUCT_KINDS,
  type Product,
  updateProduct,
} from './api'
import { PageHelp } from './PageHelp'

const EMPTY_FORM = { code: '', name: '', kind: 'material', unit: 'шт' }

/** Сколько строк просим за раз: кнопка «Показать ещё» добавляет столько же. */
const PAGE_SIZE = 100

/** Поиск с задержкой: каждый символ не должен дёргать сервер. */
const SEARCH_DELAY_MS = 300

export function NomenclaturePage({ focusId }: { focusId?: string }) {
  const [rows, setRows] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [form, setForm] = useState(EMPTY_FORM)
  const [kindFilter, setKindFilter] = useState('')
  const [search, setSearch] = useState('')
  const [needle, setNeedle] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [focusRow, setFocusRow] = useState<Product | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  // Ответ на устаревший запрос не должен затирать свежий список.
  const requestId = useRef(0)

  useEffect(() => {
    const timer = setTimeout(() => setNeedle(search), SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [search])

  const loadFirstPage = useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    try {
      const page = await fetchProductsPage({
        search: needle,
        kinds: kindFilter ? [kindFilter] : undefined,
        includeInactive: showInactive,
        limit: PAGE_SIZE,
      })
      if (id !== requestId.current) return
      setRows(page.items)
      setTotal(page.total)
      setError(null)
    } catch (err) {
      if (id !== requestId.current) return
      setError(errorMessage(err))
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [needle, kindFilter, showInactive])

  useEffect(() => {
    void loadFirstPage()
  }, [loadFirstPage])

  // Объект из сообщения тянем отдельно: он может лежать и за первой сотней.
  useEffect(() => {
    if (!focusId) {
      setFocusRow(null)
      return
    }
    let alive = true
    fetchProduct(focusId)
      .then((row) => {
        if (alive) setFocusRow(row)
      })
      .catch(() => {
        if (alive) setFocusRow(null)
      })
    return () => {
      alive = false
    }
  }, [focusId])

  /** Строка из сообщения показывается первой и не дублируется в порции. */
  const visible = useMemo(() => {
    if (!focusRow) return rows
    return [focusRow, ...rows.filter((row) => row.id !== focusRow.id)]
  }, [rows, focusRow])

  const loadMore = async () => {
    setLoadingMore(true)
    try {
      const page = await fetchProductsPage({
        search: needle,
        kinds: kindFilter ? [kindFilter] : undefined,
        includeInactive: showInactive,
        limit: PAGE_SIZE,
        offset: rows.length,
      })
      setRows((current) => {
        const seen = new Set(current.map((row) => row.id))
        return [...current, ...page.items.filter((row) => !seen.has(row.id))]
      })
      setTotal(page.total)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoadingMore(false)
    }
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await createProduct(form)
      setForm({ ...EMPTY_FORM, kind: form.kind, unit: form.unit })
      await loadFirstPage()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (product: Product) => {
    setBusy(true)
    setError(null)
    try {
      const updated = await updateProduct(product.id, { is_active: !product.is_active })
      const stillShown = showInactive || updated.is_active
      setRows((current) =>
        stillShown
          ? current.map((row) => (row.id === updated.id ? updated : row))
          : current.filter((row) => row.id !== updated.id),
      )
      setFocusRow((current) => (current?.id === updated.id ? updated : current))
      if (!stillShown) setTotal((value) => Math.max(0, value - 1))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!focusRow) return
    const frame = requestAnimationFrame(() => {
      const row = document.querySelector('tr.focus-row')
      if (row && typeof row.scrollIntoView === 'function') {
        row.scrollIntoView({ block: 'center' })
      }
    })
    return () => cancelAnimationFrame(frame)
  }, [focusRow])

  return (
    <section>
      <header className="page-head">
        <h1>Номенклатура</h1>
        <PageHelp>
          Материалы, сырьё и готовая продукция из выгрузок 1С плюс позиции, заведённые вручную. Код
          — код из 1С, поэтому повторная загрузка обновляет позицию, а не создаёт дубль. В планах и
          поступлениях выбираются только сырьё и готовая продукция, материалы остаются в
          справочнике.
        </PageHelp>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      <form className="inline-form" onSubmit={submit}>
        <input
          aria-label="Код"
          placeholder="Код (артикул)"
          value={form.code}
          onChange={(event) => setForm({ ...form, code: event.target.value })}
          required
        />
        <input
          aria-label="Наименование"
          placeholder="Наименование"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          required
        />
        <select
          aria-label="Вид"
          value={form.kind}
          onChange={(event) => setForm({ ...form, kind: event.target.value })}
        >
          {PRODUCT_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {PRODUCT_KIND_LABELS[kind]}
            </option>
          ))}
        </select>
        <input
          aria-label="Единица"
          placeholder="Ед."
          value={form.unit}
          onChange={(event) => setForm({ ...form, unit: event.target.value })}
          required
        />
        <button type="submit" className="primary" disabled={busy}>
          Добавить
        </button>
      </form>

      <div className="toolbar">
        <select
          aria-label="Фильтр по виду"
          value={kindFilter}
          onChange={(event) => setKindFilter(event.target.value)}
        >
          <option value="">Все виды</option>
          {PRODUCT_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {PRODUCT_KIND_FILTER_TITLES[kind]}
            </option>
          ))}
        </select>
        <input
          aria-label="Поиск по коду или наименованию"
          placeholder="Поиск по коду или названию"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="check">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(event) => setShowInactive(event.target.checked)}
          />
          показывать отключённые
        </label>
        <span className="sep" />
        <span className="hint">
          Найдено: <strong data-testid="products-count">{total}</strong>
        </span>
      </div>

      <table data-testid="products-table">
        <thead>
          <tr>
            <th scope="col">Код</th>
            <th scope="col">Наименование</th>
            <th scope="col">Вид</th>
            <th scope="col">Ед.</th>
            <th scope="col">Состояние</th>
            <th scope="col" aria-label="Действия" />
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 ? (
            <tr>
              <td colSpan={6} className="hint" data-testid="products-empty">
                {loading ? 'Загрузка…' : 'Номенклатуры не найдено.'}
              </td>
            </tr>
          ) : (
            visible.map((product) => (
              <tr key={product.id} className={product.id === focusId ? 'focus-row' : undefined}>
                <td>{product.code}</td>
                <td>{product.name}</td>
                <td>{PRODUCT_KIND_LABELS[product.kind] ?? product.kind}</td>
                <td>{product.unit}</td>
                <td>
                  <span className={product.is_active ? 'badge status-approved' : 'badge'}>
                    {product.is_active ? 'Активна' : 'Отключена'}
                  </span>
                </td>
                <td>
                  <button
                    type="button"
                    className="mini"
                    disabled={busy}
                    onClick={() => toggle(product)}
                  >
                    {product.is_active ? 'Отключить' : 'Включить'}
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      {!loading && rows.length < total ? (
        <div className="table-more">
          <span className="hint" data-testid="products-shown">
            Показано {rows.length} из {total}
          </span>
          <button
            type="button"
            className="mini"
            onClick={() => void loadMore()}
            disabled={loadingMore}
          >
            {loadingMore ? 'Загрузка…' : `Показать ещё ${PAGE_SIZE}`}
          </button>
        </div>
      ) : null}
    </section>
  )
}
