import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export type SearchSelectOption = {
  value: string
  label: string
  /** Дополнительный текст для поиска: код 1С, ИНН и т. п. */
  keywords?: string
}

type SearchSelectProps = {
  label: string
  value: string
  options: SearchSelectOption[]
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  emptyText?: string
  maxResults?: number
  /** Широкое поле для длинных названий номенклатуры. */
  wide?: boolean
}

/** Высота списка и отступы от поля: те же 280 px, что были в CSS. */
const MENU_MAX_HEIGHT = 280
const MENU_GAP = 4
const MENU_MARGIN = 8
/** Ниже этого места список лучше раскрыть вверх, а не прижимать к низу окна. */
const MENU_MIN_SPACE_BELOW = 180

type MenuPlacement = {
  left: number
  top?: number
  bottom?: number
  width: number | 'max-content'
  minWidth: number
  maxWidth: number
  maxHeight: number
}

/**
 * Поле с поиском по названию вместо длинного select.
 *
 * Ввод фильтрует варианты; выбор — клик или Enter. Показываем не больше
 * `maxResults` совпадений, чтобы список из тысяч позиций не тормозил.
 *
 * Список рисуется порталом в `document.body` с `position: fixed`:
 * внутри страницы есть прокручиваемые блоки (`.content`, карточки, таблицы),
 * и обычный абсолютный список обрезался их границами. Здесь же он всегда
 * целиком в окне: раскрывается вниз, а если места мало — вверх.
 */
