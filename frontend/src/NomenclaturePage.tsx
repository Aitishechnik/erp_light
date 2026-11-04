import { type FormEvent, memo, useCallback, useEffect, useMemo, useState } from 'react'
import {
  createProduct,
  errorMessage,
  fetchProduct,
  fetchProducts,
  PRODUCT_KIND_FILTER_TITLES,
  PRODUCT_KIND_LABELS,
  PRODUCT_KINDS,
  type Product,
  updateProduct,
} from './api'
import { PageHelp } from './PageHelp'
import { SortableTh } from './SortableTh'
import { type SortState, sortRows, toggleSort } from './tableSort'
import { ROW_HEIGHT, useVirtualRows } from './useVirtualRows'

const EMPTY_FORM = { code: '', name: '', kind: 'material', unit: 'шт' }

/** Сортировка по умолчанию — как в 1С: по коду позиции. */
const DEFAULT_SORT: SortState = { column: 'code', direction: 'asc' }

/**
 * Строка таблицы вынесена в memo-компонент: при сортировке React двигает
 * готовые строки, а не перерисовывает полторы тысячи строк заново.
 */
const ProductRow = memo(function ProductRow({
  product,
  busy,
  focused,
  onToggle,
}: {
  product: Product
  busy: boolean
  focused: boolean
  onToggle: (product: Product) => void
}) {
  return (
    <tr className={focused ? 'focus-row' : undefined}>
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
        <button type="button" className="mini" disabled={busy} onClick={() => onToggle(product)}>
          {product.is_active ? 'Отключить' : 'Включить'}
        </button>
      </td>
    </tr>
  )
})

export function NomenclaturePage({ focusId }: { focusId?: string }) {
  const [rows, setRows] = useState<Product[]>([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [kindFilter, setKindFilter] = useState('')
  const [search, setSearch] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT)
  const [focusRow, setFocusRow] = useState<Product | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    try {
      setRows(await fetchProducts())
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  // Объект из сообщения тянем отдельно: он может быть отключён и скрыт фильтром.
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

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await createProduct(form)
      setForm({ ...EMPTY_FORM, kind: form.kind, unit: form.unit })
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = useCallback(async (product: Product) => {
    setBusy(true)
    setError(null)
    try {
      const updated = await updateProduct(product.id, { is_active: !product.is_active })
      setRows((current) => current.map((row) => (row.id === updated.id ? updated : row)))
      setFocusRow((current) => (current?.id === updated.id ? updated : current))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }, [])

  const needle = search.trim().toLowerCase()
  const filtered = useMemo(
    () =>
      rows
        .filter((row) => (kindFilter ? row.kind === kindFilter : true))
        .filter((row) => (showInactive ? true : row.is_active))
        .filter((row) =>
          needle
            ? row.name.toLowerCase().includes(needle) || row.code.toLowerCase().includes(needle)
            : true,
        ),
    [rows, kindFilter, showInactive, needle],
  )

  const sorted = useMemo(
    () =>
      sortRows(filtered, sort, (row, column) => {
        if (column === 'kind') return PRODUCT_KIND_LABELS[row.kind] ?? row.kind
        if (column === 'state') return row.is_active
        return row[column as 'code' | 'name' | 'unit']
      }),
    [filtered, sort],
  )

  const resetKey = `${sort?.column}:${sort?.direction}:${needle}:${kindFilter}:${showInactive}`
  const { viewportRef, range, scrollToIndex } = useVirtualRows({
    count: sorted.length,
    resetKey,
  })

  // Объект из сообщения не должен теряться за фильтром: открываем его в списке.
  useEffect(() => {
    if (!focusRow) return
    setSearch('')
    setKindFilter('')
    if (!focusRow.is_active) setShowInactive(true)
  }, [focusRow])

  // В виртуальном списке строки из сообщения может не быть в DOM — сначала
  // доскролливаем к её месту, потом подсвечиваем.
  useEffect(() => {
    if (!focusRow) return
    const index = sorted.findIndex((row) => row.id === focusRow.id)
    if (index >= 0) scrollToIndex(index)
  }, [focusRow, sorted, scrollToIndex])

  const filtersActive = search !== '' || kindFilter !== '' || showInactive
  const resetFilters = () => {
    setSearch('')
    setKindFilter('')
    setShowInactive(false)
  }

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

      <div className="toolbar filter-bar">
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
      </div>

      <div className="filter-summary">
        <span className="filter-count" data-testid="products-filter-count">
          Найдено: <strong data-testid="products-count">{filtered.length}</strong>
          {filtered.length !== rows.length ? (
            <span className="filter-total"> из {rows.length}</span>
          ) : null}
        </span>
        <button
          type="button"
          className="mini filter-reset"
          onClick={resetFilters}
          disabled={!filtersActive}
        >
          Сбросить
        </button>
      </div>

      <div
        className="table-scroll table-viewport"
        ref={viewportRef}
        data-testid="products-viewport"
      >
        <table data-testid="products-table" className="virtual-table">
          <thead>
            <tr>
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
                column="unit"
                title="Ед."
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="state"
                title="Состояние"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <th scope="col" aria-label="Действия" />
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={6} className="hint" data-testid="products-empty">
                  {loading ? 'Загрузка…' : 'Номенклатуры не найдено.'}
                </td>
              </tr>
            ) : (
              <>
                {range.start > 0 ? (
                  <tr className="spacer" style={{ height: range.start * ROW_HEIGHT }}>
                    <td colSpan={6} />
                  </tr>
                ) : null}
                {sorted.slice(range.start, range.end).map((product) => (
                  <ProductRow
                    key={product.id}
                    product={product}
                    busy={busy}
                    focused={product.id === focusId}
                    onToggle={toggle}
                  />
                ))}
                {range.end < sorted.length ? (
                  <tr
                    className="spacer"
                    style={{ height: (sorted.length - range.end) * ROW_HEIGHT }}
                  >
                    <td colSpan={6} />
                  </tr>
                ) : null}
              </>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
