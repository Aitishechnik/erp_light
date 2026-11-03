import { useEffect, useMemo, useState } from 'react'
import type { AuditEvent, SessionUser } from './api'
import {
  cleanupJournal,
  errorMessage,
  fetchCleanupSuggestion,
  fetchJournal,
  fetchMessages,
  markAllMessagesRead,
} from './api'
import { PageHelp } from './PageHelp'

type Props = { user: SessionUser }

/** Сколько последних событий журнала показываем. */
const JOURNAL_PAGE = 100

function plural(count: number, forms: [string, string, string]): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1]
  return forms[2]
}

/** Роль под именем не дублируем: «Коммерческий директор (демо)» + «Коммерческий директор». */
function showRole(row: AuditEvent): boolean {
  const role = row.actor_role_title
  const name = row.actor_name
  if (!role || !name) return false
  return !name.toLowerCase().startsWith(role.toLowerCase())
}

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
  const [cleanup, setCleanup] = useState<{ year: number; events: number } | null>(null)

  useEffect(() => {
    let alive = true
    Promise.all([
      fetchJournal({ limit: JOURNAL_PAGE }),
      fetchMessages({ limit: 100 }),
      fetchCleanupSuggestion().catch(() => null),
    ])
      .then(([journal, inbox, suggestion]) => {
        if (!alive) return
        setRows(journal)
        setMessages(inbox.rows)
        setUnread(inbox.unread)
        setCleanup(suggestion)
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

  const cleanUp = async () => {
    if (!cleanup) return
    if (!window.confirm(`Удалить записи журнала за ${cleanup.year} год? Действие необратимо.`)) {
      return
    }
    setBusy(true)
    try {
      const done = await cleanupJournal(cleanup.year)
      setCleanup(null)
      setRows(await fetchJournal({ limit: JOURNAL_PAGE }))
      setError(`Журнал за ${cleanup.year} год очищен: удалено записей ${done.deleted}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <header className="page-head">
        <h1>Служебные сообщения</h1>
        <PageHelp>
          Журнал фиксирует действия, которые меняют планы, справочники и поступления.
          {user.role === 'executive_director'
            ? ' Исполнительный директор видит действия всех сотрудников.'
            : ' Здесь ваши действия и сообщения, адресованные вам.'}{' '}
          Непрочитанные — в колокольчике, прочитанные остаются здесь.
        </PageHelp>
      </header>
      <div className="toolbar messages-toolbar">
        <input
          className="audit-search"
          aria-label="Поиск по журналу"
          placeholder="Событие, объект, сотрудник"
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
        <span className="status-chip" data-testid="messages-unread">
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
      {cleanup ? (
        <div className="cleanup-box" data-testid="cleanup-box">
          <span>
            За {cleanup.year} год в журнале {cleanup.events}{' '}
            {plural(cleanup.events, ['запись', 'записи', 'записей'])}. Очистка удаляет их
            безвозвратно — оставить только текущий год?
          </span>
          <button
            type="button"
            className="mini danger"
            disabled={busy}
            onClick={() => void cleanUp()}
          >
            Удалить журнал за {cleanup.year} год
          </button>
        </div>
      ) : null}
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
                    {showRole(row) ? <div className="hint">{row.actor_role_title}</div> : null}
                  </td>
                  <td>{row.action_title}</td>
                  <td>
                    {row.link && row.entity_label ? (
                      <a className="audit-link" href={row.link}>
                        {row.entity_label}
                      </a>
                    ) : (
                      (row.entity_label ?? '—')
                    )}
                  </td>
                  <td className="wrap">
                    {row.link ? (
                      <a className="audit-link" href={row.link}>
                        {row.summary}
                      </a>
                    ) : (
                      row.summary
                    )}
                  </td>
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
