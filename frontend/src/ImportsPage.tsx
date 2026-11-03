import { type ChangeEvent, Fragment, useCallback, useEffect, useState } from 'react'
import {
  errorMessage,
  fetchImportKinds,
  fetchImports,
  type ImportKind,
  type ImportSession,
  isAdmin,
  type SessionUser,
  uploadImport,
} from './api'
import { PageHelp } from './PageHelp'

/** Компактная дата: «08.10.26 01:59» — иначе журнал не влезает по ширине. */
function stamp(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const STATUS_TITLES: Record<string, string> = {
  ok: 'загружено',
  partial: 'загружено с замечаниями',
  failed: 'ошибка',
}

/** Сколько загрузок показываем сразу и прибавляем кнопкой; больше 200 сервер не отдаёт. */
const IMPORTS_PAGE = 20
const MAX_IMPORTS_LIMIT = 200

export function ImportsPage({ user }: { user?: SessionUser }) {
  const [kinds, setKinds] = useState<ImportKind[]>([])
  const [journal, setJournal] = useState<ImportSession[]>([])
  const [limit, setLimit] = useState(IMPORTS_PAGE)
  const [files, setFiles] = useState<Record<string, File | null>>({})
  const [results, setResults] = useState<Record<string, ImportSession>>({})
  const [busyKind, setBusyKind] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [loadedKinds, loadedJournal] = await Promise.all([
        fetchImportKinds(),
        fetchImports(limit),
      ])
      setKinds(loadedKinds)
      setJournal(loadedJournal)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [limit])

  useEffect(() => {
    void reload()
  }, [reload])

  const pick = (kind: string, event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null
    setFiles((current) => ({ ...current, [kind]: file }))
  }

  const send = async (kind: string) => {
    const file = files[kind]
    if (!file) return
    setBusyKind(kind)
    setError(null)
    try {
      const result = await uploadImport(kind, file)
      setResults((current) => ({ ...current, [kind]: result }))
      setFiles((current) => ({ ...current, [kind]: null }))
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyKind(null)
    }
  }

  return (
    <section>
      <header className="page-head">
        <h1>Загрузка данных</h1>
        <PageHelp>
          Файлы выгрузок из 1С в формате .xlsx. Номенклатура опознаётся по коду 1С, контрагенты — по
          наименованию, поэтому повторная загрузка не создаёт дублей, а обновляет найденные записи.
        </PageHelp>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="import-cards">
        {kinds
          .filter((kind) => !user || isAdmin(user) || kind.roles.includes(user.role))
          .map((kind) => {
            const result = results[kind.kind]
            return (
              <article
                className="import-card"
                key={kind.kind}
                data-testid={`import-card-${kind.kind}`}
              >
                <h2>{kind.title}</h2>
                <p className="hint">Колонки: {kind.columns.join(', ')}</p>
                {kind.note ? <PageHelp label="Как читается файл">{kind.note}</PageHelp> : null}
                <input
                  type="file"
                  accept=".xlsx"
                  aria-label={`Файл: ${kind.title}`}
                  onChange={(event) => pick(kind.kind, event)}
                />
                <button
                  type="button"
                  className="primary"
                  disabled={!files[kind.kind] || busyKind !== null}
                  onClick={() => void send(kind.kind)}
                >
                  {busyKind === kind.kind ? 'Загрузка…' : 'Загрузить'}
                </button>
                {result ? (
                  <p className="import-result" data-testid={`import-result-${kind.kind}`}>
                    Создано: <strong>{result.rows_created}</strong>, обновлено:{' '}
                    <strong>{result.rows_updated}</strong>, пропущено дублей:{' '}
                    <strong>{result.rows_skipped}</strong>, ошибок:{' '}
                    <strong>{result.rows_failed}</strong> (
                    {STATUS_TITLES[result.status] ?? result.status})
                  </p>
                ) : null}
              </article>
            )
          })}
      </div>

      <h2 className="section-title">Журнал загрузок</h2>
      <table className="journal-table" data-testid="imports-journal">
        <thead>
          <tr>
            <th scope="col">Когда</th>
            <th scope="col">Тип данных</th>
            <th scope="col">Файл</th>
            <th scope="col" className="num">
              Всего
            </th>
            <th scope="col" className="num">
              Создано
            </th>
            <th scope="col" className="num">
              Обновлено
            </th>
            <th scope="col" className="num">
              Дублей
            </th>
            <th scope="col" className="num">
              Ошибок
            </th>
          </tr>
        </thead>
        <tbody>
          {journal.length === 0 ? (
            <tr>
              <td colSpan={8} className="hint">
                Загрузок пока не было.
              </td>
            </tr>
          ) : (
            journal.map((row) => (
              <Fragment key={row.id}>
                <tr>
                  <td>{stamp(row.created_at)}</td>
                  <td>{row.kind_title}</td>
                  <td>{row.file_name}</td>
                  <td className="num">{row.rows_total}</td>
                  <td className="num">{row.rows_created}</td>
                  <td className="num">{row.rows_updated}</td>
                  <td className="num">{row.rows_skipped}</td>
                  <td className="num">{row.rows_failed}</td>
                </tr>
                {row.message ? (
                  <tr className="journal-note">
                    <td colSpan={8} className="hint">
                      {row.message}
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))
          )}
        </tbody>
      </table>

      {journal.length >= limit && limit < MAX_IMPORTS_LIMIT ? (
        <div className="table-more">
          <span className="hint" data-testid="imports-shown">
            Показаны последние {journal.length} загрузок
          </span>
          <button
            type="button"
            className="mini"
            onClick={() => setLimit((value) => Math.min(value + IMPORTS_PAGE, MAX_IMPORTS_LIMIT))}
          >
            Показать ещё {IMPORTS_PAGE}
          </button>
        </div>
      ) : null}
    </section>
  )
}
