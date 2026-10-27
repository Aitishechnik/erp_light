import { useEffect, useMemo, useState } from 'react'
import type { AuditEvent, SessionUser } from './api'
import { errorMessage, fetchJournal, fetchMessages, markAllMessagesRead } from './api'

type Props = { user: SessionUser }

function formatTime(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Служебные сообщения и журнал действий.
 *
 * Исполнительный директор видит все действия, остальные — только свои:
 * разделение делает сервер, страница показывает то, что пришло.
 */
export function MessagesPage({ user }: Props) {
  const [rows, setRows] = useState<AuditEvent[]>([])
  const [messages, setMessages] = useState<AuditEvent[]>([])
  const [unread, setUnread] = useState(0)
  const [search, setSearch] = useState('')
  const [onlyMessages, setOnlyMessages] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    Promise.all([fetchJournal({ limit: 100 }), fetchMessages({ limit: 100 })])
      .then(([journal, inbox]) => {
        if (!alive) return
        setRows(journal)
        setMessages(inbox.rows)
        setUnread(inbox.unread)
      })
      .catch((err) => {
        if (alive) setError(errorMessage(err))
      })
    return () => {
      alive = false
    }
  }, [])

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const source = onlyMessages
      ? rows.filter((row) => messages.some((item) => item.id === row.id))
      : rows
    if (!needle) return source
    return source.filter((row) =>
      [row.summary, row.action_title, row.actor_name ?? '', row.entity_label ?? '']
        .join(' ')
        .toLowerCase()
        .includes(needle),
    )
  }, [rows, messages, search, onlyMessages])

  const readAll = async () => {
    setBusy(true)
    try {
      const data = await markAllMessagesRead()
      setUnread(data.unread)
      setMessages((current) => current.map((row) => ({ ...row, read: true })))
      setRows((current) => current.map((row) => ({ ...row, read: true })))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h1>Служебные сообщения</h1>
      <p className="hint">
        Журнал фиксирует действия, которые меняют планы, справочники и поступления.
        {user.role === 'executive_director'
          ? ' Исполнительный директор видит действия всех сотрудников.'
          : ' Здесь видны только ваши действия.'}
      </p>
      <div className="toolbar">
        <input
          aria-label="Поиск по журналу"
          placeholder="Поиск: событие, объект, сотрудник"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="check">
          <input
            type="checkbox"
            checked={onlyMessages}
            onChange={(event) => setOnlyMessages(event.target.checked)}
          />
          только служебные сообщения
        </label>
        <span className="hint" data-testid="messages-unread">
          Непрочитанных: {unread}
        </span>
        <button
          type="button"
          className="mini"
          disabled={busy || unread === 0}
          onClick={() => void readAll()}
        >
          Отметить всё прочитанным
        </button>
      </div>
      {error ? <p className="hint error">{error}</p> : null}
      {visible.length === 0 ? (
        <p className="hint" data-testid="messages-empty">
          Пока ничего не записано.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="audit-table" data-testid="audit-table">
            <thead>
              <tr>
                <th scope="col">Когда</th>
                <th scope="col">Кто</th>
                <th scope="col">Событие</th>
                <th scope="col">Объект</th>
                <th scope="col">Что произошло</th>
                <th scope="col" className="col-level">
                  Уровень
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.id} data-testid={`audit-${row.action}`}>
                  <td className="nowrap">{formatTime(row.created_at)}</td>
                  <td>
                    {row.actor_name ?? 'Система'}
                    <div className="hint">{row.actor_role_title ?? ''}</div>
                  </td>
                  <td>{row.action_title}</td>
                  <td>{row.entity_label ?? '—'}</td>
                  <td className="wrap">{row.summary}</td>
                  <td>
                    <span
                      className={`badge ${row.level === 'critical' ? 'badge-critical' : 'badge-info'}`}
                    >
                      {row.level === 'critical' ? 'критическое' : 'рабочее'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
