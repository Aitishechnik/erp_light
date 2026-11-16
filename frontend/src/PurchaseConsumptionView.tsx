import { Fragment, useMemo, useState } from 'react'
import { formatQuantity, MONTH_TITLES, type PurchasePlan } from './api'
import {
  buildConsumption,
  type ConsumptionDraft,
  type ConsumptionGroup,
  type ConsumptionLine,
  summarizeLines,
} from './purchaseConsumption'

const MONTH_SHORT = MONTH_TITLES.map((title) => title.slice(0, 3).toLowerCase())
const normFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4 })

function matches(haystack: string, query: string): boolean {
  return haystack.toLowerCase().includes(query)
}

function LineRows({
  line,
  unit,
  alternativeOnly,
  open,
  onToggle,
}: {
  line: ConsumptionLine
  unit: string
  alternativeOnly: boolean
  open: boolean
  onToggle: () => void
}) {
  const norm = line.norm
  const need = line.need
  const showAltBadge = line.alternative && !alternativeOnly
  return (
    <Fragment>
      <tr>
        <td>
          {line.code} · {line.name}
          {showAltBadge ? <span className="badge badge-alt">альтернатива</span> : null}
          {line.orphan ? <span className="badge need-removed">вне плана продаж</span> : null}
        </td>
        <td>{line.country || '—'}</td>
        <td className="num">
          {norm === null ? (
            <span className="need-missing">не задана</span>
          ) : (
            normFormat.format(norm)
          )}
        </td>
        <td className="num">
          {need === null ? (
            <span className="need-missing">—</span>
          ) : (
            <>
              <strong>{formatQuantity(need.toFixed(3))}</strong>{' '}
              <span className="need-unit">{unit}</span>
            </>
          )}
        </td>
        <td>
          {norm === null ? (
            <span className="need-missing">—</span>
          ) : (
            <button
              type="button"
              className="mini month-toggle"
              aria-expanded={open}
              aria-controls={`months-${line.key}`}
              aria-label={`Расход по месяцам: ${line.name}`}
              data-testid={`months-toggle-${line.key}`}
              onClick={onToggle}
            >
              {open ? '▾ свернуть' : '▸ по месяцам'}
            </button>
          )}
        </td>
      </tr>
      {norm !== null && open ? (
        <tr className="months-row" id={`months-${line.key}`}>
          <td colSpan={5}>
            <div className="months-panel">
              <div className="months-head">
                <span>
                  <b>{line.code}</b> · расход по месяцам, {unit}
                </span>
                <span>
                  за год: <b>{formatQuantity((need ?? 0).toFixed(3))}</b> {unit}
                </span>
              </div>
              <ol className="months-strip">
                {line.monthly.map((month) => (
                  <li
                    key={month.month}
                    className={month.quantity > 0 ? undefined : 'zero'}
                    title={`план продаж: ${formatQuantity(month.planned.toFixed(3))} ${
                      line.unit
                    } × норма ${normFormat.format(norm)}`}
                  >
                    <span className="m">{MONTH_SHORT[month.month - 1] ?? ''}</span>
                    <b>{month.quantity > 0 ? formatQuantity(month.quantity.toFixed(3)) : '—'}</b>
                  </li>
                ))}
              </ol>
            </div>
          </td>
        </tr>
      ) : null}
    </Fragment>
  )
}

