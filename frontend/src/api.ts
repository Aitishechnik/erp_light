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

const moneyFormat = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const quantityFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const dateFormat = new Intl.DateTimeFormat('ru-RU')

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
}

export async function fetchStock(signal?: AbortSignal): Promise<StockRow[]> {
  const response = await fetch('/api/v1/stock', { signal })
  if (!response.ok) {
    throw new Error(`Не удалось загрузить остатки: HTTP ${response.status}`)
  }
  return (await response.json()) as StockRow[]
}
