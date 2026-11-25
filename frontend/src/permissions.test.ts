import { describe, expect, it } from 'vitest'
import { can, canManageAll, isActiveManager, type Role, scopeFor, scopeOf } from './api'
import { PERMISSIONS } from './testPermissions'

function user(role: Role, is_manager = false) {
  return {
    id: `${role}-1`,
    login: role,
    full_name: role,
    role,
    role_title: role,
    is_manager,
    permissions: PERMISSIONS[role],
  }
}

describe('права активного менеджера', () => {
  it('ассистент без прав уровня получает только свои продажи', () => {
    const assistant = user('sales_assistant', true)
    expect(isActiveManager(assistant)).toBe(true)
    expect(can(assistant, 'sales_plans', 'view')).toBe(true)
    expect(can(assistant, 'sales_plans', 'edit')).toBe(true)
    expect(can(assistant, 'sales_plans', 'approve')).toBe(false)
    expect(can(assistant, 'purchase_plan', 'edit')).toBe(false)
    expect(scopeFor(assistant, 'sales_plans', 'edit')).toBe('own')
    expect(canManageAll(assistant, 'sales_plans', 'edit')).toBe(false)
  })

  it('без галочки ассистент планов не видит', () => {
    const assistant = user('sales_assistant', false)
    expect(can(assistant, 'sales_plans', 'view')).toBe(false)
    expect(can(assistant, 'monthly_plan', 'edit')).toBe(false)
  })

  it('директор по закупкам видит все планы, но правит только свой', () => {
    const purchase = user('purchase_director', true)
    expect(scopeOf(purchase, 'sales_plans')).toBe('all')
    expect(can(purchase, 'sales_plans', 'edit')).toBe(true)
    expect(scopeFor(purchase, 'sales_plans', 'edit')).toBe('own')
    expect(scopeFor(purchase, 'sales_plans', 'view')).toBe('all')
    expect(canManageAll(purchase, 'sales_plans', 'edit')).toBe(false)
  })

  it('коммерческий директор управляет всеми планами', () => {
    const commercial = user('commercial_director', true)
    expect(can(commercial, 'sales_plans', 'approve')).toBe(true)
    expect(scopeFor(commercial, 'sales_plans', 'edit')).toBe('all')
    expect(canManageAll(commercial, 'sales_plans', 'edit')).toBe(true)
  })
})