export function SearchSelect({
  label,
  value,
  options,
  onChange,
  placeholder = 'Начните вводить название',
  disabled = false,
  emptyText = 'Ничего не найдено',
  maxResults = 50,
  wide = false,
}: SearchSelectProps) {
  const listId = useId()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options
  const typingRef = useRef(false)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const [placement, setPlacement] = useState<MenuPlacement | null>(null)
  const [menuHeight, setMenuHeight] = useState<number | null>(null)

  const selected = options.find((option) => option.value === value) ?? null

  // Внешнее значение (выбор из списка, сброс после «Добавить») подставляем
  // в поле. Пока человек печатает, его текст не перебиваем.
  useEffect(() => {
    if (typingRef.current) {
      typingRef.current = false
      return
    }
    const chosen = optionsRef.current.find((option) => option.value === value)
    setQuery(chosen?.label ?? '')
  }, [value])

  const { matched, visible } = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('ru')
    const found = needle
      ? options.filter((option) => {
          const haystack = `${option.label} ${option.keywords ?? ''}`.toLocaleLowerCase('ru')
          return haystack.includes(needle)
        })
      : options
    return { matched: found, visible: found.slice(0, maxResults) }
  }, [options, query, maxResults])

  /** Ставим список рядом с полем и держим внутри окна. */
  const placeMenu = useCallback(() => {
    const input = inputRef.current
    if (!input) return
    const rect = input.getBoundingClientRect()
    const spaceBelow = window.innerHeight - rect.bottom - MENU_GAP - MENU_MARGIN
    const spaceAbove = rect.top - MENU_GAP - MENU_MARGIN
    const openAbove = spaceBelow < MENU_MIN_SPACE_BELOW && spaceAbove > spaceBelow
    const available = openAbove ? spaceAbove : spaceBelow
    setPlacement({
      left: rect.left,
      ...(openAbove
        ? { bottom: window.innerHeight - rect.top + MENU_GAP }
        : { top: rect.bottom + MENU_GAP }),
      width: wide ? 'max-content' : rect.width,
      minWidth: rect.width,
      maxWidth: Math.max(rect.width, Math.min(700, window.innerWidth - rect.left - MENU_MARGIN)),
      maxHeight: Math.max(Math.min(MENU_MAX_HEIGHT, available), 120),
    })
  }, [wide])

  useLayoutEffect(() => {
    if (!open) {
      setPlacement(null)
      setMenuHeight(null)
      return
    }
    placeMenu()
  }, [open, placeMenu])

  // Не режем вариант посередине строки: высота списка — сумма целых строк.
  // Иначе последняя строка выглядит «обрубленной», даже если список листается.
  useLayoutEffect(() => {
    if (!open || !placement) return
    const menu = menuRef.current
    if (!menu) return
    const rows = Array.from(menu.children) as HTMLElement[]
    const optionsInMenu = rows.filter((row) => row.classList.contains('search-select-option'))
    // Ждём, пока DOM догонит отфильтрованный список: мерить чужие строки нельзя.
    if (optionsInMenu.length !== visible.length) return
    if (rows.length === 0) return
    const style = getComputedStyle(menu)
    const frame =
      menu.offsetHeight -
      menu.clientHeight +
      Number.parseFloat(style.paddingTop || '0') +
      Number.parseFloat(style.paddingBottom || '0')
    let fitted = frame
    for (const row of rows) {
      const next = fitted + row.offsetHeight
      if (next > placement.maxHeight) break
      fitted = next
    }
    const height = fitted > frame ? Math.ceil(fitted) : placement.maxHeight
    if (menuHeight !== height) setMenuHeight(height)
  }, [open, placement, visible, menuHeight])

  // Страница и её блоки прокручиваются — список должен ехать вместе с полем.
  useEffect(() => {
    if (!open) return
    const onScrollOrResize = () => placeMenu()
    window.addEventListener('scroll', onScrollOrResize, true)
    window.addEventListener('resize', onScrollOrResize)
    return () => {
      window.removeEventListener('scroll', onScrollOrResize, true)
      window.removeEventListener('resize', onScrollOrResize)
    }
  }, [open, placeMenu])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return
      setOpen(false)
      setQuery(selected?.label ?? '')
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open, selected?.label])

  // Стрелки ходят по списку — подсвеченный вариант должен быть виден.
  useEffect(() => {
    if (!open) return
    const option = visible[activeIndex]
    if (!option) return
    document
      .getElementById(`${listId}-option-${option.value}`)
      ?.scrollIntoView?.({ block: 'nearest' })
  }, [activeIndex, open, visible, listId])

  const choose = (option: SearchSelectOption) => {
    onChange(option.value)
    setQuery(option.label)
    setOpen(false)
    setActiveIndex(0)
    inputRef.current?.focus()
  }

  const resetQuery = () => {
    setQuery(selected?.label ?? '')
  }

  return (
    <div
      className={`search-select${wide ? ' wide' : ''}${disabled ? ' disabled' : ''}`}
      ref={rootRef}
    >
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-label={label}
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={
          open && visible[activeIndex]
            ? `${listId}-option-${visible[activeIndex]?.value}`
            : undefined
        }
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder}
        value={query}
        disabled={disabled}
        onFocus={() => {
          setOpen(true)
          setActiveIndex(0)
        }}
        onBlur={() => {
          setOpen(false)
          resetQuery()
        }}
        onChange={(event) => {
          const next = event.target.value
          setQuery(next)
          setOpen(true)
          setActiveIndex(0)
          if (selected && next !== selected.label) {
            typingRef.current = true
            onChange('')
          }
        }}
        onKeyDown={(event) => {
          if (disabled) return
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            if (!open) {
              setOpen(true)
              setActiveIndex(0)
            } else {
              setActiveIndex((index) => Math.min(index + 1, Math.max(visible.length - 1, 0)))
            }
          } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            setActiveIndex((index) => Math.max(index - 1, 0))
          } else if (event.key === 'Enter') {
            if (!open) return
            const option = visible[activeIndex]
            if (option) {
              event.preventDefault()
              choose(option)
            }
          } else if (event.key === 'Escape') {
            setOpen(false)
            resetQuery()
          }
        }}
      />
      {open && placement
        ? createPortal(
            <div
              ref={menuRef}
              className={`search-select-menu${wide ? ' wide' : ''}`}
              role="listbox"
              id={listId}
              aria-label={label}
              style={{
                left: placement.left,
                top: placement.top,
                bottom: placement.bottom,
                width: placement.width,
                minWidth: placement.minWidth,
                maxWidth: placement.maxWidth,
                maxHeight: placement.maxHeight,
                height: menuHeight ?? undefined,
              }}
            >
              {visible.length === 0 ? (
                <div className="search-select-empty">{emptyText}</div>
              ) : (
                visible.map((option) => (
                  <div
                    key={option.value}
                    id={`${listId}-option-${option.value}`}
                    role="option"
                    tabIndex={-1}
                    aria-selected={option.value === value}
                    className={
                      visible[activeIndex]?.value === option.value
                        ? 'search-select-option active'
                        : 'search-select-option'
                    }
                    onMouseDown={(event) => event.preventDefault()}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        choose(option)
                      }
                    }}
                    onMouseEnter={() => {
                      const index = visible.findIndex((row) => row.value === option.value)
                      if (index >= 0) setActiveIndex(index)
                    }}
                    onClick={() => choose(option)}
                  >
                    {option.label}
                  </div>
                ))
              )}
              {matched.length > visible.length ? (
                <div className="search-select-more">
                  Показано {visible.length} из {matched.length} — уточните запрос
                </div>
              ) : null}
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
