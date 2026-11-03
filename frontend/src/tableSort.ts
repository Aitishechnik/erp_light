/** Сортировка таблиц: одна колонка, по возрастанию или по убыванию. */

export type SortDirection = 'asc' | 'desc'

export type SortState = { column: string; direction: SortDirection } | null

/** Клик по заголовку: другая колонка — по возрастанию, та же — переворачивает. */
export function toggleSort(current: SortState, column: string): SortState {
  if (current?.column === column) {
    return { column, direction: current.direction === 'asc' ? 'desc' : 'asc' }
  }
  return { column, direction: 'asc' }
}

type CellValue = string | number | boolean | null | undefined

function empty(value: CellValue): boolean {
  return value === null || value === undefined || value === ''
}

function compare(left: CellValue, right: CellValue): number {
  if (typeof left === 'number' && typeof right === 'number') return left - right
  if (typeof left === 'boolean' && typeof right === 'boolean') {
    return Number(left) - Number(right)
  }
  return String(left).localeCompare(String(right), 'ru', { numeric: true, sensitivity: 'base' })
}

/**
 * Отсортированная копия строк.
 *
 * Пустые значения («—», нет менеджера) всегда уходят вниз: в таблице они не
 * должны разрывать осмысленный порядок. Сами строки не мутируются.
 */
export function sortRows<T>(
  rows: T[],
  sort: SortState,
  value: (row: T, column: string) => CellValue,
): T[] {
  if (!sort) return rows
  const sign = sort.direction === 'asc' ? 1 : -1
  return [...rows].sort((left, right) => {
    const a = value(left, sort.column)
    const b = value(right, sort.column)
    const aEmpty = empty(a)
    const bEmpty = empty(b)
    if (aEmpty || bEmpty) return aEmpty === bEmpty ? 0 : aEmpty ? 1 : -1
    return sign * compare(a, b)
  })
}
