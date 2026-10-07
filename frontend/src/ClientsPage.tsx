import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { type Client, createClient, errorMessage, fetchClients, updateClient } from './api'

const EMPTY_FORM = { name: '', inn: '', note: '' }

export function ClientsPage() {
  const [rows, setRows] = useState<Client[]>([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [showInactive, setShowInactive] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    try {
      setRows(await fetchClients(true))
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
      await createClient({
        name: form.name,
        inn: form.inn.trim() === '' ? null : form.inn.trim(),
        note: form.note.trim() === '' ? null : form.note.trim(),
      })
      setForm(EMPTY_FORM)
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (client: Client) => {
    setBusy(true)
    setError(null)
    try {
      await updateClient(client.id, { is_active: !client.is_active })
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const visible = rows.filter((row) => (showInactive ? true : row.is_active))
  const active = rows.filter((row) => row.is_active)

  return (
    <section>
      <header className="page-head">
        <h1>Клиенты</h1>
        <p className="hint">
          Клиенты, по которым составляется годовой план продаж. Отключённые нельзя выбрать в новом
          плане, но уже сохранённые строки остаются на месте.
        </p>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      <form className="inline-form" onSubmit={submit}>
        <input
          aria-label="Наименование клиента"
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
        <button type="submit" className="primary" disabled={busy}>
          Добавить
        </button>
      </form>

      <div className="toolbar">
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
          Активных клиентов: <strong data-testid="clients-count">{active.length}</strong>
        </span>
      </div>

      <table data-testid="clients-table">
        <thead>
          <tr>
            <th scope="col">Наименование</th>
            <th scope="col">ИНН</th>
            <th scope="col">Примечание</th>
            <th scope="col">Состояние</th>
            <th scope="col" />
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 ? (
            <tr>
              <td colSpan={5} className="hint">
                Клиентов пока нет — добавьте первого.
              </td>
            </tr>
          ) : (
            visible.map((client) => (
              <tr key={client.id}>
                <td>{client.name}</td>
                <td>{client.inn ?? '—'}</td>
                <td>{client.note ?? '—'}</td>
                <td>
                  <span className={client.is_active ? 'badge status-approved' : 'badge'}>
                    {client.is_active ? 'Активен' : 'Отключён'}
                  </span>
                </td>
                <td>
                  <button
                    type="button"
                    className="mini"
                    disabled={busy}
                    onClick={() => toggle(client)}
                  >
                    {client.is_active ? 'Отключить' : 'Включить'}
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
