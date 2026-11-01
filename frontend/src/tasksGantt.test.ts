import { describe, expect, it } from 'vitest'
import {
  addDays,
  barGeometry,
  buildWindow,
  dayOffset,
  diffDays,
  monthSpans,
  parseIso,
  toIso,
  windowDays,
} from './tasksGantt'

const ITEMS = [{ start_date: '2026-11-05', due_date: '2026-11-10' }]

describe('tasksGantt', () => {
  it('даты считаются без сдвига часового пояса', () => {
    expect(toIso(parseIso('2026-11-05'))).toBe('2026-11-05')
    expect(addDays('2026-11-05', -5)).toBe('2026-10-31')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(diffDays('2026-11-10', '2026-11-05')).toBe(5)
  })

  it('окно выровнено по неделям и включает сегодня', () => {
    const window = buildWindow(ITEMS, '2026-11-02', 7)
    expect(window.startIso).toBe('2026-10-26')
    expect(window.endIso).toBe('2026-11-22')
    expect(window.days).toBe(28)
    expect(windowDays(window)[0]?.isMonday).toBe(true)
  })

  it('пустой список задач всё равно показывает окно вокруг сегодня', () => {
    const window = buildWindow([], '2026-11-02', 7)
    expect(window.days).toBe(21)
    expect(dayOffset('2026-11-02', window)).toBe(7)
  })

  it('полоса задачи занимает свои дни', () => {
    const window = buildWindow(ITEMS, '2026-11-02', 7)
    const bar = barGeometry('2026-11-05', '2026-11-10', window, 26)
    expect(bar.left).toBe(10 * 26)
    expect(bar.width).toBe(6 * 26)
    expect(dayOffset('2026-11-05', window)).toBe(10)
  })

  it('месяцы разрезают шкалу по границе', () => {
    const window = buildWindow(ITEMS, '2026-11-02', 7)
    const spans = monthSpans(window)
    expect(spans.map((span) => span.days)).toEqual([6, 22])
    expect(spans[0]?.label).toBe('Октябрь 2026')
    expect(spans[1]?.label).toBe('Ноябрь 2026')
  })
})
