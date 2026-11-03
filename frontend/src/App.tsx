import { useEffect, useState } from 'react'
import { AnnualSalesPlanPage } from './AnnualSalesPlanPage'
import {
  ANNUAL_SALES_PLAN_ROLES,
  logout as apiLogout,
  fetchMe,
  type Role,
  SALES_PLAN_ROLES,
  type SessionUser,
} from './api'
import { CounterpartiesPage } from './CounterpartiesPage'
import { CountriesPage } from './CountriesPage'
import { ImportsPage } from './ImportsPage'
import {
  IconAdmin,
  IconCatalogs,
  IconLogout,
  IconMoon,
  IconPanel,
  IconPlanning,
  IconPurchases,
  IconReports,
  IconSun,
  IconTasks,
} from './icons'
import { LoginPage } from './LoginPage'
import { MessagesPage } from './MessagesPage'
import { MonthResultsPage } from './MonthResultsPage'
import { NomenclaturePage } from './NomenclaturePage'
import { NotificationsBell } from './NotificationsBell'
import { PurchasePlanPage } from './PurchasePlanPage'
import { ReceiptsPage } from './ReceiptsPage'
import { SalesPlansPage } from './SalesPlansPage'
import { StockPage } from './StockPage'
import { TasksPage } from './TasksPage'
import {
  applyTheme,
  readSidebarCollapsed,
  readTheme,
  saveSidebarCollapsed,
  type Theme,
} from './theme'

type SectionId =
  | 'sales'
  | 'annual'
  | 'purchase'
  | 'pricing'
  | 'receipts'
  | 'suppliers'
  | 'nomenclature'
  | 'counterparties'
  | 'currencies'
  | 'countries'
  | 'stock'
  | 'month'
  | 'finance'
  | 'tasks'
  | 'imports'
  | 'messages'
  | 'users'
  | 'settings'

type Section = {
  id: SectionId
  title: string
  ready: boolean
  roles?: Role[]
}

type Group = {
  id: string
  title: string
  sections: Section[]
  /** Пункт меню без раскрытия: раздел один, как «Задачи». */
  direct?: boolean
}

const PURCHASE_ROLES: Role[] = ['purchase_director', 'import_manager', 'executive_director']

/** Задачи видит коммерческий отдел: продажи, ассистент и оба директора. */
const TASK_ROLES: Role[] = [
  'sales_manager',
  'sales_assistant',
  'commercial_director',
  'executive_director',
]

/** Итоги месяца: продажи против плана. Импорт и закупки смотрят, продажи и директора — все. */
const MONTH_ROLES: Role[] = [
  'sales_manager',
  'commercial_director',
  'executive_director',
  'purchase_director',
]

/** Основные категории меню; внутри — разделы, которые раскрываются по стрелке. */
const GROUPS: Group[] = [
  {
    id: 'planning',
    title: 'Планирование',
    sections: [
      { id: 'sales', title: 'Планирование продаж', ready: true, roles: SALES_PLAN_ROLES },
      { id: 'annual', title: 'Годовой план отдела', ready: true, roles: ANNUAL_SALES_PLAN_ROLES },
      { id: 'purchase', title: 'План закупок сырья', ready: true, roles: PURCHASE_ROLES },
      { id: 'pricing', title: 'Матрица цен', ready: false },
    ],
  },
  {
    id: 'purchases',
    title: 'Закупки',
    sections: [
      { id: 'receipts', title: 'Поступления', ready: true },
      { id: 'suppliers', title: 'Поставщики', ready: false },
    ],
  },
  {
    id: 'catalogs',
    title: 'Справочники',
    sections: [
      { id: 'nomenclature', title: 'Номенклатура', ready: true },
      { id: 'counterparties', title: 'Контрагенты', ready: true },
      { id: 'currencies', title: 'Валюты', ready: false },
      { id: 'countries', title: 'Страны', ready: true },
    ],
  },
  {
    id: 'reports',
    title: 'Отчёты',
    sections: [
      { id: 'stock', title: 'Остатки по партиям', ready: true },
      { id: 'month', title: 'Итоги месяца', ready: true, roles: MONTH_ROLES },
      { id: 'finance', title: 'PnL / Cashflow', ready: false },
    ],
  },
  {
    id: 'tasks',
    title: 'Задачи',
    direct: true,
    sections: [{ id: 'tasks', title: 'Таск-трекер', ready: true, roles: TASK_ROLES }],
  },
  {
    id: 'admin',
    title: 'Администрирование',
    sections: [
      { id: 'imports', title: 'Загрузка данных', ready: true },
      { id: 'messages', title: 'Служебные сообщения', ready: true },
      { id: 'users', title: 'Пользователи и роли', ready: false },
      { id: 'settings', title: 'Настройки приложения', ready: false },
    ],
  },
]

