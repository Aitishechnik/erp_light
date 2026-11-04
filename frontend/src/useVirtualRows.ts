import { useCallback, useEffect, useRef, useState } from 'react'
import { visibleRange } from './tableVirtual'

/** Высота строки в таблице; совпадает с CSS `.virtual-table tbody tr`. */
export const ROW_HEIGHT = 39

/**
 * Рендер только видимых строк таблицы.
 *
 * Область прокрутки сама подстраивается под экран: высота = остаток окна под
 * таблицей, поэтому страница и таблица не прокручиваются одновременно.
 * `resetKey` — строка-ключ фильтров и сортировки: при её смене список
 * возвращается наверх.
 */
export function useVirtualRows(options: { count: number; resetKey: string }) {
  const { count, resetKey } = options
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const appliedKey = useRef(resetKey)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(0)

  /** Подогнать высоту области под окно: всё, что ниже шапки страницы. */
  const fit = useCallback(() => {
    const element = viewportRef.current
    if (!element) return
    const top = element.getBoundingClientRect().top
    const header = element.querySelector('thead')?.getBoundingClientRect().height ?? 0
    const free = Math.max(240, window.innerHeight - top - 24) - header
    // Высота кратна строке: снизу не остаётся половинки строки — список
    // не выглядит обрезанным.
    const height = header + Math.max(1, Math.floor((free - 2) / ROW_HEIGHT)) * ROW_HEIGHT
    if (element.style.height !== `${height}px`) element.style.height = `${height}px`
    setViewportHeight(element.clientHeight)
    setScrollTop(element.scrollTop)
  }, [])

  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    fit()
    const onScroll = () => setScrollTop(element.scrollTop)
    element.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', fit)
    return () => {
      element.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', fit)
    }
  }, [fit])

  // Сменили фильтр или сортировку — показываем список с начала.
  useEffect(() => {
    if (appliedKey.current === resetKey) return
    appliedKey.current = resetKey
    const element = viewportRef.current
    if (element) element.scrollTop = 0
    setScrollTop(0)
    fit()
  }, [resetKey, fit])

  const range = visibleRange({ count, scrollTop, viewportHeight, rowHeight: ROW_HEIGHT })

  /** Прокрутить к строке: так открывается объект из сообщения. */
  const scrollToIndex = useCallback((index: number) => {
    const element = viewportRef.current
    if (!element || index < 0) return
    element.scrollTop = Math.max(0, index * ROW_HEIGHT - element.clientHeight / 2 + ROW_HEIGHT / 2)
    setScrollTop(element.scrollTop)
  }, [])

  return { viewportRef, range, scrollToIndex }
}
