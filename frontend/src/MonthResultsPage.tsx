import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import {
  clearMonthReason,
  closeMonth,
  createTransferDrafts,
  errorMessage,
  fetchMonthResult,
  fetchPlanningProducts,
  formatDate,
  formatMoney,
  formatQuantity,
  type MonthDecisionIn,
  type MonthResult,
  type MonthRow,
  type MonthUnmatched,
  matchMonthRow,
  type Product,
  reopenMonth,
  type SessionUser,
  saveMonthReason,
  setMonthDecision,
  type TransferDrafts,
} from './api'
import { PageHelp } from './PageHelp'

const MONTH_NAMES = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь',
]

const GROUP_TITLES: Record<MonthRow['group'], string> = {
  plan: 'по плану',
  extra: 'вне плана',
  short: 'не продано',
}

const MATCH_ROLES = ['commercial_director', 'executive_director']
/** Кто ставит причины: менеджер по своим строкам, коммерческий директор и админ — по всем. */
const REASON_ROLES = ['sales_manager', 'commercial_director', 'executive_director']
/** Кто закрывает месяц и принимает решение. */
const CLOSE_ROLES = ['commercial_director', 'executive_director']

/** Следующий месяц от показанного — вариант переноса по умолчанию. */
function shiftMonth(year: number, month: number, delta: number): { year: number; month: number } {
  const index = year * 12 + (month - 1) + delta
  return { year: Math.floor(index / 12), month: (index % 12) + 1 }
}

