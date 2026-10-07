/** Клиент API erp_lite. Деньги приходят строками — точность не теряется. */

export type StockRow = {
  batch_item_id: string
  batch_number: string
  batch_date: string
  product_code: string
  product_name: string
  product_kind: string
  unit: string
  quantity_on_hand: string
  unit_cost: string
  value_rub: string
  snapshot_date: string | null
}

export type Role =
  | 'sales_manager'
  | 'commercial_director'
  | 'purchase_director'
  | 'import_manager'
  | 'executive_director'

export type SessionUser = {
  id: string
  login: string
  full_name: string
  role: Role
  role_title: string
}

export type Product = {
  id: string
  code: string
  name: string
  kind: string
  unit: string
  source: string
  is_active: boolean
}

export type SalesPlanItem = {
  id: string
  client_id: string
  client_name: string
  product_id: string
  product_code: string
  product_name: string
  product_kind: string
  unit: string
  month: number
  quantity: string
  notes: string | null
}

export type SalesPlanStatus = 'draft' | 'filling' | 'on_review' | 'approved'

export type SalesPlan = {
  id: string
  year: number
  manager_id: string
  manager_name: string
  created_by_name: string
  status: SalesPlanStatus
  status_title: string
  notes: string | null
  created_at: string
  updated_at: string
  editable_months: number[]
  items: SalesPlanItem[]
}

export type SalesPlanItemIn = {
  client_id: string
  product_id: string
  month: number
  quantity: string
}

export type CounterpartyRole = 'customer' | 'local_supplier' | 'import_supplier'

export type Counterparty = {
  id: string
  name: string
  inn: string | null
  note: string | null
  is_customer: boolean
  is_local_supplier: boolean
  is_import_supplier: boolean
  source: string
  is_active: boolean
}

export type CounterpartyIn = {
  name: string
  inn?: string | null
  note?: string | null
  is_customer?: boolean
  is_local_supplier?: boolean
  is_import_supplier?: boolean
}

export type ImportKind = {
  kind: string
  title: string
  entity: string
  columns: string[]
}

export type ImportSession = {
  id: string
  kind: string
  kind_title: string
  file_name: string
  status: string
  rows_total: number
  rows_created: number
  rows_updated: number
  rows_skipped: number
  rows_failed: number
  message: string | null
  created_at: string
}

export type ProductIn = {
  code: string
  name: string
  kind: string
  unit: string
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const moneyFormat = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const quantityFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const dateFormat = new Intl.DateTimeFormat('ru-RU')

export const MONTH_TITLES = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь',
]

export const MONTH_SHORT = [
  'янв',
  'фев',
  'мар',
  'апр',
  'май',
  'июн',
  'июл',
  'авг',
  'сен',
  'окт',
  'ноя',
  'дек',
]

export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? moneyFormat.format(parsed) : value
}

export function formatQuantity(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? quantityFormat.format(parsed) : value
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : dateFormat.format(parsed)
}

export const PRODUCT_KIND_LABELS: Record<string, string> = {
  goods: 'Товар',
  material: 'Материал',
  raw: 'Сырьё',
  finished: 'Готовая продукция',
}

/** Названия видов для фильтров: там уместно множественное число. */
export const PRODUCT_KIND_FILTER_TITLES: Record<string, string> = {
  material: 'Материалы',
  raw: 'Сырьё',
  finished: 'Готовая продукция',
  goods: 'Товары',
}

export const PRODUCT_KINDS = ['material', 'raw', 'finished', 'goods']

/** Роли контрагента из его признаков. */
export function counterpartyRoles(row: {
  is_customer: boolean
  is_local_supplier: boolean
  is_import_supplier: boolean
}): string[] {
  const roles: string[] = []
  if (row.is_customer) roles.push('Покупатель')
  if (row.is_local_supplier) roles.push('Локальный поставщик')
  if (row.is_import_supplier) roles.push('Импортный поставщик')
  return roles
}

