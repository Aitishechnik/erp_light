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
import { LoginPage } from './LoginPage'
import { MessagesPage } from './MessagesPage'
import { MonthResultsPage } from './MonthResultsPage'
import { NomenclaturePage } from './NomenclaturePage'
import { NotificationsBell } from './NotificationsBell'
import { PurchasePlanPage } from './PurchasePlanPage'
import { ReceiptsPage } from './ReceiptsPage'
import { SalesPlansPage } from './SalesPlansPage'
import { StockPage } from './StockPage'

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
}

const PURCHASE_ROLES: Role[] = ['purchase_director', 'import_manager', 'executive_director']

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
    sections: [{ id: 'tasks', title: 'Таск-трекер', ready: false }],
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

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">erp_lite</div>
        <nav aria-label="Разделы">
          {groups.map((group) => {
            const isOpen = openGroup === group.id
            const hasActive = currentGroup?.id === group.id
            return (
              <div className="nav-group" key={group.id}>
                <button
                  type="button"
                  className={hasActive ? 'nav-group-head active' : 'nav-group-head'}
                  aria-expanded={isOpen}
                  onClick={() => setOpenGroup(isOpen ? null : group.id)}
                >
                  <span className="chevron" aria-hidden="true">
                    {isOpen ? '▾' : '▸'}
                  </span>
                  {group.title}
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
              </div>
            )
          })}
        </nav>
        <div className="sidebar-footer">
          <NotificationsBell
            onOpenJournal={() => {
              setActive('messages')
              setOpenGroup('admin')
            }}
          />
          <div className="user-name">{user.full_name}</div>
          <div className="hint">{user.role_title}</div>
          <button type="button" className="nav-item" onClick={handleLogout}>
            Выйти
          </button>
        </div>
      </aside>

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
        {!current.ready ? (
          <section>
            <h1>{current.title}</h1>
            <p className="hint">Модуль ещё не реализован.</p>
          </section>
        ) : null}
      </main>
    </div>
  )
}
