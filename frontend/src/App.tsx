import { useState } from 'react'
import { StockPage } from './StockPage'

const SECTIONS = [
  { id: 'stock', title: 'Партии и остатки', ready: true },
  { id: 'pricing', title: 'Матрица цен', ready: false },
  { id: 'planning', title: 'Планирование', ready: false },
  { id: 'finance', title: 'PnL / Cashflow', ready: false },
  { id: 'tasks', title: 'Задачи', ready: false },
] as const

type SectionId = (typeof SECTIONS)[number]['id']

export function App() {
  const [active, setActive] = useState<SectionId>('stock')
  const current = SECTIONS.find((section) => section.id === active)

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">erp_lite</div>
        <nav aria-label="Разделы">
          <ul>
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <button
                  type="button"
                  className={section.id === active ? 'nav-item active' : 'nav-item'}
                  aria-current={section.id === active ? 'page' : undefined}
                  onClick={() => setActive(section.id)}
                >
                  {section.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      <main className="content">
        {active === 'stock' ? (
          <StockPage />
        ) : (
          <section>
            <h1>{current?.title}</h1>
            <p className="hint">Модуль ещё не реализован.</p>
          </section>
        )}
      </main>
    </div>
  )
}
