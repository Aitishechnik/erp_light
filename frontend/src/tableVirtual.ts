/** Виртуальный список строк таблицы: в DOM живёт только то, что видно. */

export type VirtualRange = { start: number; end: number }

/**
 * Какие строки рисовать при таком положении прокрутки.
 *
 * `overscan` — запас строк сверху и снизу, чтобы при быстрой прокрутке не
 * мелькала пустота. Если высота области ещё не измерена (первый кадр или
 * тесты в jsdom), показываем все строки — так таблица никогда не «пропадает».
 */
export function visibleRange(options: {
  count: number
  scrollTop: number
  viewportHeight: number
  rowHeight: number
  overscan?: number
}): VirtualRange {
  const { count, scrollTop, viewportHeight, rowHeight, overscan = 8 } = options
  if (count <= 0) return { start: 0, end: 0 }
  if (viewportHeight <= 0 || rowHeight <= 0) return { start: 0, end: count }

  const first = Math.floor(Math.max(0, scrollTop) / rowHeight)
  const visible = Math.ceil(viewportHeight / rowHeight)
  const start = Math.max(0, first - overscan)
  const end = Math.min(count, first + visible + overscan)
  return { start, end }
}
