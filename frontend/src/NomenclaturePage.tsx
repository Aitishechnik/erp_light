import { type FormEvent, useCallback, useEffect, useState } from 'react'
import {
  createProduct,
  errorMessage,
  fetchProducts,
  PRODUCT_KIND_FILTER_TITLES,
  PRODUCT_KIND_LABELS,
  PRODUCT_KINDS,
  type Product,
  updateProduct,
} from './api'
import { PageHelp } from './PageHelp'

const EMPTY_FORM = { code: '', name: '', kind: 'material', unit: 'шт' }
const VISIBLE_LIMIT = 100

/** Объект из сообщения показываем первым, даже если он за пределами первых ста. */
function withFocusFirst<T extends { id: string }>(
  filtered: T[],
  all: T[],
  focusId: string | undefined,
  limit: number,
): T[] {
  if (!focusId) return filtered.slice(0, limit)
  const target = filtered.find((row) => row.id === focusId) ?? all.find((row) => row.id === focusId)
  if (!target) return filtered.slice(0, limit)
  return [target, ...filtered.filter((row) => row.id !== focusId).slice(0, limit - 1)]
}

export function NomenclaturePage({ focusId }: { focusId?: string }) {
  const [rows, setRows] = useState<Product[]>([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [kindFilter, setKindFilter] = useState('')
  const [search, setSearch] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    try {
      setRows(await fetchProducts())
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

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

  const toggle = async (product: Product) => {
    setBusy(true)
    setError(null)
    try {
      await updateProduct(product.id, { is_active: !product.is_active })
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const needle = search.trim().toLowerCase()
  const filtered = rows
    .filter((row) => (kindFilter ? row.kind === kindFilter : true))
    .filter((row) => (showInactive ? true : row.is_active))
    .filter((row) =>
      needle
        ? row.name.toLowerCase().includes(needle) || row.code.toLowerCase().includes(needle)
        : true,
    )
  const visible = withFocusFirst(filtered, rows, focusId, VISIBLE_LIMIT)

  useEffect(() => {
    if (!focusId) return
    const frame = requestAnimationFrame(() => {
      document.querySelector('tr.focus-row')?.scrollIntoView({ block: 'center' })
    })
    return () => cancelAnimationFrame(frame)
  }, [focusId])

  return (
    <section>
      <header className="page-head">
        <h1>Номенклатура</h1>
        <PageHelp>
          Материалы, сырьё и готовая продукция из выгрузок 1С плюс позиции, заведённые вручную. Код
          — код из 1С, поэтому повторная загрузка обновляет позицию, а не создаёт дубль.
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
          placeholder="Поиск по коду или наименованию"
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
          Найдено: <strong data-testid="products-count">{filtered.length}</strong>
          {filtered.length > VISIBLE_LIMIT ? `, показаны первые ${VISIBLE_LIMIT}` : null}
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
              <td colSpan={6} className="hint">
                Номенклатуры не найдено.
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
    </section>
  )
}
