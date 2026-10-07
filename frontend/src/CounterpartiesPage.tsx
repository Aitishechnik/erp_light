import { type FormEvent, useCallback, useEffect, useState } from 'react'
import {
  type Counterparty,
  type CounterpartyRole,
  counterpartyRoles,
  createCounterparty,
  errorMessage,
  fetchCounterparties,
  updateCounterparty,
} from './api'

const EMPTY_FORM = {
  name: '',
  inn: '',
  note: '',
  is_customer: true,
  is_local_supplier: false,
  is_import_supplier: false,
}

const VISIBLE_LIMIT = 100

const ROLE_FILTERS: { value: '' | CounterpartyRole; title: string }[] = [
  { value: '', title: 'Все контрагенты' },
  { value: 'customer', title: 'Покупатели' },
  { value: 'local_supplier', title: 'Локальные поставщики' },
  { value: 'import_supplier', title: 'Импортные поставщики' },
]

export function CounterpartiesPage() {
  const [rows, setRows] = useState<Counterparty[]>([])
  const [role, setRole] = useState<'' | CounterpartyRole>('')
  const [search, setSearch] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    try {
      setRows(
        await fetchCounterparties({
          role: role === '' ? undefined : role,
          includeInactive: showInactive,
        }),
      )
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [role, showInactive])

  useEffect(() => {
    void reload()
  }, [reload])

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

  const toggle = async (row: Counterparty) => {
    setBusy(true)
    setError(null)
    try {
      await updateCounterparty(row.id, { is_active: !row.is_active })
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const needle = search.trim().toLowerCase()
  const filtered = rows
    .filter((row) => (showInactive ? true : row.is_active))
    .filter((row) => (needle ? row.name.toLowerCase().includes(needle) : true))
  const visible = filtered.slice(0, VISIBLE_LIMIT)

  return (
    <section>
      <header className="page-head">
        <h1>Контрагенты</h1>
        <p className="hint">
          Покупатели, локальные и импортные поставщики. Одна компания может быть и покупателем, и
          поставщиком — это одна запись с двумя признаками. В плане продаж выбираются только
          покупатели.
        </p>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

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
          Найдено: <strong data-testid="counterparties-count">{filtered.length}</strong>
          {filtered.length > VISIBLE_LIMIT ? `, показаны первые ${VISIBLE_LIMIT}` : null}
        </span>
      </div>

      <table data-testid="counterparties-table">
        <thead>
          <tr>
            <th scope="col">Наименование</th>
            <th scope="col">Роли</th>
            <th scope="col">ИНН</th>
            <th scope="col">Источник</th>
            <th scope="col">Состояние</th>
            <th scope="col" />
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 ? (
            <tr>
              <td colSpan={6} className="hint">
                Контрагентов не найдено.
              </td>
            </tr>
          ) : (
            visible.map((row) => (
              <tr key={row.id}>
                <td>{row.name}</td>
                <td>{counterpartyRoles(row).join(', ') || '—'}</td>
                <td>{row.inn ?? '—'}</td>
                <td>{row.source === '1c' ? '1С' : 'вручную'}</td>
                <td>
                  <span className={row.is_active ? 'badge status-approved' : 'badge'}>
                    {row.is_active ? 'Активен' : 'Отключён'}
                  </span>
                </td>
                <td>
                  <button
                    type="button"
                    className="mini"
                    disabled={busy}
                    onClick={() => toggle(row)}
                  >
                    {row.is_active ? 'Отключить' : 'Включить'}
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
