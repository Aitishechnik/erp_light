import { useCallback, useEffect, useRef, useState } from 'react'
import type { AuditEvent } from './api'
import { errorMessage, fetchMessages, fetchUnreadCount, markAllMessagesRead } from './api'

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

/**
 * Колокольчик служебных сообщений.
 *
 * Счётчик непрочитанных обновляется при входе и после каждого открытия панели:
 * отдельного «живого» канала нет — сообщения приходят на действия пользователей,
 * а не мгновенно.
 */
export function NotificationsBell({ onOpenJournal }: Props) {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [rows, setRows] = useState<AuditEvent[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [canScroll, setCanScroll] = useState(false)
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

  // Список длиннее окна — показываем подсказку, что есть ещё. Меряем после
  // отрисовки: ref-callback срабатывает, когда список уже в DOM и посчитан.
  const listRef = useCallback((node: HTMLUListElement | null) => {
    if (!node) return
    requestAnimationFrame(() => {
      setCanScroll(node.scrollHeight > node.clientHeight + 1)
    })
  }, [])

  const showPanel = async () => {
    const next = !open
    setOpen(next)
    if (!next) return
    try {
      const data = await fetchMessages({ limit: 20 })
      setRows(data.rows)
      setUnread(data.unread)
      setTotal(data.total)
      setError('')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const readAll = async () => {
    setBusy(true)
    try {
      const data = await markAllMessagesRead()
      setUnread(data.unread)
      setRows((current) => current.map((row) => ({ ...row, read: true })))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const shown = rows.length
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
        <span className="bell-title">Служебные сообщения</span>
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
              показано {shown} из {total}
            </span>
            <button type="button" className="mini" onClick={() => setOpen(false)}>
              Закрыть
            </button>
          </div>
          {error ? <p className="hint error">{error}</p> : null}
          {rows.length === 0 ? (
            <p className="hint" data-testid="bell-empty">
              Новых сообщений нет.
            </p>
          ) : (
            <>
              <ul className="bell-list" data-testid="bell-list" ref={listRef}>
                {rows.map((row) => (
                  <li key={row.id} className={row.read ? 'bell-row read' : 'bell-row'}>
                    <span className="bell-time">{formatTime(row.created_at)}</span>
                    <span className="bell-text">
                      <span className="bell-summary">
                        {row.link ? (
                          <a className="audit-link" href={row.link} onClick={() => setOpen(false)}>
                            {row.summary}
                          </a>
                        ) : (
                          row.summary
                        )}
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
                ))}
              </ul>
              {canScroll ? (
                <p className="hint bell-more" data-testid="bell-more">
                  Прокрутите список — есть ещё сообщения.
                </p>
              ) : null}
            </>
          )}
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
