import { useCallback, useEffect, useRef, useState } from 'react'
import type { AuditEvent } from './api'
import {
  errorMessage,
  fetchMessages,
  fetchUnreadCount,
  markAllMessagesRead,
  markMessagesRead,
} from './api'

type Props = {
  /** Переход в полный журнал действий. */
  onOpenJournal: () => void
}

function formatTime(value: string): string {
  const date = new Date(value)
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function rowTitle(row: AuditEvent): string {
  if (row.link) return row.read ? 'Открыть сообщение' : 'Открыть и отметить прочитанным'
  return 'Отметить прочитанным'
}

function rowAriaLabel(row: AuditEvent): string {
  return `${rowTitle(row)}: ${row.summary}`
}

/**
 * Колокольчик служебных сообщений.
 *
 * Счётчик непрочитанных обновляется при входе и после каждого открытия панели:
 * отдельного «живого» канала нет — сообщения приходят на действия пользователей,
 * а не мгновенно.
 *
 * Панель показывает только непрочитанное: клик по строке отмечает сообщение
 * прочитанным и убирает его из списка. Прочитанные и все действия остаются
 * в журнале — туда ведёт кнопка «Весь журнал».
 */
export function NotificationsBell({ onOpenJournal }: Props) {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [rows, setRows] = useState<AuditEvent[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const panelRef = useRef<HTMLDivElement | null>(null)

  const refreshCount = useCallback(async () => {
    try {
      const data = await fetchUnreadCount()
      setUnread(data.unread)
    } catch {
      // Колокольчик не должен мешать работе: ошибку счётчика молча пропускаем.
    }
  }, [])

  useEffect(() => {
    void refreshCount()
  }, [refreshCount])

  // Клик мимо панели и Esc закрывают её: панель не должна перехватывать меню.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onPointer = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onPointer)
    }
  }, [open])

  /** В панель попадают только непрочитанные: прочитанное живёт в журнале. */
  const loadUnread = useCallback(async () => {
    const data = await fetchMessages({ unread: true, limit: 20 })
    setRows(data.rows.filter((row) => !row.read))
    setUnread(data.unread)
    setError('')
  }, [])

  const showPanel = async () => {
    const next = !open
    setOpen(next)
    if (!next) return
    try {
      await loadUnread()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const readAll = async () => {
    setBusy(true)
    try {
      const data = await markAllMessagesRead()
      setUnread(data.unread)
      setRows([])
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  /** Одно сообщение: отмечаем прочитанным и сразу гасим строку и счётчик. */
  const readOne = useCallback(
    async (row: AuditEvent) => {
      if (row.read) return
      setRows((current) => current.filter((item) => item.id !== row.id))
      setUnread((current) => Math.max(0, current - 1))
      try {
        const data = await markMessagesRead([row.id])
        setUnread(data.unread)
      } catch (err) {
        // Не получилось — возвращаем список непрочитанных с сервера.
        setError(errorMessage(err))
        void loadUnread().catch(() => undefined)
        void refreshCount()
      }
    },
    [loadUnread, refreshCount],
  )

  const openRow = (row: AuditEvent) => {
    void readOne(row)
    if (row.link) {
      setOpen(false)
      window.location.hash = row.link
    }
  }

  const hasUnreadRows = rows.some((row) => !row.read)
  return (
    <div className="bell" ref={panelRef}>
      <button
        type="button"
        className={unread > 0 ? 'bell-button has-unread' : 'bell-button'}
        aria-label={`Служебные сообщения, непрочитанных: ${unread}`}
        aria-expanded={open}
        onClick={() => void showPanel()}
      >
        <svg
          className="bell-icon"
          viewBox="0 0 24 24"
          width="18"
          height="18"
          aria-hidden="true"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M18 8a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6" />
          <path d="M10.3 19a2 2 0 0 0 3.4 0" />
        </svg>
        <span className="bell-title">Сообщения</span>
        {unread > 0 ? (
          <span className="bell-badge" data-testid="bell-badge">
            {unread > 99 ? '99+' : unread}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="bell-panel" role="dialog" aria-label="Служебные сообщения">
          <div className="bell-head">
            <strong>Служебные сообщения</strong>
            <span className="bell-count" data-testid="bell-count">
              непрочитанных: {unread}
            </span>
            <button type="button" className="mini" onClick={() => setOpen(false)}>
              Закрыть
            </button>
          </div>
          {error ? <p className="hint error">{error}</p> : null}
          {hasUnreadRows ? (
            <p className="hint bell-hint" data-testid="bell-hint">
              Нажмите на сообщение — оно откроется и станет прочитанным.
            </p>
          ) : null}
          {rows.length === 0 ? (
            <p className="hint" data-testid="bell-empty">
              Непрочитанных нет — все сообщения в журнале.
            </p>
          ) : (
            <ul className="bell-list" data-testid="bell-list">
              {rows.map((row) => {
                const actionable = !row.read || Boolean(row.link)
                return (
                  <li
                    key={row.id}
                    className={row.read ? 'bell-row read' : 'bell-row'}
                    data-testid={`bell-row-${row.id}`}
                    role={actionable ? 'button' : undefined}
                    tabIndex={actionable ? 0 : undefined}
                    aria-label={actionable ? rowAriaLabel(row) : undefined}
                    title={actionable ? rowTitle(row) : undefined}
                    onClick={actionable ? () => openRow(row) : undefined}
                    onKeyDown={
                      actionable
                        ? (event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              openRow(row)
                            }
                          }
                        : undefined
                    }
                  >
                    <span className="bell-time">{formatTime(row.created_at)}</span>
                    <span className="bell-text">
                      <span className="bell-summary">
                        {row.link ? <span className="audit-link">{row.summary}</span> : row.summary}
                      </span>
                      <span className="bell-meta">
                        {row.actor_name ?? 'Система'}
                        {row.actor_role_title &&
                        row.actor_name &&
                        !row.actor_name.toLowerCase().startsWith(row.actor_role_title.toLowerCase())
                          ? ` · ${row.actor_role_title}`
                          : ''}
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
          {unread > rows.length ? (
            <p className="hint bell-more" data-testid="bell-more">
              Показаны последние {rows.length} — остальные в журнале.
            </p>
          ) : null}
          <div className="bell-actions">
            <button
              type="button"
              className="mini"
              disabled={busy || unread === 0}
              onClick={() => void readAll()}
            >
              Отметить всё прочитанным
            </button>
            <button
              type="button"
              className="mini"
              onClick={() => {
                setOpen(false)
                onOpenJournal()
              }}
            >
              Весь журнал
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
