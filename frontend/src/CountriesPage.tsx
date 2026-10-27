import { type FormEvent, useCallback, useEffect, useState } from 'react'
import {
  type Country,
  createCountry,
  errorMessage,
  fetchCountries,
  type SessionUser,
  updateCountry,
} from './api'

const EMPTY_FORM = { name: '', delivery_days: '30' }

function parseDays(raw: string): number | null {
  const value = Number(raw)
  return Number.isInteger(value) && value >= 1 && value <= 365 ? value : null
}

export function CountriesPage({ user, focusId }: { user: SessionUser; focusId?: string }) {
  const [rows, setRows] = useState<Country[]>([])
  const [search, setSearch] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [editing, setEditing] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDays, setEditDays] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const canEdit = user.role === 'purchase_director'

  const reload = useCallback(async () => {
    try {
      setRows(await fetchCountries({ includeInactive: showInactive }))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [showInactive])

  useEffect(() => {
    void reload()
  }, [reload])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const days = parseDays(form.delivery_days)
    if (!form.name.trim()) {
      setError('Укажите название страны')
      return
    }
    if (days === null) {
      setError('Срок доставки — целое число дней от 1 до 365')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await createCountry({ name: form.name, delivery_days: days })
      setForm(EMPTY_FORM)
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (row: Country) => {
    setEditing(row.id)
    setEditName(row.name)
    setEditDays(String(row.delivery_days))
    setError(null)
  }

  const saveEdit = async (row: Country) => {
    const days = parseDays(editDays)
    if (!editName.trim()) {
      setError('Название страны не может быть пустым')
      return
    }
    if (days === null) {
      setError('Срок доставки — целое число дней от 1 до 365')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await updateCountry(row.id, { name: editName, delivery_days: days })
      setEditing(null)
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (row: Country) => {
    setBusy(true)
    setError(null)
    try {
      await updateCountry(row.id, { is_active: !row.is_active })
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const needle = search.trim().toLowerCase()
  const filtered = rows.filter((row) => (needle ? row.name.toLowerCase().includes(needle) : true))

  return (
    <section>
      <header className="page-head">
        <h1>Страны</h1>
        <p className="hint">
          Страна происхождения сырья и срок доставки. План закупок сдвигает месяц заказа назад ровно
          на этот срок: январская потребность при сроке 90 дней заказывается в октябре.
        </p>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {canEdit ? (
        <form className="inline-form" onSubmit={submit}>
          <input
            aria-label="Название страны"
            placeholder="Название"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
          <label className="inline-field">
            Срок доставки, дней
            <input
              aria-label="Срок доставки, дней"
              type="number"
              min={1}
              max={365}
              value={form.delivery_days}
              onChange={(event) => setForm({ ...form, delivery_days: event.target.value })}
              required
            />
          </label>
          <button type="submit" className="primary" disabled={busy}>
            Добавить
          </button>
        </form>
      ) : (
        <p className="hint">Справочник стран ведёт директор по закупкам — здесь только просмотр.</p>
      )}

      <div className="toolbar">
        <input
          aria-label="Поиск по стране"
          placeholder="Поиск по названию"
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
          Найдено: <strong data-testid="countries-count">{filtered.length}</strong>
        </span>
      </div>

      <table data-testid="countries-table">
        <thead>
          <tr>
            <th scope="col">Название</th>
            <th scope="col" className="num">
              Срок доставки
            </th>
            <th scope="col">Состояние</th>
            {canEdit ? <th scope="col" aria-label="Действия" /> : null}
          </tr>
        </thead>
        <tbody>
          {filtered.length === 0 ? (
            <tr>
              <td colSpan={canEdit ? 4 : 3} className="hint" data-testid="countries-empty">
                Стран пока нет.
              </td>
            </tr>
          ) : (
            filtered.map((row) => {
              const isEditing = editing === row.id
              return (
                <tr
                  key={row.id}
                  data-testid={`country-row-${row.id}`}
                  className={row.id === focusId ? 'focus-row' : undefined}
                >
                  <td>
                    {isEditing ? (
                      <input
                        aria-label={`Название страны ${row.name}`}
                        value={editName}
                        onChange={(event) => setEditName(event.target.value)}
                      />
                    ) : (
                      row.name
                    )}
                  </td>
                  <td className="num">
                    {isEditing ? (
                      <input
                        className="cell"
                        type="number"
                        min={1}
                        max={365}
                        aria-label={`Срок доставки ${row.name}`}
                        value={editDays}
                        onChange={(event) => setEditDays(event.target.value)}
                      />
                    ) : (
                      `${row.delivery_days} дн`
                    )}
                  </td>
                  <td>
                    <span className={row.is_active ? 'badge status-approved' : 'badge'}>
                      {row.is_active ? 'Активна' : 'Отключена'}
                    </span>
                  </td>
                  {canEdit ? (
                    <td>
                      {isEditing ? (
                        <>
                          <button
                            type="button"
                            className="mini"
                            disabled={busy}
                            onClick={() => void saveEdit(row)}
                          >
                            Сохранить
                          </button>
                          <button
                            type="button"
                            className="mini"
                            disabled={busy}
                            onClick={() => setEditing(null)}
                          >
                            Отмена
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="mini"
                            disabled={busy}
                            onClick={() => startEdit(row)}
                          >
                            Изменить
                          </button>
                          <button
                            type="button"
                            className="mini"
                            disabled={busy}
                            onClick={() => void toggle(row)}
                          >
                            {row.is_active ? 'Отключить' : 'Включить'}
                          </button>
                        </>
                      )}
                    </td>
                  ) : null}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </section>
  )
}
