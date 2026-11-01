import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SessionUser, Task, TaskDetail } from './api'
import { mockApi } from './apiMock'
import { TasksPage } from './TasksPage'

const MANAGER: SessionUser = {
  id: 'sm-1',
  login: 'sales',
  full_name: 'Иван Петров',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

const TASK: Task = {
  id: 't1',
  title: 'Согласовать цены с клиентом',
  description: 'Свести матрицу цен и отправить клиенту',
  priority: 'red',
  priority_title: 'Высокий',
  status: 'in_progress',
  status_title: 'В работе',
  progress: 40,
  start_date: '2026-11-02',
  due_date: '2026-11-06',
  assignee_id: 'sm-1',
  assignee_name: 'Иван Петров',
  created_by_id: 'cd-1',
  created_by_name: 'Коммерческий директор',
  closed_at: null,
  created_at: '2026-11-01T09:00:00Z',
  updated_at: '2026-11-01T09:00:00Z',
  is_overdue: false,
  days_overdue: 0,
  steps: [
    {
      id: 's1',
      title: 'Собрать цены',
      start_date: '2026-11-02',
      due_date: '2026-11-03',
      is_done: true,
      position: 0,
    },
  ],
  reports_count: 1,
  files_count: 0,
  last_report: null,
}

const DETAIL: TaskDetail = {
  ...TASK,
  reports: [
    {
      id: 'r1',
      kind: 'interim',
      kind_title: 'Промежуточный',
      progress: 40,
      text: 'Собрал половину данных',
      author_id: 'sm-1',
      author_name: 'Иван Петров',
      created_at: '2026-11-01T10:00:00Z',
      files: [],
    },
  ],
  actions: {
    can_edit: true,
    can_change_status: true,
    can_report: true,
    can_delete: false,
    can_reopen: false,
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.location.hash = ''
})

describe('TasksPage', () => {
  it('рисует Гант: цвет приоритета, готовность и этапы', async () => {
    mockApi({ '/api/v1/tasks': { body: [TASK] } })
    render(<TasksPage user={MANAGER} focus={[]} />)

    expect(await screen.findByRole('heading', { level: 1, name: 'Задачи' })).toBeInTheDocument()
    expect(screen.getByTestId('gantt')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Согласовать цены с клиентом' })).toBeInTheDocument()
    expect(screen.getByText('40%')).toBeInTheDocument()

    // Этапы раскрываются по стрелке, полоса задачи остаётся на месте.
    await userEvent.click(screen.getByRole('button', { name: 'Показать этапы' }))
    expect(screen.getByText('Собрать цены')).toBeInTheDocument()
  })

  it('открывает карточку задачи и показывает отчёты', async () => {
    mockApi({
      '/api/v1/tasks/t1': { body: DETAIL },
      '/api/v1/tasks': { body: [TASK] },
    })
    render(<TasksPage user={MANAGER} focus={[]} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'Согласовать цены с клиентом' }),
    )

    expect(await screen.findByText('Готовность: 40%')).toBeInTheDocument()
    const report = screen.getByText('Собрал половину данных').closest('.task-report') as HTMLElement
    expect(within(report).getByText('Промежуточный')).toBeInTheDocument()
  })

  it('добавляет промежуточный отчёт и показывает его в истории', async () => {
    const user = userEvent.setup()
    const reports = [...DETAIL.reports]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString()
        const method = (init?.method ?? 'GET').toUpperCase()
        const json = (body: unknown) =>
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        if (url.includes('/api/v1/tasks/t1/reports') && method === 'POST') {
          const payload = JSON.parse(String(init?.body)) as { text: string; progress: number }
          const report = {
            id: 'r2',
            kind: 'interim' as const,
            kind_title: 'Промежуточный',
            progress: payload.progress,
            text: payload.text,
            author_id: MANAGER.id,
            author_name: MANAGER.full_name,
            created_at: '2026-11-01T11:00:00Z',
            files: [],
          }
          reports.push(report)
          return json({ ...DETAIL, reports, progress: payload.progress })
        }
        if (url.includes('/api/v1/tasks/t1') && method === 'GET') {
          return json({ ...DETAIL, reports })
        }
        if (url.includes('/api/v1/tasks') && method === 'GET') {
          return json([TASK])
        }
        return new Response(JSON.stringify({ detail: 'нет мока' }), { status: 404 })
      }),
    )

    render(<TasksPage user={MANAGER} focus={['t1']} />)

    const box = await screen.findByLabelText('Что сделано')
    await user.type(box, 'Договорились о скидке')
    await user.click(screen.getByRole('button', { name: 'Отправить отчёт' }))

    expect(await screen.findByText('Договорились о скидке')).toBeInTheDocument()
  })
})
