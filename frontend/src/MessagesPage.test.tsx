import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AuditEvent, SessionUser } from './api'
import { mockApi } from './apiMock'
import { MessagesPage } from './MessagesPage'

const EXECUTIVE: SessionUser = {
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
    action: 'month.closed',
    action_title: 'Месяц закрыт',
    level: 'critical',
    entity_kind: 'month',
    entity_id: 'month-1',
    entity_label: '01.2027',
    summary: 'Месяц 01.2027 закрыт, версия снимка 2',
    actor_name: 'Коммерческий директор (демо)',
    actor_role_title: 'Коммерческий директор',
    year: 2027,
    month: 1,
    read: true,
    link: '#/month/2027/1',
    ...overrides,
  }
}

describe('Журнал: ссылки и очистка', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('событие с объектом — ссылка на место события', async () => {
    mockApi({
      '/api/v1/messages': { body: { rows: [event()], unread: 0, total: 1 } },
      '/api/v1/audit': { body: [event()] },
    })
    render(<MessagesPage user={EXECUTIVE} />)

    const link = await screen.findByRole('link', { name: /Месяц 01.2027 закрыт/ })
    expect(link).toHaveAttribute('href', '#/month/2027/1')
  })

  it('событие без объекта остаётся текстом', async () => {
    mockApi({
      '/api/v1/messages': {
        body: {
          rows: [event({ action: 'auth.login_failed', link: null, summary: 'Неудачный вход' })],
          unread: 0,
          total: 1,
        },
      },
      '/api/v1/audit': {
        body: [event({ action: 'auth.login_failed', link: null, summary: 'Неудачный вход' })],
      },
    })
    render(<MessagesPage user={EXECUTIVE} />)

    await screen.findByTestId('audit-table')
    expect(screen.queryByRole('link', { name: /Неудачный вход/ })).toBeNull()
    expect(screen.getByText('Неудачный вход')).toBeInTheDocument()
  })

  it('предлагает очистить прошлый год и удаляет по подтверждению', async () => {
    const user = userEvent.setup()
    const calls: string[] = []
    mockApi({
      'POST /api/v1/audit/cleanup': { body: { deleted: 12 } },
      '/api/v1/audit/cleanup': { body: { year: 2025, events: 12 } },
      '/api/v1/messages': { body: { rows: [], unread: 0, total: 0 } },
      '/api/v1/audit': { body: [event()] },
    })
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${String(input)}`)
      return originalFetch(input, init)
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<MessagesPage user={EXECUTIVE} />)

    const box = await screen.findByTestId('cleanup-box')
    expect(box).toHaveTextContent('За 2025 год в журнале 12 записей')
    await user.click(screen.getByRole('button', { name: 'Удалить журнал за 2025 год' }))

    await waitFor(() => {
      expect(calls.some((call) => call.startsWith('POST') && call.includes('/audit/cleanup'))).toBe(
        true,
      )
    })
    expect(await screen.findByText(/Журнал за 2025 год очищен/)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByTestId('cleanup-box')).toBeNull()
    })
  })
})