/** Роли, которым виден раздел планирования продаж. */
export const SALES_PLAN_ROLES: Role[] = [
  'sales_manager',
  'commercial_director',
  'executive_director',
]

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: isFormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = `Ошибка запроса: HTTP ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // Тело не JSON — оставляем общий текст.
    }
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function fetchStock(signal?: AbortSignal): Promise<StockRow[]> {
  return request<StockRow[]>('/api/v1/stock', { signal })
}

export function login(loginName: string, password: string): Promise<SessionUser> {
  return request<SessionUser>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ login: loginName, password }),
  })
}

export function logout(): Promise<void> {
  return request<void>('/api/v1/auth/logout', { method: 'POST' })
}

export function fetchMe(): Promise<SessionUser> {
  return request<SessionUser>('/api/v1/auth/me')
}

export function fetchUsers(role?: Role): Promise<SessionUser[]> {
  const query = role ? `?role=${role}` : ''
  return request<SessionUser[]>(`/api/v1/users${query}`)
}

export function fetchProducts(): Promise<Product[]> {
  return request<Product[]>('/api/v1/products')
}

export function createProduct(payload: ProductIn): Promise<Product> {
  return request<Product>('/api/v1/products', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateProduct(
  productId: string,
  payload: Partial<ProductIn> & { is_active?: boolean },
): Promise<Product> {
  return request<Product>(`/api/v1/products/${productId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function fetchCounterparties(options?: {
  role?: CounterpartyRole
  includeInactive?: boolean
}): Promise<Counterparty[]> {
  const params = new URLSearchParams()
  if (options?.role) params.set('role', options.role)
  if (options?.includeInactive) params.set('include_inactive', 'true')
  const query = params.toString()
  return request<Counterparty[]>(`/api/v1/counterparties${query ? `?${query}` : ''}`)
}

export function createCounterparty(payload: CounterpartyIn): Promise<Counterparty> {
  return request<Counterparty>('/api/v1/counterparties', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateCounterparty(
  counterpartyId: string,
  payload: Partial<CounterpartyIn> & { is_active?: boolean },
): Promise<Counterparty> {
  return request<Counterparty>(`/api/v1/counterparties/${counterpartyId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function fetchImportKinds(): Promise<ImportKind[]> {
  return request<ImportKind[]>('/api/v1/imports/kinds')
}

export function fetchImports(limit = 20): Promise<ImportSession[]> {
  return request<ImportSession[]>(`/api/v1/imports?limit=${limit}`)
}

export function uploadImport(kind: string, file: File): Promise<ImportSession> {
  const form = new FormData()
  form.append('file', file)
  return request<ImportSession>(`/api/v1/imports/${kind}`, { method: 'POST', body: form })
}

export function fetchSalesPlans(): Promise<SalesPlan[]> {
  return request<SalesPlan[]>('/api/v1/sales-plans')
}

export function createSalesPlan(year: number, managerId?: string): Promise<SalesPlan> {
  return request<SalesPlan>('/api/v1/sales-plans', {
    method: 'POST',
    body: JSON.stringify(managerId ? { year, manager_id: managerId } : { year }),
  })
}

export function saveSalesPlanItems(planId: string, items: SalesPlanItemIn[]): Promise<SalesPlan> {
  return request<SalesPlan>(`/api/v1/sales-plans/${planId}/items`, {
    method: 'PUT',
    body: JSON.stringify({ items }),
  })
}

export function salesPlanAction(
  planId: string,
  action: 'send-to-fill' | 'submit' | 'approve',
): Promise<SalesPlan> {
  return request<SalesPlan>(`/api/v1/sales-plans/${planId}/${action}`, { method: 'POST' })
}

export function rejectSalesPlan(planId: string, reason: string): Promise<SalesPlan> {
  return request<SalesPlan>(`/api/v1/sales-plans/${planId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export function deleteSalesPlan(planId: string): Promise<void> {
  return request<void>(`/api/v1/sales-plans/${planId}`, { method: 'DELETE' })
}

/** Текст ошибки для показа пользователю. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return err instanceof Error ? err.message : 'Не удалось выполнить действие'
}
