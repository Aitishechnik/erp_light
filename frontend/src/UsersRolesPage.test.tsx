import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AccessPayload, AdminUser } from './api'
import { mockApi } from './apiMock'
import { UsersRolesPage } from './UsersRolesPage'

const ACCESS: AccessPayload = {
  levels: [
    {
      key: 'sales_manager',
      title: 'Менеджер по продажам',
      description: 'Свои планы',
      rights: { sales_plans: { actions: ['view'], scope: 'own' } },
    },
    {
      key: 'commercial_director',
      title: 'Коммерческий директор',
      description: 'Весь коммерческий блок',
      rights: { sales_plans: { actions: ['view', 'approve'], scope: 'all' } },
    },
  ],
  blocks: [
    {
      key: 'sales_plans',
      title: 'Планирование продаж',
      group: 'planning',
      scoped: true,
      actions: [
        { key: 'view', title: 'Смотреть' },
        { key: 'approve', title: 'Утверждать' },
      ],
    },
  ],
}

const ADMIN: AdminUser = {
  id: 'admin-1',
  login: 'admin',
  full_name: 'Администратор',
  role: 'admin',
  role_title: 'Администратор',
  is_admin: true,
  is_active: true,
  created_at: '2026-11-01T00:00:00Z',
  permissions: null,
}

const SALES: AdminUser = {
  id: 'u1',
  login: 'valeri_serg',
  full_name: 'Валерий Сергеевич',
  role: 'commercial_director',
  role_title: 'Коммерческий директор',
  is_admin: false,
  is_active: true,
  created_at: '2026-11-02T00:00:00Z',
  permissions: null,
}

function routes(): Record<string, { status?: number; body?: unknown }> {
  return {
    'GET /api/v1/access': { body: ACCESS },
    'GET /api/v1/admin/users': { body: [ADMIN, SALES] },
    'POST /api/v1/admin/users': { status: 201, body: SALES },
    'DELETE /api/v1/admin/users/u1': { status: 204 },
    'PUT /api/v1/access/sales_manager': { body: ACCESS.levels[0] },
    'PUT /api/v1/access/commercial_director': { body: ACCESS.levels[1] },
  }
}

function lastBody(
  fragment: string,
  method: string,
): { login?: string; role?: string; rights?: unknown } {
  const mock = fetch as unknown as {
    mock: { calls: [RequestInfo | URL, { method?: string; body?: string }?][] }
  }
  const matching = mock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes(fragment) && (init?.method ?? 'GET').toUpperCase() === method,
  )
  const call = matching[matching.length - 1]
  return JSON.parse(String(call?.[1]?.body ?? '{}'))
}

describe('UsersRolesPage', () => {
  it('показывает сотрудников и заводит нового с уровнем доступа', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<UsersRolesPage user={{ id: 'admin-1' }} />)

    expect(await screen.findByText('Валерий Сергеевич')).toBeInTheDocument()
    expect(screen.getByText('admin')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Добавить сотрудника' }))
    await user.type(screen.getByLabelText('Имя сотрудника'), 'Новый Сотрудник')
    await user.type(screen.getByLabelText('Логин сотрудника'), 'new_user')
    await user.type(screen.getByLabelText('Пароль сотрудника'), 'password-123')
    await user.selectOptions(screen.getByLabelText('Уровень доступа'), 'sales_manager')
    await user.click(screen.getByRole('button', { name: 'Завести' }))

    await waitFor(() => {
      const body = lastBody('/api/v1/admin/users', 'POST')
      expect(body.login).toBe('new_user')
      expect(body.role).toBe('sales_manager')
    })
  })

  it('удаляет сотрудника после подтверждения', async () => {
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockApi(routes())
    render(<UsersRolesPage user={{ id: 'admin-1' }} />)

    const row = (await screen.findByText('Валерий Сергеевич')).closest('tr')
    if (!row) throw new Error('строка сотрудника не найдена')
    await user.click(within(row).getByRole('button', { name: 'Удалить' }))

    await waitFor(() => {
      const mock = fetch as unknown as {
        mock: { calls: [RequestInfo | URL, { method?: string }?][] }
      }
      const called = mock.mock.calls.some(
        ([input, init]) =>
          String(input).includes('/api/v1/admin/users/u1') &&
          (init?.method ?? 'GET').toUpperCase() === 'DELETE',
      )
      expect(called).toBe(true)
    })
    confirm.mockRestore()
  })

  it('собирает права уровня по блокам и сохраняет их', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    render(<UsersRolesPage user={{ id: 'admin-1' }} />)

    await user.click(await screen.findByRole('tab', { name: 'Права уровней' }))
    await user.click(await screen.findByRole('button', { name: 'Коммерческий директор' }))

    const approve = await screen.findByLabelText('Планирование продаж: Утверждать')
    expect(approve).toBeChecked()
    await user.click(approve)

    await user.click(screen.getByRole('button', { name: 'Сохранить права' }))

    await waitFor(() => {
      const body = lastBody('/api/v1/access/commercial_director', 'PUT')
      const rights = body.rights as {
        sales_plans: { actions: string[]; scope: string }
      }
      expect(rights.sales_plans.actions).toEqual(['view'])
      expect(rights.sales_plans.scope).toBe('all')
    })
  })
})
