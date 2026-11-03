import type { SortState } from './tableSort'

type Props = {
  /** Имя колонки для сортировки: страница решает, что по ней сравнивать. */
  column: string
  title: string
  sort: SortState
  onSort: (column: string) => void
  /** `num` — числовая колонка: заголовок и стрелка прижаты вправо. */
  className?: string
}

/**
 * Стрелка сортировки рисуется SVG, а не символом шрифта: символы в 9–10 px
 * сливаются в точку, а стрелка размером 12 px читается при любом шрифте.
 */
function SortIcon({ direction }: { direction: 'asc' | 'desc' | null }) {
  if (direction === null) {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
        <path d="M6 1.5 9 5H3z" fill="currentColor" />
        <path d="M6 10.5 3 7h6z" fill="currentColor" />
      </svg>
    )
  }
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      {direction === 'asc' ? (
        <path d="M6 1.5 10.5 9h-9z" fill="currentColor" />
      ) : (
        <path d="M6 10.5 1.5 3h9z" fill="currentColor" />
      )}
    </svg>
  )
}

/**
 * Заголовок сортируемой колонки.
 *
 * Значок рядом с названием: ▲ по возрастанию, ▼ по убыванию, две стрелки —
 * колонка сортируемая, но сейчас выбрана другая. Активная колонка подсвечена.
 */
export function SortableTh({ column, title, sort, onSort, className }: Props) {
  const active = sort?.column === column
  const direction = active ? sort?.direction : null
  return (
    <th
      scope="col"
      className={className}
      aria-sort={direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none'}
    >
      <button
        type="button"
        className={active ? 'sort-button active' : 'sort-button'}
        onClick={() => onSort(column)}
      >
        {title}
        <span className="sort-arrow" aria-hidden="true">
          <SortIcon direction={direction ?? null} />
        </span>
      </button>
    </th>
  )
}