function MaterialCard({
  group,
  open,
  onToggle,
  openMonths,
  onToggleMonth,
}: {
  group: ConsumptionGroup
  open: boolean
  onToggle: (isOpen: boolean) => void
  openMonths: string[]
  onToggleMonth: (key: string) => void
}) {
  return (
    <details
      className="material-card"
      open={open}
      onToggle={(event) => onToggle(event.currentTarget.open)}
      data-testid={`consumption-card-${group.code || group.productId}`}
    >
      <summary>
        <span className="mc-name">{group.name}</span>
        <span className="mc-code">
          {group.code} · {group.unit}
        </span>
        {group.alternativeOnly ? <span className="badge badge-alt">альтернатива</span> : null}
        {group.missingNorm > 0 ? (
          <span className="badge need-changed">без нормы: {group.missingNorm}</span>
        ) : null}
        <span className="mc-count">
          позиций: {group.products} · строк: {group.lines.length}
        </span>
        <span className="mc-caret" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
      </summary>
      <table className="card-table">
        <thead>
          <tr>
            <th scope="col">Готовая продукция</th>
            <th scope="col">Страна</th>
            <th scope="col" className="num">
              Норма расхода
            </th>
            <th scope="col" className="num">
              Потребность за год
            </th>
            <th scope="col">По месяцам</th>
          </tr>
        </thead>
        <tbody>
          {group.lines.map((line) => (
            <LineRows
              key={line.key}
              line={line}
              unit={group.unit}
              alternativeOnly={group.alternativeOnly}
              open={openMonths.includes(line.key)}
              onToggle={() => onToggleMonth(line.key)}
            />
          ))}
        </tbody>
      </table>
    </details>
  )
}

export function PurchaseConsumptionView({
  plan,
  drafts,
}: {
  plan: PurchasePlan
  drafts: ConsumptionDraft[]
}) {
  const [search, setSearch] = useState('')
  const [closedCards, setClosedCards] = useState<string[]>([])
  const [openMonths, setOpenMonths] = useState<string[]>([])
  const groups = useMemo(() => buildConsumption(plan, drafts), [plan, drafts])
  const query = search.trim().toLowerCase()

  const filtered = useMemo(() => {
    if (query === '') return groups
    return groups.flatMap((group) => {
      const materialHit = matches(`${group.code} ${group.name}`, query)
      const lines = materialHit
        ? group.lines
        : group.lines.filter((line) => matches(`${line.code} ${line.name} ${line.country}`, query))
      return lines.length === 0 ? [] : [{ ...group, lines, ...summarizeLines(lines) }]
    })
  }, [groups, query])

  const shownLines = filtered.reduce((sum, group) => sum + group.lines.length, 0)

  const toggleCard = (productId: string, isOpen: boolean) =>
    setClosedCards((current) =>
      isOpen ? current.filter((id) => id !== productId) : [...current, productId],
    )

  const toggleMonth = (key: string) =>
    setOpenMonths((current) =>
      current.includes(key) ? current.filter((id) => id !== key) : [...current, key],
    )

  return (
    <div className="consumption-view" data-testid="consumption-view">
      <div className="view-head">
        <h2>Расход сырья на {plan.year} год</h2>
      </div>

      {groups.length === 0 ? (
        <div className="empty-state" data-testid="consumption-empty">
          <strong>В плане пока нет строк сырья</strong>
          <span>Добавьте сырьё в плане закупок — расход появится здесь.</span>
        </div>
      ) : (
        <>
          <div className="toolbar filter-bar">
            <input
              type="search"
              className="consumption-search"
              placeholder="Поиск по сырью или продукции"
              aria-label="Поиск по сырью или продукции"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <span className="filter-count" data-testid="consumption-count">
              Сырья: <strong>{filtered.length}</strong>
              {query !== '' ? <span className="filter-total"> из {groups.length}</span> : null}
              {' · '}строк: <strong>{shownLines}</strong>
            </span>
            <button
              type="button"
              className="mini filter-reset"
              disabled={query === ''}
              onClick={() => setSearch('')}
            >
              Сбросить
            </button>
          </div>

          {filtered.length === 0 ? (
            <div className="empty-state" data-testid="consumption-no-match">
              <strong>Ничего не найдено</strong>
              <span>Проверьте запрос или сбросьте фильтр.</span>
            </div>
          ) : null}

          {filtered.map((group) => (
            <MaterialCard
              key={group.productId}
              group={group}
              open={!closedCards.includes(group.productId)}
              onToggle={(isOpen) => toggleCard(group.productId, isOpen)}
              openMonths={openMonths}
              onToggleMonth={toggleMonth}
            />
          ))}
        </>
      )}
    </div>
  )
}
