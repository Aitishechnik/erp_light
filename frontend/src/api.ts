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

export type AnnualSalesPlanStatus = 'draft' | 'on_review' | 'approved' | 'revision'

export type AnnualSalesPlanManager = {
  manager_id: string
  manager_name: string
  plan_id: string | null
  plan_status: string | null
  plan_status_title: string | null
  approved: boolean
  positions: number
  clients: number
}

export type AnnualSalesPlanItem = {
  manager_id: string
  manager_name: string
  client_id: string
  client_name: string
  product_id: string
  product_code: string
  product_name: string
  unit: string
  month: number
  quantity: string
}

export type AnnualSalesPlan = {
  year: number
  status: AnnualSalesPlanStatus
  status_title: string
  submitted_by_name: string | null
  submitted_at: string | null
  approved_by_name: string | null
  approved_at: string | null
  notes: string | null
  is_stale: boolean
  all_approved: boolean
  missing_managers: string[]
  managers: AnnualSalesPlanManager[]
  items: AnnualSalesPlanItem[]
}

export type SalesPlanCorrectionStatus = 'draft' | 'on_review' | 'approved' | 'rejected'

export type SalesPlanCorrectionItem = {
  id: string
  client_id: string
  client_name: string
  product_id: string
  product_code: string
  product_name: string
  unit: string
  month: number
  quantity: string
  current_quantity: string
  notes: string | null
}

export type SalesPlanCorrection = {
  id: string
  plan_id: string
  status: SalesPlanCorrectionStatus
  status_title: string
  created_by_name: string
  reviewed_by_name: string | null
  reviewed_at: string | null
  reason: string | null
  review_reason: string | null
  created_at: string
  updated_at: string
  annual_needs_reapproval: boolean
  items: SalesPlanCorrectionItem[]
}

export type SalesPlanCorrectionItemIn = {
  client_id: string
  product_id: string
  month: number
  quantity: string
  notes?: string | null
}

export type PurchasePlanStatus = 'draft' | 'on_review' | 'approved'

export type PurchasePlanScheduleEntry = {
  month: number
  quantity: string
  order_year: number
  order_month: number
  overdue: boolean
}

export type PurchasePlanItem = {
  id: string
  sales_product_id: string
  sales_product_name: string
  product_id: string
  product_code: string
  product_name: string
  product_kind: string
  unit: string
  country_id: string
  country_name: string
  delivery_days: number
  quantity: string
  price_rub: string | null
  supplier_id: string | null
  supplier_name: string | null
  notes: string | null
  /** Поступило по связанным поступлениям, в единицах сырья. */
  fact_quantity: string
  /** Исполнение, %: факт ÷ годовое количество × 100. */
  fact_share: string
  /** Поступило по месяцам прихода партии: только месяцы с фактом. */
  fact_months: { month: number; quantity: string }[]
  schedule: PurchasePlanScheduleEntry[]
}

export type PurchasePlanMonth = { month: number; quantity: string }

export type PurchasePlanPosition = {
  product_id: string
  code: string
  name: string
  unit: string
  total: string
  months: PurchasePlanMonth[]
  decomposed: boolean
  status: 'ok' | 'added' | 'removed' | 'orphan'
  changed: boolean
}

export type PurchasePlanChange = {
  product_id: string
  code: string
  name: string
  unit: string
  month: number
  was: string | null
  now: string | null
  kind: 'added' | 'removed' | 'changed'
}

export type PurchasePlanSourceEvent = {
  id: string
  acknowledged_at: string
  acknowledged_by_name: string | null
  changes: PurchasePlanChange[]
}

export type PurchasePlanSource = {
  state: 'ok' | 'changed' | 'revision' | 'missing' | 'no_snapshot'
  title: string
  annual_status_title: string | null
  annual_approved_at: string | null
  snapshot_at: string | null
  acknowledged_at: string | null
  changes: PurchasePlanChange[]
  history: PurchasePlanSourceEvent[]
  revision_requested_at: string | null
  revision_requested_by_name: string | null
}

export type PurchasePlan = {
  id: string
  year: number
  status: PurchasePlanStatus
  status_title: string
  created_by_name: string
  approved_by_name: string | null
  approved_at: string | null
  notes: string | null
  created_at: string
  updated_at: string
  editable_months: number[]
  source: PurchasePlanSource
  positions: PurchasePlanPosition[]
  items: PurchasePlanItem[]
}

