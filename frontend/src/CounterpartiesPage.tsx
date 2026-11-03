import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  type Counterparty,
  type CounterpartyRole,
  counterpartyRoles,
  createCounterparty,
  errorMessage,
  fetchCounterpartiesPage,
  fetchCounterparty,
  fetchManagers,
  isAdmin,
  type SessionUser,
  updateCounterparty,
} from './api'
import { PageHelp } from './PageHelp'

const EMPTY_FORM = {
  name: '',
  inn: '',
  note: '',
  is_customer: true,
  is_local_supplier: false,
  is_import_supplier: false,
}

/** Сколько строк просим за раз: кнопка «Показать ещё» добавляет столько же. */
const PAGE_SIZE = 100

/** Поиск с задержкой: каждый символ не должен дёргать сервер. */
const SEARCH_DELAY_MS = 300

const ROLE_FILTERS: { value: '' | CounterpartyRole; title: string }[] = [
  { value: '', title: 'Все контрагенты' },
  { value: 'customer', title: 'Покупатели' },
  { value: 'local_supplier', title: 'Локальные поставщики' },
  { value: 'import_supplier', title: 'Импортные поставщики' },
]

/** Кто может менять справочник: те же роли, что и на бэкенде, плюс администратор. */
const WRITE_ROLES: string[] = ['sales_manager', 'commercial_director', 'purchase_director']

export function CounterpartiesPage({ user, focusId }: { user?: SessionUser; focusId?: string }) {
  const mayEdit = !user || isAdmin(user) || WRITE_ROLES.includes(user.role)
  const [rows, setRows] = useState<Counterparty[]>([])
  const [total, setTotal] = useState(0)
  const [managers, setManagers] = useState<SessionUser[]>([])
  const [role, setRole] = useState<'' | CounterpartyRole>('')
  const [search, setSearch] = useState('')
  const [needle, setNeedle] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [focusRow, setFocusRow] = useState<Counterparty | null>(null)
  const [form, setForm] = useState(EMPTY_FORM)
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
      const page = await fetchCounterpartiesPage({
        role: role === '' ? undefined : role,
        includeInactive: showInactive,
        search: needle,
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
  }, [role, showInactive, needle])

  useEffect(() => {
    void loadFirstPage()
  }, [loadFirstPage])

  useEffect(() => {
    fetchManagers()
      .then(setManagers)
      .catch(() => setManagers([]))
  }, [])

  // Объект из сообщения тянем отдельно: он может лежать и за первой сотней.
  useEffect(() => {
    if (!focusId) {
      setFocusRow(null)
      return
    }
    let alive = true
    fetchCounterparty(focusId)
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
      const page = await fetchCounterpartiesPage({
        role: role === '' ? undefined : role,
        includeInactive: showInactive,
        search: needle,
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
      await createCounterparty({
        name: form.name,
        inn: form.inn.trim() === '' ? null : form.inn.trim(),
        note: form.note.trim() === '' ? null : form.note.trim(),
        is_customer: form.is_customer,
        is_local_supplier: form.is_local_supplier,
        is_import_supplier: form.is_import_supplier,
      })
      setForm({ ...EMPTY_FORM, is_customer: form.is_customer })
      await loadFirstPage()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const assignManager = async (row: Counterparty, managerId: string) => {
    setBusy(true)
    setError(null)
    try {
      const updated = await updateCounterparty(row.id, {
        manager_id: managerId === '' ? null : managerId,
      })
      setRows((current) => current.map((item) => (item.id === updated.id ? updated : item)))
      setFocusRow((current) => (current?.id === updated.id ? updated : current))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (row: Counterparty) => {
    setBusy(true)
    setError(null)
    try {
      const updated = await updateCounterparty(row.id, { is_active: !row.is_active })
      const stillShown = showInactive || updated.is_active
      setRows((current) =>
        stillShown
          ? current.map((item) => (item.id === updated.id ? updated : item))
          : current.filter((item) => item.id !== updated.id),
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
        <h1>Контрагенты</h1>
        <PageHelp>
          Покупатели, локальные и импортные поставщики. Одна компания может быть и покупателем, и
          поставщиком — это одна запись с двумя признаками. В плане продаж выбираются только
          покупатели.
        </PageHelp>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {mayEdit ? (
        <form className="inline-form" onSubmit={submit}>
          <input
            aria-label="Наименование контрагента"
            placeholder="Наименование"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
          <input
            aria-label="ИНН"
            placeholder="ИНН (необязательно)"
            value={form.inn}
            onChange={(event) => setForm({ ...form, inn: event.target.value })}
          />
          <input
            aria-label="Примечание"
            placeholder="Примечание"
            value={form.note}
            onChange={(event) => setForm({ ...form, note: event.target.value })}
          />
          <label className="check">
            <input
              type="checkbox"
              checked={form.is_customer}
              onChange={(event) => setForm({ ...form, is_customer: event.target.checked })}
            />
            покупатель
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.is_local_supplier}
              onChange={(event) => setForm({ ...form, is_local_supplier: event.target.checked })}
            />
            локальный поставщик
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.is_import_supplier}
              onChange={(event) => setForm({ ...form, is_import_supplier: event.target.checked })}
            />
            импортный поставщик
          </label>
          <button type="submit" className="primary" disabled={busy}>
            Добавить
          </button>
        </form>
      ) : null}

      <div className="toolbar">
        <select
          aria-label="Роль контрагента"
          value={role}
          onChange={(event) => setRole(event.target.value as '' | CounterpartyRole)}
        >
          {ROLE_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.title}
            </option>
          ))}
        </select>
        <input
          aria-label="Поиск по наименованию"
          placeholder="Поиск по наименованию"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="check">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(event) => setShowInactive(event.target.checked)}
          />
          показывать отключённых
        </label>
        <span className="sep" />
        <span className="hint">
          Найдено: <strong data-testid="counterparties-count">{total}</strong>
        </span>
      </div>

      <table data-testid="counterparties-table">
        <thead>
          <tr>
            <th scope="col">Наименование</th>
            <th scope="col">Менеджер</th>
            <th scope="col">Роли</th>
            <th scope="col">Состояние</th>
            <th scope="col" aria-label="Действия" />
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 ? (
            <tr>
              <td colSpan={5} className="hint" data-testid="counterparties-empty">
                {loading ? 'Загрузка…' : 'Контрагентов не найдено.'}
              </td>
            </tr>
          ) : (
            visible.map((row) => (
              <tr key={row.id} className={row.id === focusId ? 'focus-row' : undefined}>
                <td>{row.name}</td>
                <td>
                  {row.is_customer && mayEdit ? (
                    <select
                      aria-label={`Менеджер клиента ${row.name}`}
                      value={row.manager_id ?? ''}
                      disabled={busy}
                      onChange={(event) => void assignManager(row, event.target.value)}
                    >
                      <option value="">— не закреплён —</option>
                      {managers.map((manager) => (
                        <option key={manager.id} value={manager.id}>
                          {manager.full_name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    (row.manager_name ?? '—')
                  )}
                </td>
                <td>{counterpartyRoles(row).join(', ') || '—'}</td>
                <td>
                  <span className={row.is_active ? 'badge status-approved' : 'badge'}>
                    {row.is_active ? 'Активен' : 'Отключён'}
                  </span>
                </td>
                <td>
                  {mayEdit ? (
                    <button
                      type="button"
                      className="mini"
                      disabled={busy}
                      onClick={() => toggle(row)}
                    >
                      {row.is_active ? 'Отключить' : 'Включить'}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      {!loading && rows.length < total ? (
        <div className="table-more">
          <span className="hint" data-testid="counterparties-shown">
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
