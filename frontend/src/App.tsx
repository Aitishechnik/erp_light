import { useEffect, useState } from 'react'
import { logout as apiLogout, fetchMe, type Role, SALES_PLAN_ROLES, type SessionUser } from './api'
import { CounterpartiesPage } from './CounterpartiesPage'
import { ImportsPage } from './ImportsPage'
import { LoginPage } from './LoginPage'
import { NomenclaturePage } from './NomenclaturePage'
import { SalesPlansPage } from './SalesPlansPage'
import { StockPage } from './StockPage'

type SectionId =
  | 'sales'
  | 'purchase'
  | 'pricing'
  | 'nomenclature'
  | 'counterparties'
  | 'currencies'
  | 'countries'
  | 'stock'
  | 'finance'
  | 'tasks'
  | 'imports'
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

/** Основные категории меню; внутри — разделы, которые раскрываются по стрелке. */
const GROUPS: Group[] = [
  {
    id: 'planning',
    title: 'Планирование',
    sections: [
      { id: 'sales', title: 'Планирование продаж', ready: true, roles: SALES_PLAN_ROLES },
      { id: 'purchase', title: 'Планирование закупок', ready: false, roles: PURCHASE_ROLES },
      { id: 'pricing', title: 'Матрица цен', ready: false },
    ],
  },
  {
    id: 'catalogs',
    title: 'Справочники',
    sections: [
      { id: 'nomenclature', title: 'Номенклатура', ready: true },
      { id: 'counterparties', title: 'Контрагенты', ready: true },
      { id: 'currencies', title: 'Валюты', ready: false },
      { id: 'countries', title: 'Страны', ready: false },
    ],
  },
  {
    id: 'reports',
    title: 'Отчёты',
    sections: [
      { id: 'stock', title: 'Остатки по партиям', ready: true },
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
      { id: 'users', title: 'Пользователи и роли', ready: false },
      { id: 'settings', title: 'Настройки приложения', ready: false },
    ],
  },
]

export function App() {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState<SectionId>('stock')
  const [openGroup, setOpenGroup] = useState<string | null>('reports')

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
                          onClick={() => setActive(section.id)}
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
          <div className="user-name">{user.full_name}</div>
          <div className="hint">{user.role_title}</div>
          <button type="button" className="nav-item" onClick={handleLogout}>
            Выйти
          </button>
        </div>
      </aside>

      <main className="content">
        {current.id === 'stock' && current.ready ? <StockPage /> : null}
        {current.id === 'sales' && current.ready ? <SalesPlansPage user={user} /> : null}
        {current.id === 'nomenclature' && current.ready ? <NomenclaturePage /> : null}
        {current.id === 'counterparties' && current.ready ? <CounterpartiesPage /> : null}
        {current.id === 'imports' && current.ready ? <ImportsPage /> : null}
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
