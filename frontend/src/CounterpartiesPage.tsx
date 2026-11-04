import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import {
  type Counterparty,
  type CounterpartyRole,
  counterpartyRoles,
  createCounterparty,
  errorMessage,
  fetchCounterparties,
  fetchCounterparty,
  fetchManagers,
  isAdmin,
  type SessionUser,
  updateCounterparty,
} from './api'
import { PageHelp } from './PageHelp'
import { SortableTh } from './SortableTh'
import { type SortState, sortRows, toggleSort } from './tableSort'
import { ROW_HEIGHT, useVirtualRows } from './useVirtualRows'

const EMPTY_FORM = {
  name: '',
  inn: '',
  note: '',
  is_customer: true,
  is_local_supplier: false,
  is_import_supplier: false,
}

const ROLE_FILTERS: { value: '' | CounterpartyRole; title: string }[] = [
  { value: '', title: 'Все контрагенты' },
  { value: 'customer', title: 'Покупатели' },
  { value: 'local_supplier', title: 'Локальные поставщики' },
  { value: 'import_supplier', title: 'Импортные поставщики' },
]

/** Кто может менять справочник: те же роли, что и на бэкенде, плюс администратор. */
const WRITE_ROLES: string[] = ['sales_manager', 'commercial_director', 'purchase_director']

/** По умолчанию — по наименованию, как в справочнике 1С. */
const DEFAULT_SORT: SortState = { column: 'name', direction: 'asc' }

export function CounterpartiesPage({ user, focusId }: { user?: SessionUser; focusId?: string }) {
  const mayEdit = !user || isAdmin(user) || WRITE_ROLES.includes(user.role)
  const [rows, setRows] = useState<Counterparty[]>([])
  const [managers, setManagers] = useState<SessionUser[]>([])
  const [role, setRole] = useState<'' | CounterpartyRole>('')
  const [search, setSearch] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT)
  const [focusRow, setFocusRow] = useState<Counterparty | null>(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  // Берём и отключённых: переключатель ниже решает, показывать ли их.
  const reload = useCallback(async () => {
    try {
      setRows(await fetchCounterparties({ includeInactive: true }))
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
    fetchManagers()
      .then(setManagers)
      .catch(() => setManagers([]))
  }, [])

  // Объект из сообщения тянем отдельно: он может быть отключён и скрыт фильтром.
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
      await reload()
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
      setRows((current) => current.map((item) => (item.id === updated.id ? updated : item)))
      setFocusRow((current) => (current?.id === updated.id ? updated : current))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const needle = search.trim().toLowerCase()
  const filtered = useMemo(
    () =>
      rows
        .filter((row) => (showInactive ? true : row.is_active))
        .filter((row) => {
          if (role === 'customer') return row.is_customer
          if (role === 'local_supplier') return row.is_local_supplier
          if (role === 'import_supplier') return row.is_import_supplier
          return true
        })
        .filter((row) => (needle ? row.name.toLowerCase().includes(needle) : true)),
    [rows, showInactive, role, needle],
  )

  const sorted = useMemo(
    () =>
      sortRows(filtered, sort, (row, column) => {
        if (column === 'manager') return row.manager_name
        if (column === 'roles') return counterpartyRoles(row).join(', ')
        if (column === 'state') return row.is_active
        return row.name
      }),
    [filtered, sort],
  )

  const resetKey = `${sort?.column}:${sort?.direction}:${needle}:${role}:${showInactive}`
  const { viewportRef, range, scrollToIndex } = useVirtualRows({
    count: sorted.length,
    resetKey,
  })

  // Объект из сообщения не должен теряться за фильтром: открываем его в списке.
  useEffect(() => {
    if (!focusRow) return
    setSearch('')
    setRole('')
    if (!focusRow.is_active) setShowInactive(true)
  }, [focusRow])

  // В виртуальном списке строки из сообщения может не быть в DOM — сначала
  // доскролливаем к её месту, потом подсвечиваем.
  useEffect(() => {
    if (!focusRow) return
    const index = sorted.findIndex((row) => row.id === focusRow.id)
    if (index >= 0) scrollToIndex(index)
  }, [focusRow, sorted, scrollToIndex])

  const filtersActive = search !== '' || role !== '' || showInactive
  const resetFilters = () => {
    setSearch('')
    setRole('')
    setShowInactive(false)
  }

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

      <div className="toolbar filter-bar">
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
      </div>

      <div className="filter-summary">
        <span className="filter-count" data-testid="counterparties-filter-count">
          Найдено: <strong data-testid="counterparties-count">{filtered.length}</strong>
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
        data-testid="counterparties-viewport"
      >
        <table data-testid="counterparties-table" className="virtual-table">
          <thead>
            <tr>
              <SortableTh
                column="name"
                title="Наименование"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="manager"
                title="Менеджер"
                sort={sort}
                onSort={(column) => setSort((current) => toggleSort(current, column))}
              />
              <SortableTh
                column="roles"
                title="Роли"
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
                <td colSpan={5} className="hint" data-testid="counterparties-empty">
                  {loading ? 'Загрузка…' : 'Контрагентов не найдено.'}
                </td>
              </tr>
            ) : (
              <>
                {range.start > 0 ? (
                  <tr className="spacer" style={{ height: range.start * ROW_HEIGHT }}>
                    <td colSpan={5} />
                  </tr>
                ) : null}
                {sorted.slice(range.start, range.end).map((row) => (
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
                ))}
                {range.end < sorted.length ? (
                  <tr
                    className="spacer"
                    style={{ height: (sorted.length - range.end) * ROW_HEIGHT }}
                  >
                    <td colSpan={5} />
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
