/** Геометрия Ганта: окно, полосы и заголовок месяцев. Чистые функции — без React. */

export type GanttWindow = {
  startIso: string
  endIso: string
  days: number
}

export type GanttDay = {
  iso: string
  dayOfMonth: number
  weekday: number
  isMonday: boolean
  isWeekend: boolean
  isFirstOfMonth: boolean
}

export type GanttMonth = {
  key: string
  label: string
  days: number
}

const DAY_MS = 86_400_000

/** ISO-дата → миллисекунды UTC (полночь), чтобы не зависеть от часового пояса. */
export function parseIso(value: string): number {
  const [year = 1970, month = 1, day = 1] = value.split('-').map(Number)
  return Date.UTC(year, month - 1, day)
}

export function toIso(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

export function addDays(value: string, days: number): string {
  return toIso(parseIso(value) + days * DAY_MS)
}

export function diffDays(later: string, earlier: string): number {
  return Math.round((parseIso(later) - parseIso(earlier)) / DAY_MS)
}

/** Понедельник недели, в которую попадает дата. */
export function mondayOf(value: string): string {
  const weekday = new Date(parseIso(value)).getUTCDay() // 0 — воскресенье
  const shift = weekday === 0 ? 6 : weekday - 1
  return addDays(value, -shift)
}

function sundayOf(value: string): string {
  return addDays(mondayOf(value), 6)
}

/**
 * Окно Ганта: все сроки задач плюс сегодня, выровненное по неделям.
 * Пустой список задач всё равно показывает вокруг сегодняшнего дня.
 */
export function buildWindow(
  items: { start_date: string; due_date: string }[],
  todayIso: string,
  paddingDays = 7,
): GanttWindow {
  let min = todayIso
  let max = todayIso
  for (const item of items) {
    if (diffDays(item.start_date, min) < 0) min = item.start_date
    if (diffDays(item.due_date, max) > 0) max = item.due_date
  }
  const startIso = mondayOf(addDays(min, -paddingDays))
  const endIso = sundayOf(addDays(max, paddingDays))
  return { startIso, endIso, days: diffDays(endIso, startIso) + 1 }
}

/** Смещение даты от начала окна в днях (может быть отрицательным). */
export function dayOffset(value: string, window: GanttWindow): number {
  return diffDays(value, window.startIso)
}

/** Полоса задачи: левый край и ширина в пикселях. */
export function barGeometry(
  startIso: string,
  dueIso: string,
  window: GanttWindow,
  dayWidth: number,
): { left: number; width: number } {
  const left = dayOffset(startIso, window) * dayWidth
  const length = diffDays(dueIso, startIso) + 1
  return { left, width: Math.max(length, 1) * dayWidth }
}

/** Дни окна для сетки и подписей недель. */
export function windowDays(window: GanttWindow): GanttDay[] {
  const days: GanttDay[] = []
  for (let index = 0; index < window.days; index += 1) {
    const iso = addDays(window.startIso, index)
    const date = new Date(parseIso(iso))
    const weekday = date.getUTCDay()
    days.push({
      iso,
      dayOfMonth: date.getUTCDate(),
      weekday,
      isMonday: weekday === 1,
      isWeekend: weekday === 0 || weekday === 6,
      isFirstOfMonth: date.getUTCDate() === 1,
    })
  }
  return days
}

/** Заголовок месяцев: ширина каждого месяца в днях окна. */
export function monthSpans(window: GanttWindow): GanttMonth[] {
  const formatter = new Intl.DateTimeFormat('ru-RU', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  })
  const months: GanttMonth[] = []
  for (const day of windowDays(window)) {
    const key = day.iso.slice(0, 7)
    const last = months[months.length - 1]
    if (last && last.key === key) {
      last.days += 1
      continue
    }
    const label = formatter.format(new Date(parseIso(day.iso))).replace(/\s*г\.$/, '')
    months.push({ key, label: label.charAt(0).toUpperCase() + label.slice(1), days: 1 })
  }
  return months
}

/** Короткая подпись срока: «05.11». */
export function shortDate(value: string): string {
  return `${value.slice(8, 10)}.${value.slice(5, 7)}`
}
