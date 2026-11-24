import type { BlockRights, Role } from './api'

const r = (actions: string, scope: 'own' | 'all' = 'all'): BlockRights => ({
  actions: actions.split(' '),
  scope,
})

/**
 * Права уровней для тестов: копия стартовой матрицы backend.
 *
 * Настоящие права приходят с сервера в SessionUser.permissions; здесь — чтобы
 * компонентные тесты могли собрать пользователя без запроса к API.
 */
export const PERMISSIONS: Record<Role, Record<string, BlockRights>> = {
  sales_manager: {
    sales_plans: r('view edit submit delete', 'own'),
    corrections: r('view propose', 'own'),
    annual_plan: r('view'),
    monthly_plan: r('view edit', 'own'),
    receipts: r('view'),
    month_results: r('view reasons', 'own'),
    plan_fact: r('view', 'own'),
    directories: r('view edit'),
    countries: r('view'),
    stock: r('view'),
    tasks: r('view', 'own'),
    imports: r('view local_suppliers import_suppliers customers nomenclature'),
    rates: r('view'),
    journal: r('view', 'own'),
  },
  sales_assistant: {
    directories: r('view'),
    countries: r('view'),
    stock: r('view'),
    receipts: r('view'),
    tasks: r('view', 'own'),
    imports: r('view'),
    rates: r('view'),
    journal: r('view', 'own'),
  },
  commercial_director: {
    sales_plans: r('view edit approve dispatch delete'),
    corrections: r('view propose approve'),
    annual_plan: r('view submit'),
    monthly_plan: r('view edit approve'),
    month_results: r('view match reasons close history'),
    plan_fact: r('view'),
    receipts: r('view'),
    directories: r('view edit'),
    countries: r('view'),
    stock: r('view'),
    tasks: r('view create manage'),
    imports: r('view local_suppliers import_suppliers customers nomenclature sales'),
    rates: r('view'),
    journal: r('view'),
    users: r('view'),
  },
  purchase_director: {
    sales_plans: r('view'),
    annual_plan: r('view'),
    purchase_plan: r('view edit delete'),
    receipts: r('view edit delete customs'),
    directories: r('view edit'),
    countries: r('view edit'),
    stock: r('view'),
    month_results: r('view history'),
    plan_fact: r('view'),
    imports: r(
      'view local_suppliers import_suppliers customers nomenclature import_receipts batch_items',
    ),
    rates: r('view refresh'),
    journal: r('view', 'own'),
  },
  import_manager: {
    sales_plans: r('view'),
    purchase_plan: r('view edit'),
    receipts: r('view edit delete'),
    directories: r('view'),
    countries: r('view'),
    stock: r('view'),
    imports: r('view import_receipts batch_items'),
    rates: r('view refresh'),
    journal: r('view', 'own'),
  },
  executive_director: {
    sales_plans: r('view edit submit approve dispatch delete'),
    corrections: r('view propose approve'),
    annual_plan: r('view submit approve'),
    monthly_plan: r('view edit approve'),
    purchase_plan: r('view edit approve delete'),
    receipts: r('view edit delete customs'),
    directories: r('view edit'),
    countries: r('view edit'),
    stock: r('view'),
    month_results: r('view match reasons close history'),
    plan_fact: r('view'),
    tasks: r('view create manage'),
    imports: r(
      'view local_suppliers import_suppliers customers nomenclature import_receipts batch_items sales',
    ),
    rates: r('view refresh'),
    journal: r('view cleanup'),
    users: r('view'),
  },
  admin: {},
}

/** Удобно, когда в тесте нужен только один блок прав. */
export function rightsFor(role: Role): Record<string, BlockRights> {
  return PERMISSIONS[role]
}
