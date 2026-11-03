import { vi } from 'vitest'

export type MockRoute = { status?: number; body?: unknown }

/**
 * Подменяет fetch таблицей маршрутов: ключ — фрагмент URL.
 * Более конкретные маршруты указывайте раньше общих.
 *
 * Ключ можно уточнить методом — «POST /api/v1/batches»: на один и тот же адрес
 * GET и POST отвечают по-разному.
 */
export function mockApi(routes: Record<string, MockRoute>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const method = (init?.method ?? 'GET').toUpperCase()
      const match = Object.entries(routes).find(([key]) => {
        const space = key.indexOf(' ')
        if (space > 0) {
          return key.slice(0, space).toUpperCase() === method && url.includes(key.slice(space + 1))
        }
        return url.includes(key)
      })
      if (!match) {
        return new Response(JSON.stringify({ detail: `нет мока для ${url}` }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      const { status = 200, body } = match[1]
      if (status === 204) return new Response(null, { status })
      return new Response(JSON.stringify(body ?? null), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}
