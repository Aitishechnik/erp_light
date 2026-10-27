import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { AuditEvent } from './api'
import { mockApi } from './apiMock'

const EXECUTIVE = {
  id: 'ed-1',
  login: 'executive',
  full_name: 'Ольга Директорова',
  role: 'executive_director',
  role_title: 'Исполнительный директор',
}

function event(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: 'ev-1',
    created_at: '2026-10-27T10:00:00Z',
    action: 'sales_plan.approved',
    action_title: 'План продаж утверждён',
    level: 'critical',
    entity_kind: 'sales_plan',
    entity_id: 'plan-1',
    entity_label: 'Менеджер по продажам (демо), 2026',
    summary: 'План продаж на 2026 год утверждён: Менеджер по продажам (демо)',
    actor_name: 'Коммерческий директор (демо)',
    actor_role_title: 'Коммерческий директор',
    year: 2026,
    month: null,
    read: false,
    link: '#/sales-plan/2026/plan-1',
    ...overrides,
  }
}

const SESSION: Record<string, { body?: unknown; status?: number }> = {
  '/api/v1/auth/me': { body: EXECUTIVE },
  '/api/v1/stock': { body: [] },
  'POST /api/v1/messages/read-all': { body: { unread: 0 } },
  'POST /api/v1/messages/read': { body: { unread: 1 } },
  '/api/v1/messages/count': { body: { unread: 2 } },
  '/api/v1/messages': {
    body: { rows: [event(), event({ id: 'ev-2', read: true })], unread: 2, total: 2 },
  },
  '/api/v1/audit': { body: [event()] },
}

describe('Служебные сообщения', () => {
  beforeEach(() => {
    window.location.hash = ''
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('колокольчик показывает счётчик и панель сообщений', async () => {
    const user = userEvent.setup()
    mockApi(SESSION)
    render(<App />)

    const badge = await screen.findByTestId('bell-badge')
    expect(badge).toHaveTextContent('2')

    await user.click(screen.getByLabelText(/Служебные сообщения, непрочитанных: 2/))
    expect(await screen.findByTestId('bell-list')).toHaveTextContent(
      'План продаж на 2026 год утверждён',
    )
    expect(screen.getAllByText(/Коммерческий директор \(демо\)/).length).toBeGreaterThan(0)
  })

  it('отмечает всё прочитанным и убирает счётчик', async () => {
    const user = userEvent.setup()
    mockApi(SESSION)
    render(<App />)

    await screen.findByTestId('bell-badge')
    await user.click(screen.getByLabelText(/Служебные сообщения, непрочитанных: 2/))
    await user.click(await screen.findByRole('button', { name: 'Отметить всё прочитанным' }))

    await waitFor(() => {
      expect(screen.queryByTestId('bell-badge')).toBeNull()
    })
  })

  it('открывает журнал действий из панели', async () => {
    const user = userEvent.setup()
    mockApi(SESSION)
    render(<App />)

    await user.click(await screen.findByLabelText(/Служебные сообщения, непрочитанных: 2/))
    await user.click(await screen.findByRole('button', { name: 'Весь журнал' }))

    expect(await screen.findByTestId('audit-table')).toBeInTheDocument()
    expect(screen.getByTestId('audit-sales_plan.approved')).toHaveTextContent(
      'План продаж на 2026 год утверждён',
    )
    expect(screen.getByText('Непрочитанных: 2')).toBeInTheDocument()
  })
})
