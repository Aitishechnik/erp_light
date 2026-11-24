import { useCallback, useEffect, useState } from 'react'
import { type AuditEvent, errorMessage, fetchAdminJournal } from './api'
import { PageHelp } from './PageHelp'

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
 * Отдельный журнал администратора: только его действия.
 *
 * Обычный журнал показывает действия пользователей, поэтому здесь чисто:
 * смена прав, заведение сотрудников, сброс паролей и бизнес-правки админа.
 */
export function AdminLogPage() {
  const [rows, setRows] = useState<AuditEvent[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setRows(await fetchAdminJournal({ limit: 100 }))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  return (
    <section>
      <header className="page-head">
        <h1>Действия администратора</h1>
        <PageHelp>
          Здесь только действия администратора: сотрудники, права уровней и его правки данных.
          Действия пользователей остаются в «Служебных сообщениях». Журнал только для чтения.
        </PageHelp>
      </header>

      {error ? <p className="error">{error}</p> : null}
      <div className="toolbar">
        <button type="button" className="mini" disabled={busy} onClick={() => void reload()}>
          Обновить
        </button>
        <span className="hint">Показано событий: {rows.length}</span>
      </div>

      {rows.length === 0 && !busy ? (
        <div className="empty-state">
          <strong>Действий администратора пока нет.</strong>
          <span>Здесь появятся заведение сотрудников и изменения прав.</span>
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Когда</th>
                <th>Действие</th>
                <th>Что именно</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{formatTime(row.created_at)}</td>
                  <td>{row.action_title}</td>
                  <td>{row.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
