import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import {
  bindFutureProduct,
  can,
  canManageAll,
  createFutureProduct,
  deleteFutureProduct,
  errorMessage,
  type FutureProduct,
  fetchFutureProducts,
  fetchProducts,
  PLANNING_PRODUCT_KINDS,
  type Product,
  type SessionUser,
  updateFutureProduct,
} from './api'
import { PageHelp } from './PageHelp'
import { SearchSelect } from './SearchSelect'

const EMPTY_FORM = { name: '', unit: 'шт' }

/** Использование позиции для строки списка: планы, документы и годы. */
function usageText(row: FutureProduct): string {
  const parts: string[] = []
  if (row.plans_count > 0) parts.push(`планов: ${row.plans_count}, строк: ${row.rows_count}`)
  if (row.other_documents > 0) parts.push(`в документах: ${row.other_documents}`)
  if (parts.length === 0) return 'не используется'
  return parts.join(' · ') + (row.years.length ? ` · ${row.years.join(', ')}` : '')
}

/**
 * Позиции будущих периодов: номенклатура, которой ещё нет в 1С.
 *
 * Пока позиция не привязана, она живёт только в планировании. Привязка к
 * реальной карточке переносит все ссылки и удаляет заглушку, поэтому доступна
 * только тому, кто отвечает за планы всех менеджеров.
 */
