/** Тема оформления и состояние меню живут в localStorage: выбор переживает перезагрузку. */

export type Theme = 'light' | 'dark'

const THEME_KEY = 'erp_lite_theme'
const SIDEBAR_KEY = 'erp_lite_sidebar'

export function readTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Приватный режим — просто не запоминаем выбор.
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
