import { useEffect, useState } from 'react'
import { logout as apiLogout, fetchMe, type Role, SALES_PLAN_ROLES, type SessionUser } from './api'
import { ClientsPage } from './ClientsPage'
import { LoginPage } from './LoginPage'
import { NomenclaturePage } from './NomenclaturePage'
import { SalesPlansPage } from './SalesPlansPage'
import { StockPage } from './StockPage'

type SectionId =
  | 'stock'
  | 'sales'
  | 'purchase'
  | 'nomenclature'
  | 'clients'
  | 'pricing'
  | 'finance'
  | 'tasks'

type Section = {
  id: SectionId
  title: string
  ready: boolean
  roles?: Role[]
}

const SECTIONS: Section[] = [
  { id: 'stock', title: 'Партии и остатки', ready: true },
  { id: 'sales', title: 'Планирование продаж', ready: true, roles: SALES_PLAN_ROLES },
  {
    id: 'purchase',
    title: 'Планирование закупок',
    ready: false,
    roles: ['purchase_director', 'import_manager', 'executive_director'],
  },
  { id: 'nomenclature', title: 'Номенклатура', ready: true },
  { id: 'clients', title: 'Клиенты', ready: true },
  { id: 'pricing', title: 'Матрица цен', ready: false },
  { id: 'finance', title: 'PnL / Cashflow', ready: false },
  { id: 'tasks', title: 'Задачи', ready: false },
]

export function App() {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState<SectionId>('stock')

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

  const sections = SECTIONS.filter((section) => !section.roles || section.roles.includes(user.role))
  const current = sections.find((section) => section.id === active) ?? sections[0]

  if (!current) {
    return <p className="hint">Для вашей роли пока нет доступных разделов.</p>
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">erp_lite</div>
        <nav aria-label="Разделы">
          <ul>
            {sections.map((section) => (
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
        {current.id === 'clients' && current.ready ? <ClientsPage /> : null}
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