export function FutureProductsPage({ user }: { user: SessionUser }) {
  const [rows, setRows] = useState<FutureProduct[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({ name: '', unit: '' })
  const [binding, setBinding] = useState<string | null>(null)
  const [targetId, setTargetId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const mayBind = canManageAll(user, 'sales_plans', 'edit')
  const mayEdit = can(user, 'directories', 'edit') || mayBind

  const reload = useCallback(async () => {
    try {
      setRows(await fetchFutureProducts())
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    if (!mayBind) return
    fetchProducts({ kinds: PLANNING_PRODUCT_KINDS, includeFuture: false })
      .then((list) => setProducts(list.filter((row) => row.is_active && !row.is_future)))
      .catch(() => setProducts([]))
  }, [mayBind])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const name = form.name.trim()
    if (!name) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await createFutureProduct({ name, unit: form.unit.trim() || 'шт' })
      setForm({ ...EMPTY_FORM, unit: form.unit })
      await reload()
      setNotice(`Позиция «${name}» добавлена в список будущих`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (row: FutureProduct) => {
    setEditing(row.id)
    setEditForm({ name: row.name, unit: row.unit })
    setError(null)
    setNotice(null)
  }

  const saveEdit = async (row: FutureProduct) => {
    setBusy(true)
    setError(null)
    try {
      await updateFutureProduct(row.id, {
        name: editForm.name.trim(),
        unit: editForm.unit.trim() || 'шт',
      })
      setEditing(null)
      await reload()
      setNotice('Название обновлено — в планах показывается новое')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (row: FutureProduct) => {
    if (!confirm(`Удалить будущую позицию «${row.name}»?`)) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await deleteFutureProduct(row.id)
      await reload()
      setNotice(`Позиция «${row.name}» удалена`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const startBind = (row: FutureProduct) => {
    setBinding(row.id)
    setTargetId('')
    setError(null)
    setNotice(null)
  }

  const bind = async () => {
    const row = rows.find((candidate) => candidate.id === binding)
    const target = products.find((candidate) => candidate.id === targetId)
    if (!row || !target) return
    if (
      !confirm(
        `Заменить «${row.name}» на «${target.code} · ${target.name}» во всех планах? ` +
          'Совпадающие строки сложатся, старое название удалится. Отменить привязку нельзя.',
      )
    ) {
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await bindFutureProduct(row.id, target.id)
      setBinding(null)
      setTargetId('')
      await reload()
      setNotice(
        `«${row.name}» заменена на «${result.product_code} · ${result.product_name}». ` +
          `Строк плана: ${result.plan_rows}, планов: ${result.plans}` +
          (result.other_rows ? `, прочих строк: ${result.other_rows}` : ''),
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const needle = search.trim().toLowerCase()
  const visible = useMemo(
    () => rows.filter((row) => (needle ? row.name.toLowerCase().includes(needle) : true)),
    [rows, needle],
  )
  const bindingRow = binding ? (rows.find((row) => row.id === binding) ?? null) : null

  return (
    <section>
      <header className="page-head">
        <h1>Позиции будущих периодов</h1>
        <PageHelp>
          Номенклатура, которой ещё нет в 1С: планируем её по названию. В обычной номенклатуре,
          остатках и сопоставлении продаж таких позиций нет. Когда позиция появилась в выгрузке 1С,
          привяжите её здесь — годовые и месячные планы, корректировки и закупки перейдут на
          реальную карточку, а старое название удалится. Неиспользованную позицию можно удалить;
          если она уже попала в план или документ — только привязать.
        </PageHelp>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="hint saved" role="status" data-testid="future-notice">
          {notice}
        </p>
      ) : null}

      {mayEdit ? (
        <form className="inline-form" onSubmit={submit}>
          <input
            aria-label="Название будущей позиции"
            placeholder="Название без кода 1С"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
          <input
            aria-label="Единица будущей позиции"
            placeholder="Ед."
            value={form.unit}
            onChange={(event) => setForm({ ...form, unit: event.target.value })}
            required
          />
          <button type="submit" className="primary" disabled={busy || !form.name.trim()}>
            Добавить
          </button>
        </form>
      ) : null}

      <div className="toolbar filter-bar">
        <input
          aria-label="Поиск по названию"
          placeholder="Поиск по названию"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <span className="hint" data-testid="future-products-count">
          {visible.length}
          {visible.length !== rows.length ? ` из ${rows.length}` : ''}
        </span>
      </div>

      {bindingRow ? (
        <div className="correction-box" data-testid="future-bind-panel">
          <div className="toolbar">
            <h2>Привязка «{bindingRow.name}»</h2>
            <span className="sep" />
            <SearchSelect
              label="Реальная позиция из 1С"
              value={targetId}
              onChange={setTargetId}
              disabled={busy}
              wide
              placeholder="Код или название позиции"
              emptyText="Позиция не найдена"
              options={products.map((product) => ({
                value: product.id,
                label: `${product.code} · ${product.name}`,
                keywords: product.code,
              }))}
            />
            <button type="button" className="primary" disabled={busy || !targetId} onClick={bind}>
              Привязать
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setBinding(null)
                setTargetId('')
              }}
            >
              Отмена
            </button>
          </div>
          <p className="hint">
            Заменяет позицию во всех планах и корректировках. Строки «тот же клиент и месяц»
            складываются, старое название удаляется. Отменить привязку нельзя.
          </p>
        </div>
      ) : null}

      <div className="table-scroll">
        <table data-testid="future-products-table">
          <thead>
            <tr>
              <th scope="col">Название</th>
              <th scope="col">Ед.</th>
              <th scope="col">Использование</th>
              <th scope="col">Действия</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={4} className="hint" data-testid="future-products-empty">
                  {loading
                    ? 'Загрузка…'
                    : rows.length === 0
                      ? 'Будущих позиций пока нет — добавьте название выше.'
                      : 'По запросу ничего не найдено.'}
                </td>
              </tr>
            ) : (
              visible.map((row) =>
                editing === row.id ? (
                  <tr key={row.id}>
                    <td>
                      <input
                        aria-label={`Новое название ${row.name}`}
                        value={editForm.name}
                        onChange={(event) => setEditForm({ ...editForm, name: event.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        aria-label={`Новая единица ${row.name}`}
                        value={editForm.unit}
                        onChange={(event) => setEditForm({ ...editForm, unit: event.target.value })}
                      />
                    </td>
                    <td className="hint">—</td>
                    <td>
                      <button
                        type="button"
                        className="primary"
                        disabled={busy || !editForm.name.trim()}
                        onClick={() => void saveEdit(row)}
                      >
                        Сохранить
                      </button>
                      <button type="button" disabled={busy} onClick={() => setEditing(null)}>
                        Отмена
                      </button>
                    </td>
                  </tr>
                ) : (
                  <tr key={row.id}>
                    <td>{row.name}</td>
                    <td>{row.unit}</td>
                    <td className="hint">{usageText(row)}</td>
                    <td>
                      {mayBind ? (
                        <button
                          type="button"
                          className="mini"
                          disabled={busy}
                          onClick={() => startBind(row)}
                        >
                          Привязать
                        </button>
                      ) : null}
                      {mayEdit ? (
                        <>
                          <button
                            type="button"
                            className="mini"
                            disabled={busy}
                            onClick={() => startEdit(row)}
                          >
                            Переименовать
                          </button>
                          <button
                            type="button"
                            className="mini"
                            disabled={busy || !row.delete_allowed}
                            title={
                              row.delete_allowed
                                ? undefined
                                : 'Позиция уже используется — её можно только привязать'
                            }
                            onClick={() => void remove(row)}
                          >
                            Удалить
                          </button>
                        </>
                      ) : null}
                    </td>
                  </tr>
                ),
              )
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
