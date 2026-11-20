/** Тема оформления и состояние меню живут в localStorage: выбор переживает перезагрузку. */

export type Theme = 'light' | 'dark'

/** Варианты тёмной темы: одна палитра на выбор, «Claude» — цвета Claude Code. */
export type DarkVariant = 'indigo' | 'claude' | 'nord' | 'graphite'

export type DarkVariantInfo = {
  id: DarkVariant
  name: string
  note: string
  /** Три цвета для образца в меню: фон, поверхность, акцент. */
  swatches: [string, string, string]
}

export const DARK_VARIANTS: DarkVariantInfo[] = [
  {
    id: 'indigo',
    name: 'Индиго',
    note: 'Фиолетовый акцент, как сейчас',
    swatches: ['#101019', '#181826', '#8b87f5'],
  },
  {
    id: 'claude',
    name: 'Claude Code',
    note: 'Тёплый уголь и терракота',
    swatches: ['#1a1917', '#22211e', '#d97757'],
  },
  {
    id: 'nord',
    name: 'Nord',
    note: 'Холодный синий, полярная ночь',
    swatches: ['#242933', '#2e3440', '#88c0d0'],
  },
  {
    id: 'graphite',
    name: 'Графит',
    note: 'Нейтральный чёрный и небесный',
    swatches: ['#0b0d0f', '#171a1d', '#7cc4ea'],
  },
]

const THEME_KEY = 'erp_lite_theme'
const DARK_VARIANT_KEY = 'erp_lite_dark_variant'
const SIDEBAR_KEY = 'erp_lite_sidebar'

const KNOWN_VARIANTS = new Set<string>(DARK_VARIANTS.map((variant) => variant.id))

export function readTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function readDarkVariant(): DarkVariant {
  try {
    const saved = localStorage.getItem(DARK_VARIANT_KEY)
    return saved !== null && KNOWN_VARIANTS.has(saved) ? (saved as DarkVariant) : 'indigo'
  } catch {
    return 'indigo'
  }
}

/**
 * Ставит тему и вариант на <html>: CSS берёт палитру из [data-theme="dark"][data-dark="…"].
 * Вариант пишем всегда — при возврате в тёмную тему выбранная палитра ждёт на месте.
 */
export function applyTheme(theme: Theme, variant: DarkVariant = readDarkVariant()): void {
  document.documentElement.dataset.theme = theme
  document.documentElement.dataset.dark = variant
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Приватный режим — просто не запоминаем выбор.
  }
}

/** Выбор варианта сразу включает тёмную тему: иначе изменение не видно. */
export function applyDarkVariant(variant: DarkVariant): void {
  applyTheme('dark', variant)
  try {
    localStorage.setItem(DARK_VARIANT_KEY, variant)
  } catch {
    // То же: состояние не критично.
  }
}

export function readSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === 'collapsed'
  } catch {
    return false
  }
}

export function saveSidebarCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_KEY, collapsed ? 'collapsed' : 'expanded')
  } catch {
    // То же: состояние не критично.
  }
}
