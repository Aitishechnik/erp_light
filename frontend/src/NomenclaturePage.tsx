import { type FormEvent, useCallback, useEffect, useState } from 'react'
import {
  createProduct,
  errorMessage,
  fetchProducts,
  PRODUCT_KIND_LABELS,
  type Product,
  updateProduct,
} from './api'

const EMPTY_FORM = { code: '', name: '', kind: 'goods', unit: 'шт' }

export function NomenclaturePage() {
  const [rows, setRows] = useState<Product[]>([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [kindFilter, setKindFilter] = useState('')
  const [showInactive, setShowInactive] = useState(true)
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

  const visible = rows
    .filter((row) => (kindFilter ? row.kind === kindFilter : true))
    .filter((row) => (showInactive ? true : row.is_active))

  return (
    <section>
      <header className="page-head">
        <h1>Номенклатура</h1>
        <p className="hint">
          Товары и материалы, по которым ведётся учёт и планирование. Позиции из партий попадают
          сюда автоматически.
        </p>
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
          <option value="goods">Товар</option>
          <option value="material">Материал</option>
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
          <option value="goods">Товары</option>
          <option value="material">Материалы</option>
        </select>
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
          Всего позиций: <strong data-testid="products-count">{visible.length}</strong>
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
            <th scope="col" />
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 ? (
            <tr>
              <td colSpan={6} className="hint">
                Номенклатуры пока нет — добавьте первую позицию.
              </td>
            </tr>
          ) : (
            visible.map((product) => (
              <tr key={product.id}>
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