/** Иконки категорий: нужны и в развёрнутом меню, и в свёрнутом. */
const GROUP_ICONS: Record<string, typeof IconPlanning> = {
  planning: IconPlanning,
  purchases: IconPurchases,
  catalogs: IconCatalogs,
  reports: IconReports,
  tasks: IconTasks,
  admin: IconAdmin,
}

/** Адрес в строке браузера: #/month/2027/1, #/receipt/<id> и т.п. */
type Route = { section: SectionId; params: string[] }

const SECTION_TO_PATH: Record<string, string> = {
  stock: 'stock',
  sales: 'sales-plan',
  annual: 'annual-plan',
  purchase: 'purchase-plan',
  month: 'month',
  receipts: 'receipt',
  nomenclature: 'nomenclature',
  counterparties: 'counterparties',
  countries: 'countries',
  imports: 'imports',
  messages: 'messages',
  pricing: 'pricing',
  suppliers: 'suppliers',
  currencies: 'currencies',
  finance: 'finance',
  tasks: 'tasks',
  users: 'users',
  settings: 'settings',
}

const PATH_TO_SECTION: Record<string, SectionId> = Object.fromEntries(
  Object.entries(SECTION_TO_PATH).map(([section, path]) => [path, section as SectionId]),
)

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [name, ...params] = raw.split('/').filter(Boolean)
  const section = PATH_TO_SECTION[name ?? ''] ?? 'stock'
  return { section, params }
}

function sectionHash(section: SectionId): string {
  return `#/${SECTION_TO_PATH[section] ?? section}`
}

