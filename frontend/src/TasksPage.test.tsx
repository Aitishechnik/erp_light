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
      has_report: true,
      needs_report: false,
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
      step_id: null,
      step_title: null,
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
            step_id: null,
            step_title: null,
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

const COMMERCIAL: SessionUser = {
  id: 'cd-1',
  login: 'commercial',
  full_name: 'Коммерческий директор',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
}

describe('TasksPage — права отдела', () => {
  it('коммерческий директор видит кнопку новой задачи, менеджер — нет', async () => {
    mockApi({
      '/api/v1/tasks/assignees': {
        body: [{ id: 'sm-1', full_name: 'Иван Петров', role_title: 'Менеджер по продажам' }],
      },
      '/api/v1/tasks': { body: [] },
    })
    const director = render(<TasksPage user={COMMERCIAL} focus={[]} />)
    expect(await screen.findByRole('button', { name: '＋ Новая задача' })).toBeInTheDocument()
    director.unmount()

    render(<TasksPage user={MANAGER} focus={[]} />)
    expect(await screen.findByText('Вам пока не поставили ни одной задачи.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '＋ Новая задача' })).not.toBeInTheDocument()
  })
})

describe('TasksPage — этапы', () => {
  it('этап закрывается промежуточным отчётом', async () => {
    const user = userEvent.setup()
    let current: TaskDetail = {
      ...DETAIL,
      reports: [],
      steps: [
        {
          id: 's2',
          title: 'Согласовать скидки',
          start_date: '2026-11-04',
          due_date: '2026-11-06',
          is_done: false,
          position: 0,
          has_report: false,
          needs_report: false,
        },
      ],
    }
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
          const payload = JSON.parse(String(init?.body)) as { text: string; step_id: string }
          current = {
            ...current,
            progress: 100,
            steps: current.steps.map((step) =>
              step.id === payload.step_id
                ? { ...step, is_done: true, has_report: true, needs_report: false }
                : step,
            ),
            reports: [
              {
                id: 'r-step',
                kind: 'interim',
                kind_title: 'Промежуточный',
                step_id: payload.step_id,
                step_title: 'Согласовать скидки',
                progress: 100,
                text: payload.text,
                author_id: MANAGER.id,
                author_name: MANAGER.full_name,
                created_at: '2026-11-05T10:00:00Z',
                files: [],
              },
            ],
          }
          return json(current)
        }
        if (url.includes('/api/v1/tasks/t1') && method === 'GET') return json(current)
        if (url.includes('/api/v1/tasks') && method === 'GET') return json([TASK])
        return new Response(JSON.stringify({ detail: 'нет мока' }), { status: 404 })
      }),
    )

    render(<TasksPage user={MANAGER} focus={['t1']} />)

    await user.click(await screen.findByRole('button', { name: 'Отчёт по этапу' }))
    await user.type(screen.getByLabelText('Что сделано'), 'Скидки согласованы со всеми')
    await user.click(screen.getByRole('button', { name: 'Закрыть этап отчётом' }))

    expect(await screen.findByText('Отчёт получен')).toBeInTheDocument()
    expect(screen.getByText('Скидки согласованы со всеми')).toBeInTheDocument()
  })
})

describe('TasksPage — перенос задачи', () => {
  it('меняет сроки и показывает новые даты', async () => {
    const user = userEvent.setup()
    let current: TaskDetail = {
      ...DETAIL,
      start_date: '2026-11-02',
      due_date: '2026-11-06',
      steps: [],
      reports: [],
    }
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
        if (url.includes('/reschedule') && method === 'POST') {
          const payload = JSON.parse(String(init?.body)) as {
            start_date: string
            due_date: string
          }
          current = { ...current, start_date: payload.start_date, due_date: payload.due_date }
          return json(current)
        }
        if (url.includes('/api/v1/tasks/t1') && method === 'GET') return json(current)
        if (url.includes('/api/v1/tasks') && method === 'GET') return json([TASK])
        return new Response(JSON.stringify({ detail: 'нет мока' }), { status: 404 })
      }),
    )

    render(<TasksPage user={COMMERCIAL} focus={['t1']} />)

    await user.click(await screen.findByRole('button', { name: 'Перенести' }))
    const start = screen.getByLabelText('Новое начало')
    const due = screen.getByLabelText('Новое окончание')
    await user.clear(start)
    await user.type(start, '2026-11-05')
    await user.clear(due)
    await user.type(due, '2026-11-12')
    await user.click(screen.getByRole('button', { name: 'Сохранить перенос' }))

    expect(await screen.findByText(/05\.11\.2026 — 12\.11\.2026/)).toBeInTheDocument()
  })
})
