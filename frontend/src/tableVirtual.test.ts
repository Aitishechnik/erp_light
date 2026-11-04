import { describe, expect, it } from 'vitest'
import { visibleRange } from './tableVirtual'

describe('visibleRange', () => {
  it('рисует окно вокруг прокрутки, а не всю таблицу', () => {
    const range = visibleRange({
      count: 1689,
      scrollTop: 39 * 500,
      viewportHeight: 390,
      rowHeight: 39,
    })
    // 10 видимых строк + запас по 8 сверху и снизу.
    expect(range.start).toBe(492)
    expect(range.end).toBe(518)
  })

  it('в начале списка не уходит в минус', () => {
    const range = visibleRange({
      count: 100,
      scrollTop: 0,
      viewportHeight: 390,
      rowHeight: 39,
    })
    expect(range.start).toBe(0)
    expect(range.end).toBe(18)
  })

  it('в конце списка не выходит за границу', () => {
    const range = visibleRange({
      count: 100,
      scrollTop: 39 * 95,
      viewportHeight: 390,
      rowHeight: 39,
    })
    expect(range.start).toBe(87)
    expect(range.end).toBe(100)
  })

  it('пока высота не измерена — отдаёт все строки', () => {
    // Так ведут себя тесты в jsdom: у области нет размеров.
    expect(visibleRange({ count: 250, scrollTop: 0, viewportHeight: 0, rowHeight: 39 })).toEqual({
      start: 0,
      end: 250,
    })
  })

  it('пустой список — пустое окно', () => {
    expect(visibleRange({ count: 0, scrollTop: 0, viewportHeight: 390, rowHeight: 39 })).toEqual({
      start: 0,
      end: 0,
    })
  })
})