export function App() {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState<SectionId>(parseHash().section)
  const [route, setRoute] = useState<Route>(parseHash)
  const [openGroup, setOpenGroup] = useState<string | null>(
    GROUPS.find((group) => group.sections.some((section) => section.id === parseHash().section))
      ?.id ?? 'reports',
  )
  const [theme, setTheme] = useState<Theme>(readTheme)
  const [collapsed, setCollapsed] = useState<boolean>(readSidebarCollapsed)

  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    applyTheme(next)
  }

  const toggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    saveSidebarCollapsed(next)
  }

  const expandSidebar = () => {
    setCollapsed(false)
    saveSidebarCollapsed(false)
  }

  useEffect(() => {
    const onHash = () => {
      const next = parseHash()
      setRoute(next)
      setActive(next.section)
      const group = GROUPS.find((row) =>
        row.sections.some((section) => section.id === next.section),
      )
      if (group) setOpenGroup(group.id)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const handleLogout = async () => {
    try {
      await apiLogout()
    } catch {
      // Сессия могла уже истечь — всё равно показываем экран входа.
    }
    setUser(null)
  }

  if (loading) {
    return <p className="hint">Загрузка…</p>
  }

  if (!user) {
    return <LoginPage onLogin={setUser} />
  }

  const groups = GROUPS.map((group) => ({
    ...group,
    sections: group.sections.filter(
      (section) => !section.roles || section.roles.includes(user.role),
    ),
  })).filter((group) => group.sections.length > 0)

  const allSections = groups.flatMap((group) => group.sections)
  const current = allSections.find((section) => section.id === active) ?? allSections[0]

  if (!current) {
    return <p className="hint">Для вашей роли пока нет доступных разделов.</p>
  }

  const focus = route.section === current.id ? route.params : []

  const currentGroup = groups.find((group) =>
    group.sections.some((section) => section.id === current.id),
  )

  const initials =
    user.full_name
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part[0])
      .slice(0, 2)
      .join('') || '—'

  return (
    <div className={collapsed ? 'layout collapsed' : 'layout'}>
      <aside className={collapsed ? 'sidebar collapsed' : 'sidebar'}>
        <div className="brand-row">
          <div className="brand">
            erp_lite
            <span aria-hidden="true" />
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label={collapsed ? 'Развернуть меню' : 'Свернуть меню'}
            aria-expanded={!collapsed}
            onClick={toggleSidebar}
          >
            <IconPanel collapsed={collapsed} />
          </button>
        </div>
        <nav aria-label="Разделы">
          {groups.map((group) => {
            const isOpen = openGroup === group.id
            const hasActive = currentGroup?.id === group.id
            const Icon = GROUP_ICONS[group.id] ?? IconReports
            const openSection = () => {
              const section = group.sections[0]
              if (!section) return
              setActive(section.id)
              window.location.hash = sectionHash(section.id)
              setRoute({ section: section.id, params: [] })
            }
            return (
              <div className="nav-group" key={group.id}>
                {group.direct ? (
                  <button
                    type="button"
                    className={hasActive ? 'nav-item active nav-direct' : 'nav-item nav-direct'}
                    aria-current={hasActive ? 'page' : undefined}
                    aria-label={collapsed ? group.title : undefined}
                    title={collapsed ? group.title : undefined}
                    onClick={openSection}
                  >
                    <Icon />
                    <span className="nav-title">{group.title}</span>
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      className={hasActive ? 'nav-group-head active' : 'nav-group-head'}
                      aria-expanded={isOpen}
                      aria-label={collapsed ? group.title : undefined}
                      title={collapsed ? group.title : undefined}
                      onClick={() => {
                        if (collapsed) {
                          expandSidebar()
                          setOpenGroup(group.id)
                          return
                        }
                        setOpenGroup(isOpen ? null : group.id)
                      }}
                    >
                      <Icon />
                      <span className="nav-title">{group.title}</span>
                      <span className="chevron" aria-hidden="true">
                        {isOpen ? '▾' : '▸'}
                      </span>
                    </button>
                    {isOpen ? (
                      <ul className="nav-sublist">
                        {group.sections.map((section) => (
                          <li key={section.id}>
                            <button
                              type="button"
                              className={section.id === current.id ? 'nav-item active' : 'nav-item'}
                              aria-current={section.id === current.id ? 'page' : undefined}
                              onClick={() => {
                                setActive(section.id)
                                window.location.hash = sectionHash(section.id)
                                setRoute({ section: section.id, params: [] })
                              }}
                            >
                              {section.title}
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </>
                )}
              </div>
            )
          })}
        </nav>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <NotificationsBell
            onOpenJournal={() => {
              setActive('messages')
              setOpenGroup('admin')
            }}
          />
          <button
            type="button"
            className="icon-btn theme-toggle"
            aria-label={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            onClick={toggleTheme}
          >
            {theme === 'dark' ? <IconSun /> : <IconMoon />}
          </button>
          <div className="profile">
            <div className="user-avatar" aria-hidden="true">
              {initials}
            </div>
            <div className="profile-meta">
              <div className="user-name">{user.full_name}</div>
              <div className="user-role">{user.role_title}</div>
            </div>
          </div>
          <button
            type="button"
            className="icon-btn logout-icon"
            aria-label="Выйти"
            title="Выйти"
            onClick={handleLogout}
          >
            <IconLogout />
          </button>
        </header>

        <main className={current.id === 'receipts' ? 'content content-receipts' : 'content'}>
          {current.id === 'stock' && current.ready ? <StockPage /> : null}
          {current.id === 'sales' && current.ready ? (
            <SalesPlansPage user={user} focus={focus} />
          ) : null}
          {current.id === 'annual' && current.ready ? (
            <AnnualSalesPlanPage user={user} focus={focus} />
          ) : null}
          {current.id === 'purchase' && current.ready ? (
            <PurchasePlanPage user={user} focus={focus} />
          ) : null}
          {current.id === 'nomenclature' && current.ready ? (
            <NomenclaturePage focusId={focus[0]} />
          ) : null}
          {current.id === 'counterparties' && current.ready ? (
            <CounterpartiesPage user={user} focusId={focus[0]} />
          ) : null}
          {current.id === 'countries' && current.ready ? (
            <CountriesPage user={user} focusId={focus[0]} />
          ) : null}
          {current.id === 'month' && current.ready ? (
            <MonthResultsPage user={user} focus={focus} />
          ) : null}
          {current.id === 'receipts' && current.ready ? (
            <ReceiptsPage user={user} focus={focus} />
          ) : null}
          {current.id === 'imports' && current.ready ? <ImportsPage user={user} /> : null}
          {current.id === 'messages' && current.ready ? <MessagesPage user={user} /> : null}
          {current.id === 'tasks' && current.ready ? <TasksPage user={user} focus={focus} /> : null}
          {!current.ready ? (
            <section>
              <header className="page-head">
                <h1>{current.title}</h1>
              </header>
              <div className="empty-state">
                <strong>Модуль ещё не реализован.</strong>
                <span>Раздел появится в одном из следующих обновлений.</span>
              </div>
            </section>
          ) : null}
        </main>
      </div>
    </div>
  )
}