function targetValue(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}`
}

/** Исполнение плана: процент считаем только там, где план есть. */
function share(fact: string, plan: string): string {
  const planned = Number(plan)
  if (!Number.isFinite(planned) || planned <= 0) return '—'
  const value = (Number(fact) / planned) * 100
  return `${value.toFixed(1).replace('.', ',')} %`
}

function signed(value: string): string {
  const number = Number(value)
  if (!Number.isFinite(number) || number === 0) return '0'
  return number > 0 ? `+${formatQuantity(String(number))}` : formatQuantity(String(number))
}

/** Сопоставление строки файла с номенклатурой: поиск и выбор карточки. */
function MatchBox({
  row,
  products,
  busy,
  onMatch,
}: {
  row: MonthUnmatched
  products: Product[]
  busy: boolean
  onMatch: (productId: string) => void
}) {
  const [query, setQuery] = useState(row.source_name)
  const [choice, setChoice] = useState('')
  const needle = query.trim().toLowerCase()
  const options = useMemo(() => {
    const found = needle
      ? products.filter((product) => product.name.toLowerCase().includes(needle))
      : products
    return found.slice(0, 40)
  }, [needle, products])

  return (
    <tr data-testid={`unmatched-${row.id}`}>
      <td>
        <div>{row.source_name}</div>
        <div className="hint">
          {row.client_name ?? 'клиент?'} · {formatQuantity(row.quantity)} ·{' '}
          {formatMoney(row.amount_rub)} ₽
        </div>
      </td>
      <td>
        <input
          aria-label={`Поиск номенклатуры для «${row.source_name}»`}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setChoice('')
          }}
        />
      </td>
      <td>
        {options.length === 0 ? (
          <div className="hint">Ничего не найдено — измените запрос</div>
        ) : null}
        <select
          aria-label={`Номенклатура для «${row.source_name}»`}
          value={choice}
          onChange={(event) => setChoice(event.target.value)}
        >
          <option value="">— выберите позицию —</option>
          {options.map((product) => (
            <option key={product.id} value={product.id}>
              {product.name} ({product.unit})
            </option>
          ))}
        </select>
      </td>
      <td>
        <button
          type="button"
          className="primary"
          disabled={!choice || busy}
          onClick={() => onMatch(choice)}
        >
          Сопоставить
        </button>
      </td>
    </tr>
  )
}

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; result: MonthResult }

export function MonthResultsPage({ user, focus }: { user: SessionUser; focus?: string[] }) {
  const today = new Date()
  const [year, setYear] = useState(focus?.[0] ? Number(focus[0]) : today.getFullYear())
  const [month, setMonth] = useState(focus?.[1] ? Number(focus[1]) : today.getMonth() + 1)
  const [state, setState] = useState<State>({ status: 'loading' })
  const [onlyDeviation, setOnlyDeviation] = useState(false)
  const [search, setSearch] = useState('')
  const [manager, setManager] = useState('')
  const [products, setProducts] = useState<Product[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [onlyNoReason, setOnlyNoReason] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [reasonCode, setReasonCode] = useState('')
  const [reasonComment, setReasonComment] = useState('')
  const [confirmClose, setConfirmClose] = useState(false)
  const [reopenOpen, setReopenOpen] = useState(false)
  const [reopenReason, setReopenReason] = useState('')
  const [decisionCode, setDecisionCode] = useState('')
  const [decisionTarget, setDecisionTarget] = useState(() => {
    const next = shiftMonth(today.getFullYear(), today.getMonth() + 1, 1)
    return targetValue(next.year, next.month)
  })
  const [decisionComment, setDecisionComment] = useState('')
  const [transferResult, setTransferResult] = useState<TransferDrafts | null>(null)

  const mayMatch = MATCH_ROLES.includes(user.role)
  const mayReason = REASON_ROLES.includes(user.role)
  const mayClose = CLOSE_ROLES.includes(user.role)

  const load = useCallback(async () => {
    setState({ status: 'loading' })
    try {
      const result = await fetchMonthResult(year, month)
      setState({ status: 'ready', result })
    } catch (error) {
      setState({ status: 'error', message: errorMessage(error) })
    }
  }, [year, month])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!mayMatch) return
    fetchPlanningProducts()
      .then(setProducts)
      .catch(() => setProducts([]))
  }, [mayMatch])

  // Открытый редактор причины подкручиваем в окно: строка может быть внизу списка.
  useEffect(() => {
    if (editing === null) return
    const node = document.querySelector('.reason-editor')
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'center' })
    }
  }, [editing])

  const result = state.status === 'ready' ? state.result : null

  // Решение в форме повторяет сохранённое, пока пользователь его не поменял.
  useEffect(() => {
    if (!result) return
    const next = shiftMonth(result.year, result.month, 1)
    setDecisionCode(result.decision?.code ?? '')
    setDecisionComment(result.decision?.comment ?? '')
    setDecisionTarget(
      result.decision?.target_year && result.decision.target_month
        ? targetValue(result.decision.target_year, result.decision.target_month)
        : targetValue(next.year, next.month),
    )
  }, [result])

  const managers = useMemo(() => {
    const map = new Map<string, string>()
    for (const row of result?.rows ?? []) {
      map.set(row.manager_id ?? '', row.manager_name ?? 'Менеджер не определён')
    }
    return [...map.entries()]
  }, [result])

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (result?.rows ?? [])
      .filter((row) => (onlyDeviation ? Number(row.deviation) !== 0 : true))
      .filter((row) => (onlyNoReason ? Number(row.deviation) !== 0 && !row.reason : true))
      .filter((row) => (manager === '' ? true : (row.manager_id ?? '') === manager))
      .filter((row) =>
        needle
          ? `${row.client_name} ${row.product_name} ${row.manager_name ?? ''}`
              .toLowerCase()
              .includes(needle)
          : true,
      )
  }, [result, onlyDeviation, onlyNoReason, manager, search])

  const byManager = useMemo(() => {
    const map = new Map<string, { name: string; lines: number; extra: number; short: number }>()
    for (const row of result?.rows ?? []) {
      const key = row.manager_id ?? ''
      const current = map.get(key) ?? {
        name: row.manager_name ?? 'Менеджер не определён',
        lines: 0,
        extra: 0,
        short: 0,
      }
      current.lines += 1
      if (row.group === 'extra') current.extra += 1
      if (row.group === 'short') current.short += 1
      map.set(key, current)
    }
    return [...map.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name, 'ru'))
  }, [result])

  const openReason = (row: MonthRow) => {
    const key = `${row.client_id}:${row.product_id}`
    if (editing === key) {
      setEditing(null)
      return
    }
    setEditing(key)
    setReasonCode(row.reason?.code ?? '')
    setReasonComment(row.reason?.comment ?? '')
  }

  const saveReason = async (row: MonthRow) => {
    if (!reasonCode) return
    setBusy(true)
    setNotice(null)
    try {
      await saveMonthReason(
        year,
        month,
        row.client_id,
        row.product_id,
        reasonCode,
        reasonComment.trim() === '' ? null : reasonComment.trim(),
      )
      setEditing(null)
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const clearReason = async (row: MonthRow) => {
    setBusy(true)
    setNotice(null)
    try {
      await clearMonthReason(year, month, row.client_id, row.product_id)
      setEditing(null)
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const doClose = async () => {
    setBusy(true)
    setNotice(null)
    try {
      await closeMonth(year, month)
      setConfirmClose(false)
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const doReopen = async () => {
    if (reopenReason.trim() === '') return
    setBusy(true)
    setNotice(null)
    try {
      await reopenMonth(year, month, reopenReason.trim())
      setReopenOpen(false)
      setReopenReason('')
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const createDrafts = async () => {
    setBusy(true)
    setNotice(null)
    setTransferResult(null)
    try {
      setTransferResult(await createTransferDrafts(year, month))
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const saveDecision = async () => {
    if (decisionCode === '') return
    const [targetYear, targetMonth] = decisionTarget.split('-').map(Number)
    const payload: MonthDecisionIn = {
      decision: decisionCode as MonthDecisionIn['decision'],
      comment: decisionComment.trim() === '' ? null : decisionComment.trim(),
    }
    if (decisionCode !== 'accept') {
      payload.target_year = targetYear ?? null
      payload.target_month = targetMonth ?? null
    }
    setBusy(true)
    setNotice(null)
    try {
      await setMonthDecision(year, month, payload)
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const match = async (row: MonthUnmatched, productId: string) => {
    setBusy(true)
    setNotice(null)
    try {
      const outcome = await matchMonthRow(year, month, row.id, productId)
      setNotice(
        outcome.matched > 0
          ? `Сопоставлено строк: ${outcome.matched}. Осталось в очереди: ${outcome.remaining}`
          : 'Строка уже сопоставлена — обновите экран',
      )
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <header className="page-head">
        <h1>Итоги месяца</h1>
        <PageHelp>
          План продаж против факта из выгрузки 1С по клиенту и позиции. План — утверждённые планы
          менеджеров; факт — продажи за месяц, возвраты идут минусом. Сравнение по количеству: в
          плане продаж цен нет.
        </PageHelp>
      </header>

      <div className="toolbar">
        <label className="check">
          Год
          <input
            type="number"
            aria-label="Год итогов"
            min={2020}
            max={2100}
            value={year}
            onChange={(event) => setYear(Number(event.target.value) || today.getFullYear())}
          />
        </label>
        <select
          aria-label="Месяц итогов"
          value={month}
          onChange={(event) => setMonth(Number(event.target.value))}
        >
          {MONTH_NAMES.map((title, index) => (
            <option key={title} value={index + 1}>
              {title}
            </option>
          ))}
        </select>
        <select
          aria-label="Менеджер"
          value={manager}
          onChange={(event) => setManager(event.target.value)}
        >
          <option value="">Все менеджеры</option>
          {managers.map(([id, title]) => (
            <option key={id} value={id}>
              {title}
            </option>
          ))}
        </select>
        <label className="check">
          <input
            type="checkbox"
            checked={onlyDeviation}
            onChange={(event) => setOnlyDeviation(event.target.checked)}
          />
          только отклонения
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={onlyNoReason}
            onChange={(event) => setOnlyNoReason(event.target.checked)}
          />
          без причины
        </label>
        <input
          aria-label="Поиск по клиенту и позиции"
          placeholder="Клиент или позиция"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {result ? (
        <div className="month-state" data-testid="month-state">
          <span className={`badge ${result.status === 'closed' ? 'badge-closed' : 'badge-open'}`}>
            {result.status === 'closed' ? 'месяц закрыт' : 'месяц открыт'}
          </span>
          {result.status === 'closed' ? (
            <span className="hint">
              {`Снимок зафиксирован ${formatDate(result.closed_at)}, ${result.closed_by_name ?? '—'}. ${
                result.reopen_reason
                  ? `Месяц открывали заново — причина: «${result.reopen_reason}».`
                  : ''
              }`}
            </span>
          ) : null}
          {mayClose ? (
            result.status === 'closed' ? (
              <button type="button" className="mini" onClick={() => setReopenOpen(true)}>
                Открыть заново
              </button>
            ) : (
              <button type="button" className="primary" onClick={() => setConfirmClose(true)}>
                Закрыть месяц
              </button>
            )
          ) : null}
        </div>
      ) : null}

      {result && confirmClose && result.status === 'open' ? (
        <div className="month-confirm" data-testid="close-confirm">
          <p>
            Снимок зафиксирует план, факт, причины и решение. Строк: {result.lines}, без причины:{' '}
            {result.without_reason}
            {result.unmatched.length > 0
              ? `, в очереди сопоставления: ${result.unmatched.length}`
              : ''}
            .
          </p>
          <button type="button" className="primary" disabled={busy} onClick={() => void doClose()}>
            Закрыть месяц
          </button>
          <button type="button" className="mini" onClick={() => setConfirmClose(false)}>
            Отмена
          </button>
        </div>
      ) : null}

      {result && reopenOpen && result.status === 'closed' ? (
        <div className="month-confirm" data-testid="reopen-form">
          <p>Открыть месяц заново можно только с причиной — она попадёт в историю.</p>
          <input
            aria-label="Причина повторного открытия"
            placeholder="Что изменилось"
            value={reopenReason}
            onChange={(event) => setReopenReason(event.target.value)}
          />
          <button
            type="button"
            className="primary"
            disabled={busy || reopenReason.trim() === ''}
            onClick={() => void doReopen()}
          >
            Открыть заново
          </button>
          <button
            type="button"
            className="mini"
            onClick={() => {
              setReopenOpen(false)
              setReopenReason('')
            }}
          >
            Отмена
          </button>
        </div>
      ) : null}

      {state.status === 'error' ? (
        <p className="error" role="alert">
          {state.message}
        </p>
      ) : null}
      {state.status === 'loading' ? <p className="hint">Загрузка итогов…</p> : null}
      {notice ? <p className="hint">{notice}</p> : null}

      {result ? (
        <>
          {!result.plan_approved ? (
            <p className="error" role="status">
              На {result.year} год нет утверждённого плана продаж: сравнивать не с чем, все продажи
              считаются «вне плана».
            </p>
          ) : null}

          <p className="month-summary" data-testid="month-summary">
            Строк: <strong>{result.lines}</strong> · с отклонением:{' '}
            <strong>{result.deviation_lines}</strong> · вне плана:{' '}
            <strong>{result.extra_lines}</strong> · не продано:{' '}
            <strong>{result.short_lines}</strong> · без причины:{' '}
            <strong>{result.without_reason}</strong> · факт:{' '}
            <strong>{formatMoney(result.fact_amount)} ₽</strong>
          </p>

          <div className="month-decision" data-testid="month-decision">
            <h2>Решение месяца</h2>
            {result.decision ? (
              <p data-testid="month-decision-current">
                <strong>{result.decision.title}</strong>
                {result.decision.target_year && result.decision.target_month
                  ? ` → ${MONTH_NAMES[result.decision.target_month - 1]} ${result.decision.target_year}`
                  : ''}
                {result.decision.comment ? ` · ${result.decision.comment}` : ''}
                <span className="hint">
                  {' '}
                  — {result.decision.author_name ?? '—'}, {formatDate(result.decision.at)}
                </span>
              </p>
            ) : (
              <p className="hint">Решение не принято.</p>
            )}
            {mayClose && result.status === 'open' ? (
              <div className="month-decision-form">
                <select
                  aria-label="Решение месяца"
                  value={decisionCode}
                  onChange={(event) => setDecisionCode(event.target.value)}
                >
                  <option value="">— не принято —</option>
                  <option value="transfer_sales">Перенести в план продаж</option>
                  <option value="transfer_purchase">Перенести в план закупок</option>
                  <option value="accept">Принять как есть</option>
                </select>
                {decisionCode === 'transfer_sales' || decisionCode === 'transfer_purchase' ? (
                  <select
                    aria-label="Месяц переноса"
                    value={decisionTarget}
                    onChange={(event) => setDecisionTarget(event.target.value)}
                  >
                    {[1, 2, 3, 4, 5, 6].map((shift) => {
                      const target = shiftMonth(result.year, result.month, shift)
                      return (
                        <option
                          key={targetValue(target.year, target.month)}
                          value={targetValue(target.year, target.month)}
                        >
                          {MONTH_NAMES[target.month - 1]} {target.year}
                        </option>
                      )
                    })}
                  </select>
                ) : null}
                <input
                  aria-label="Комментарий к решению"
                  placeholder="Комментарий к решению"
                  value={decisionComment}
                  onChange={(event) => setDecisionComment(event.target.value)}
                />
                <button
                  type="button"
                  className="primary"
                  disabled={busy || decisionCode === ''}
                  onClick={() => void saveDecision()}
                >
                  Сохранить решение
                </button>
              </div>
            ) : null}
            {result.status === 'closed' &&
            result.decision?.code === 'transfer_sales' &&
            mayClose ? (
              <div className="month-decision-form">
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={() => void createDrafts()}
                >
                  Создать корректировки
                </button>
                <span className="hint">
                  Черновики планов менеджеров на месяц переноса; утверждать — в «Планировании
                  продаж».
                </span>
              </div>
            ) : null}

            {transferResult ? (
              <p className="hint" data-testid="transfer-result">
                {transferResult.created.length > 0
                  ? `Созданы черновики: ${transferResult.created
                      .map(
                        (row) =>
                          `${row.manager_name} — ${row.lines} стр., ${formatQuantity(row.quantity)} ед`,
                      )
                      .join('; ')}. `
                  : 'Черновики не созданы. '}
                {transferResult.skipped.length > 0
                  ? `Пропущено: ${transferResult.skipped
                      .map((row) => `${row.manager_name} — ${row.reason}`)
                      .join('; ')}. `
                  : ''}
                Утвердить корректировки можно в «Планировании продаж».
              </p>
            ) : null}

            {result.status === 'closed' ? (
              <p className="hint">
                Месяц закрыт: решение и причины не меняются. Перенос объёма оформляется
                корректировкой плана продаж, перенос закупки — пересмотром плана закупок.
              </p>
            ) : null}
          </div>

          {result.unmatched.length > 0 ? (
            <div className="unmatched-box" data-testid="unmatched-box">
              <h2>Не сопоставлено с номенклатурой: {result.unmatched.length}</h2>
              <p className="hint">
                Эти строки файла не попали в итоги. Сопоставьте их — выбор запомнится для следующих
                месяцев. Пока очередь не пуста, месяц нельзя закрыть.
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Название из файла</th>
                      <th scope="col">Поиск номенклатуры</th>
                      <th scope="col">Позиция</th>
                      <th scope="col" aria-label="Действие" />
                    </tr>
                  </thead>
                  <tbody>
                    {result.unmatched.map((row) => (
                      <MatchBox
                        key={row.id}
                        row={row}
                        products={products}
                        busy={busy || !mayMatch}
                        onMatch={(productId) => void match(row, productId)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {byManager.length > 1 ? (
            <table className="month-table" data-testid="manager-summary">
              <thead>
                <tr>
                  <th scope="col">Менеджер</th>
                  <th scope="col" className="num">
                    Строк
                  </th>
                  <th scope="col" className="num">
                    Вне плана
                  </th>
                  <th scope="col" className="num">
                    Не продано
                  </th>
                </tr>
              </thead>
              <tbody>
                {byManager.map(([id, row]) => (
                  <tr key={id || 'none'}>
                    <td>{row.name}</td>
                    <td className="num">{row.lines}</td>
                    <td className="num">{row.extra}</td>
                    <td className="num">{row.short}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}

          {result.rows.length === 0 ? (
            <div className="empty-state" data-testid="month-empty">
              <strong>За этот месяц продаж и плана нет</strong>
              <span>Загрузите выгрузку «Продажи за месяц» в разделе «Загрузка данных».</span>
            </div>
          ) : null}

          {result.rows.length > 0 ? (
            <div className="table-scroll">
              <table className="month-table" data-testid="month-table">
                <thead>
                  <tr>
                    <th scope="col">Менеджер</th>
                    <th scope="col">Клиент</th>
                    <th scope="col">Позиция</th>
                    <th scope="col">Ед.</th>
                    <th scope="col" className="num">
                      План
                    </th>
                    <th scope="col" className="num">
                      Факт
                    </th>
                    <th scope="col" className="num">
                      Отклонение
                    </th>
                    <th scope="col" className="num">
                      Исполнение
                    </th>
                    <th scope="col" className="num" title="Сумма факта в рублях">
                      Сумма, ₽
                    </th>
                    <th scope="col">Группа</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.length === 0 ? (
                    <tr>
                      <td colSpan={10} className="hint">
                        Под фильтр ничего не подошло.
                      </td>
                    </tr>
                  ) : (
                    visible.map((row) => {
                      const key = `${row.client_id}:${row.product_id}`
                      return (
                        <Fragment key={key}>
                          <tr>
                            <td>
                              {row.manager_name ?? '—'}
                              {row.manager_mismatch ? (
                                <span
                                  className="badge"
                                  title="Клиент закреплён за другим менеджером, чем его план"
                                >
                                  ≠
                                </span>
                              ) : null}
                            </td>
                            <td>{row.client_name}</td>
                            <td>{row.product_name}</td>
                            <td>{row.unit}</td>
                            <td className="num">{formatQuantity(row.plan_quantity)}</td>
                            <td className="num">{formatQuantity(row.fact_quantity)}</td>
                            <td className="num">{signed(row.deviation)}</td>
                            <td className="num">{share(row.fact_quantity, row.plan_quantity)}</td>
                            <td className="num">{formatMoney(row.fact_amount)}</td>
                            <td>
                              <span className={`badge badge-${row.group}`}>
                                {GROUP_TITLES[row.group]}
                              </span>
                              {row.reason ? (
                                <button
                                  type="button"
                                  className="reason-chip"
                                  title={`${
                                    row.reason.comment ?? row.reason.title
                                  }${row.reason.author_name ? ` — ${row.reason.author_name}` : ''}`}
                                  disabled={!mayReason || busy}
                                  onClick={() => openReason(row)}
                                >
                                  {row.reason.title}
                                </button>
                              ) : Number(row.deviation) !== 0 &&
                                mayReason &&
                                result.status === 'open' ? (
                                <button
                                  type="button"
                                  className="reason-add"
                                  onClick={() => openReason(row)}
                                >
                                  + причина
                                </button>
                              ) : null}
                            </td>
                          </tr>
                          {editing === key ? (
                            <tr className="reason-editor">
                              <td colSpan={10}>
                                <span className="reason-title">
                                  Причина отклонения: {row.client_name} · {row.product_name}
                                </span>
                                <select
                                  aria-label="Причина отклонения"
                                  value={reasonCode}
                                  onChange={(event) => setReasonCode(event.target.value)}
                                >
                                  <option value="">— выберите причину —</option>
                                  {(result.reason_options ?? []).map((option) => (
                                    <option key={option.code} value={option.code}>
                                      {option.title}
                                    </option>
                                  ))}
                                </select>
                                <input
                                  aria-label="Комментарий к причине"
                                  placeholder="Комментарий (для «Другое»)"
                                  title="Комментарий необязателен, кроме причины «Другое»"
                                  value={reasonComment}
                                  onChange={(event) => setReasonComment(event.target.value)}
                                />
                                <button
                                  type="button"
                                  className="primary"
                                  disabled={busy || reasonCode === ''}
                                  onClick={() => void saveReason(row)}
                                >
                                  Сохранить
                                </button>
                                {row.reason ? (
                                  <button
                                    type="button"
                                    className="mini"
                                    disabled={busy}
                                    onClick={() => void clearReason(row)}
                                  >
                                    Убрать
                                  </button>
                                ) : null}
                                <button
                                  type="button"
                                  className="mini"
                                  onClick={() => setEditing(null)}
                                >
                                  Отмена
                                </button>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}