export type PurchasePlanItemIn = {
  id: string | null
  sales_product_id: string
  product_id: string
  country_id: string
  quantity: string
  price_rub: string | null
  supplier_id: string | null
  notes?: string | null
}

export type Country = {
  id: string
  name: string
  delivery_days: number
  is_active: boolean
  source: string
}

export type CountryIn = {
  name: string
  delivery_days: number
  is_active?: boolean
}

export type CountryUpdate = {
  name?: string
  delivery_days?: number
  is_active?: boolean
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

/** Категории валютных платежей: инвойс и рисковая надбавка закрываются отдельно. */
export type PaymentCategory = 'invoice' | 'risk'

/** Валюты общих расходов: выбор только из этих двух. */
export type ExpenseCurrency = 'RUB' | 'USD'

export type BatchItem = {
  id: string
  product_code: string
  product_name: string
  product_kind: string
  unit: string
  quantity: string
  unit_price_currency: string
  duty_percent: string
  vat_percent: string
  risk_unit_currency: string
  /** Пошлина строки, ₽: фикс после растаможки, до неё — null. */
  duty_fixed_rub: string | null
  /** НДС строки, ₽: фикс после растаможки, до неё — null. */
  vat_fixed_rub: string | null
  /** Строка плана закупок; null — закупка без плана. */
  purchase_plan_item_id: string | null
  /** Готовая подпись строки плана: «2026 · Китай · поставщик». */
  purchase_plan_label: string | null
  invoice_currency: string
  risk_currency: string
  duty_rub: string
  vat_rub: string
  risk_rub: string
  expenses_rub: string
  item_total_rub: string
  unit_cost: string
  quantity_on_hand: string
}

export type BatchFinance = {
  invoice_total_currency: string
  risk_total_currency: string
  exchange_rate: string
  rate_date: string | null
  rate_updated_at: string | null
  invoice_paid_currency: string
  invoice_paid_rub: string
  invoice_remaining_currency: string
  invoice_rate: string
  risk_paid_currency: string
  risk_paid_rub: string
  risk_remaining_currency: string
  risk_rate: string
  planned_invoice_currency: string
  planned_invoice_rub: string
  planned_risk_currency: string
  planned_risk_rub: string
  expenses_rub: string
  duty_rub: string
  vat_rub: string
  /** Средний курс партии по инвойсу и Risk — он виден в списке поступлений. */
  average_rate: string
  final_cost_rub: string
}

export type BatchPayment = {
  id: string
  payment_date: string
  amount_currency: string
  exchange_rate: string
  amount_rub: string
  category: PaymentCategory
  comment: string | null
}

export type BatchPaymentIn = {
  payment_date: string
  amount_currency: string
  exchange_rate: string
  category: PaymentCategory
  comment?: string | null
}

export type Batch = {
  id: string
  batch_number: string
  batch_type: string
  batch_date: string
  currency: string
  supplier_id: string | null
  supplier: string | null
  source: string
  comment: string | null
  created_at: string
  /** Дата растаможки; null — партия ещё не растаможена. */
  customs_date: string | null
  /** Курс, по которому зафиксированы пошлина и НДС. */
  customs_rate: string | null
  finance: BatchFinance
  payments: BatchPayment[]
  expenses: BatchExpense[]
  items: BatchItem[]
}

export type BatchItemIn = {
  /** Строка партии: нужна, чтобы сменить ссылку на план у растаможенной партии. */
  id?: string | null
  product_code: string
  product_name?: string | null
  quantity: string
  unit_price_currency: string
  duty_percent: string
  vat_percent: string
  risk_unit_currency: string
  /** Строка плана закупок; null — закупка без плана. */
  purchase_plan_item_id?: string | null
}

export type BatchExpenseIn = {
  amount_currency: string
  currency: ExpenseCurrency
  description: string
}

export type BatchExpense = {
  id: string
  amount_currency: string
  currency: ExpenseCurrency
  amount_rub: string
  description: string
}

export type BatchIn = {
  batch_number: string
  batch_date: string
  currency: string
  supplier_id: string | null
  supplier?: string | null
  current_exchange_rate: string | null
  auto_rate: boolean
  comment?: string | null
  items: BatchItemIn[]
  payments: BatchPaymentIn[]
  expenses: BatchExpenseIn[]
}

export type CurrencyRate = {
  code: string
  rate_date: string
  rate: string
  nominal: number
  source: string
}

export type ImportKind = {
  kind: string
  title: string
  entity: string
  columns: string[]
  roles: Role[]
  note: string | null
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

/** Роли, которым виден раздел планирования продаж (закупки — только просмотр). */
export const SALES_PLAN_ROLES: Role[] = [
  'sales_manager',
  'commercial_director',
  'executive_director',
  'purchase_director',
  'import_manager',
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

export function fetchBatches(from?: string, to?: string): Promise<Batch[]> {
  const params = new URLSearchParams()
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  const query = params.toString()
  return request<Batch[]>(`/api/v1/batches${query ? `?${query}` : ''}`)
}

export function updateBatch(batchId: string, payload: BatchIn): Promise<Batch> {
  return request<Batch>(`/api/v1/batches/${batchId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteBatch(batchId: string): Promise<void> {
  return request<void>(`/api/v1/batches/${batchId}`, { method: 'DELETE' })
}

/** Растаможка: дата, курс фиксации и (необязательно) правка итогов вручную. */
export type CustomsIn = {
  customs_date: string
  rate: string
  duty_rub?: string | null
  vat_rub?: string | null
}

export function applyCustoms(batchId: string, payload: CustomsIn): Promise<Batch> {
  return request<Batch>(`/api/v1/batches/${batchId}/customs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** Отмена растаможки: проценты пошлины и НДС возвращаются в строки. */
export function cancelCustoms(batchId: string): Promise<Batch> {
  return request<Batch>(`/api/v1/batches/${batchId}/customs`, { method: 'DELETE' })
}

/** Курс валюты: без даты — последний доступный (он же для незакрытой части). */
export function fetchRate(code: string, day?: string): Promise<CurrencyRate> {
  const query = day ? `?date=${day}` : ''
  return request<CurrencyRate>(`/api/v1/rates/${code}${query}`)
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

export function fetchCountries(options?: { includeInactive?: boolean }): Promise<Country[]> {
  const params = new URLSearchParams()
  if (options?.includeInactive) params.set('include_inactive', 'true')
  const query = params.toString()
  return request<Country[]>(`/api/v1/countries${query ? `?${query}` : ''}`)
}

export function createCountry(payload: CountryIn): Promise<Country> {
  return request<Country>('/api/v1/countries', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateCountry(countryId: string, payload: CountryUpdate): Promise<Country> {
  return request<Country>(`/api/v1/countries/${countryId}`, {
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

/** Загрузка файла «Партия» из 1С в конкретное поступление (из его карточки). */
export type BatchImportResult = {
  batch: Batch
  report: ImportSession
}

export function uploadBatchItems(batchId: string, file: File): Promise<BatchImportResult> {
  const form = new FormData()
  form.append('file', file)
  return request<BatchImportResult>(`/api/v1/batches/${batchId}/import-items`, {
    method: 'POST',
    body: form,
  })
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

/** Роли, которым виден годовой план отдела продаж. */
export const ANNUAL_SALES_PLAN_ROLES: Role[] = [
  'sales_manager',
  'commercial_director',
  'executive_director',
  'purchase_director',
]

export function fetchAnnualSalesPlan(year: number): Promise<AnnualSalesPlan> {
  return request<AnnualSalesPlan>(`/api/v1/annual-sales-plans?year=${year}`)
}

export function annualSalesPlanAction(
  year: number,
  action: 'submit' | 'approve',
): Promise<AnnualSalesPlan> {
  return request<AnnualSalesPlan>(`/api/v1/annual-sales-plans/${year}/${action}`, {
    method: 'POST',
  })
}

export function rejectAnnualSalesPlan(year: number, reason: string): Promise<AnnualSalesPlan> {
  return request<AnnualSalesPlan>(`/api/v1/annual-sales-plans/${year}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export function reopenAnnualSalesPlan(year: number, reason: string): Promise<AnnualSalesPlan> {
  return request<AnnualSalesPlan>(`/api/v1/annual-sales-plans/${year}/reopen`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export function fetchSalesPlanCorrections(planId: string): Promise<SalesPlanCorrection[]> {
  return request<SalesPlanCorrection[]>(`/api/v1/sales-plan-corrections?plan_id=${planId}`)
}

export function createSalesPlanCorrection(planId: string): Promise<SalesPlanCorrection> {
  return request<SalesPlanCorrection>('/api/v1/sales-plan-corrections', {
    method: 'POST',
    body: JSON.stringify({ plan_id: planId }),
  })
}

export function saveSalesPlanCorrectionItems(
  correctionId: string,
  items: SalesPlanCorrectionItemIn[],
): Promise<SalesPlanCorrection> {
  return request<SalesPlanCorrection>(`/api/v1/sales-plan-corrections/${correctionId}/items`, {
    method: 'PUT',
    body: JSON.stringify({ items }),
  })
}

export function submitSalesPlanCorrection(correctionId: string): Promise<SalesPlanCorrection> {
  return request<SalesPlanCorrection>(`/api/v1/sales-plan-corrections/${correctionId}/submit`, {
    method: 'POST',
  })
}

export function approveSalesPlanCorrection(correctionId: string): Promise<SalesPlanCorrection> {
  return request<SalesPlanCorrection>(`/api/v1/sales-plan-corrections/${correctionId}/approve`, {
    method: 'POST',
  })
}

export function rejectSalesPlanCorrection(
  correctionId: string,
  reason: string,
): Promise<SalesPlanCorrection> {
  return request<SalesPlanCorrection>(`/api/v1/sales-plan-corrections/${correctionId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export function deleteSalesPlanCorrection(correctionId: string): Promise<void> {
  return request<void>(`/api/v1/sales-plan-corrections/${correctionId}`, { method: 'DELETE' })
}

/** План закупок сырья: один ручной план на год, утверждает исполнительный директор. */
export function fetchPurchasePlans(year?: number): Promise<PurchasePlan[]> {
  const query = year ? `?year=${year}` : ''
  return request<PurchasePlan[]>(`/api/v1/purchase-plans${query}`)
}

export function createPurchasePlan(year: number): Promise<PurchasePlan> {
  return request<PurchasePlan>('/api/v1/purchase-plans', {
    method: 'POST',
    body: JSON.stringify({ year }),
  })
}

export function savePurchasePlanItems(
  planId: string,
  items: PurchasePlanItemIn[],
): Promise<PurchasePlan> {
  return request<PurchasePlan>(`/api/v1/purchase-plans/${planId}/items`, {
    method: 'PUT',
    body: JSON.stringify({ items }),
  })
}

export function submitPurchasePlan(planId: string): Promise<PurchasePlan> {
  return request<PurchasePlan>(`/api/v1/purchase-plans/${planId}/submit`, { method: 'POST' })
}

export function approvePurchasePlan(planId: string): Promise<PurchasePlan> {
  return request<PurchasePlan>(`/api/v1/purchase-plans/${planId}/approve`, { method: 'POST' })
}

export function rejectPurchasePlan(planId: string, reason: string): Promise<PurchasePlan> {
  return request<PurchasePlan>(`/api/v1/purchase-plans/${planId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export function reopenPurchasePlan(planId: string, reason: string): Promise<PurchasePlan> {
  return request<PurchasePlan>(`/api/v1/purchase-plans/${planId}/reopen`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export function acknowledgePurchasePlanSource(planId: string): Promise<PurchasePlan> {
  return request<PurchasePlan>(`/api/v1/purchase-plans/${planId}/acknowledge-source`, {
    method: 'POST',
  })
}

export function requestPurchasePlanRevision(planId: string, reason: string): Promise<PurchasePlan> {
  return request<PurchasePlan>(`/api/v1/purchase-plans/${planId}/request-revision`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export function deletePurchasePlan(planId: string): Promise<void> {
  return request<void>(`/api/v1/purchase-plans/${planId}`, { method: 'DELETE' })
}

/** Текст ошибки для показа пользователю. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return err instanceof Error ? err.message : 'Не удалось выполнить действие'
}
