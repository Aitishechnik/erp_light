import { useEffect, useId, useMemo, useRef, useState } from 'react'

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

/**
 * Поле с поиском по названию вместо длинного select.
 *
 * Ввод фильтрует варианты; выбор — клик или Enter. Показываем не больше
 * `maxResults` совпадений, чтобы список из тысяч позиций не тормозил.
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
  const optionsRef = useRef(options)
  optionsRef.current = options
  const typingRef = useRef(false)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)

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

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return
      setOpen(false)
      setQuery(selected?.label ?? '')
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open, selected?.label])

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
      {open ? (
        <div className="search-select-menu" role="listbox" id={listId} aria-label={label}>
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
        </div>
      ) : null}
    </div>
  )
}
