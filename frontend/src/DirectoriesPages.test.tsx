import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Counterparty, ImportKind, ImportSession, Product, Role, SessionUser } from './api'
import { type MockResponse, mockApi } from './apiMock'
import { CounterpartiesPage } from './CounterpartiesPage'
import { ImportsPage } from './ImportsPage'
import { NomenclaturePage } from './NomenclaturePage'

const COUNTERPARTIES: Counterparty[] = [
  {
    id: 'c1',
    name: 'ООО Ромашка',
    inn: '7701234567',
    note: null,
    is_customer: true,
    is_local_supplier: false,
    is_import_supplier: false,
    source: '1c',
    is_active: true,
  },
  {
    id: 'c2',
    name: 'Комус',
    inn: null,
    note: null,
    is_customer: true,
    is_local_supplier: true,
    is_import_supplier: false,
    source: '1c',
    is_active: false,
  },
]

const PRODUCTS: Product[] = [
  {
    id: 'p1',
    code: 'ТОВ394895',
    name: 'Антиоксидант',
    kind: 'material',
    unit: 'л',
    source: '1c',
    is_active: true,
  },
  {
    id: 'p2',
    code: 'ТОВ396451',
    name: 'Абрикос цукаты',
    kind: 'raw',
    unit: 'кг',
    source: '1c',
    is_active: false,
  },
]

const DIRECTORY_ROLES: Role[] = [
  'sales_manager',
  'commercial_director',
  'purchase_director',
  'executive_director',
]

const ADMIN: SessionUser = {
  id: 'ed-1',
  login: 'executive',
  full_name: 'Ольга Директорова',
  role: 'executive_director',
  role_title: 'Исполнительный директор',
}

const KINDS: ImportKind[] = [
  {
    kind: 'customers',
    title: 'Покупатели',
    entity: 'counterparties',
    columns: ['Наименование'],
    roles: DIRECTORY_ROLES,
    note: null,
  },
  {
    kind: 'nomenclature',
    title: 'Номенклатура',
    entity: 'products',
    columns: ['Код', 'Полное наименование', 'Базовая единица измерения', 'Вид номенклатуры'],
    roles: DIRECTORY_ROLES,
    note: null,
  },
  {
    kind: 'import_receipts',
    title: 'Импортные поступления',
    entity: 'batches',
    columns: ['Номер', 'Дата', 'Контрагент', 'Комментарий'],
    roles: ['purchase_director', 'import_manager', 'executive_director'],
    note: 'Создаёт черновики поступлений для календаря',
  },
]

const SESSION: ImportSession = {
  id: 's1',
  kind: 'customers',
  kind_title: 'Покупатели',
  file_name: 'Покупатели.xlsx',
  status: 'ok',
  rows_total: 789,
  rows_created: 775,
  rows_updated: 4,
  rows_skipped: 10,
  rows_failed: 0,
  message: 'Изменено 2 поз. (наименование 1, вид 1): ТОВ1, ТОВ2',
  created_at: '2026-10-08T01:00:00Z',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Тела запросов: у POST это строка JSON внутри init.body. */
function bodies(): string[] {
  const mock = fetch as unknown as { mock: { calls: unknown[][] } }
  return mock.mock.calls.map((call) =>
    String((call[1] as { body?: unknown } | undefined)?.body ?? ''),
  )
}

/** Параметры запроса: серверные фильтры и порции видны в адресе. */
function query(url: string): URLSearchParams {
  return new URL(url, 'http://localhost').searchParams
}

/**
 * Сервер номенклатуры: те же правила, что у настоящего API, — поиск, вид,
 * отключённые и порция с общим числом в заголовке.
 */
function productsServer(rows: Product[]) {
  return (url: string): MockResponse => {
    const params = query(url)
    const kinds = params.get('kinds')?.split(',') ?? []
    const includeInactive = params.get('include_inactive') === 'true'
    const search = (params.get('search') ?? '').toLowerCase()
    const limit = Number(params.get('limit') ?? rows.length)
    const offset = Number(params.get('offset') ?? 0)
    const found = rows
      .filter((row) => includeInactive || row.is_active)
      .filter((row) => kinds.length === 0 || kinds.includes(row.kind))
      .filter(
        (row) =>
          search === '' ||
          row.name.toLowerCase().includes(search) ||
          row.code.toLowerCase().includes(search),
      )
      .sort((left, right) => left.code.localeCompare(right.code))
    return {
      body: found.slice(offset, offset + limit),
      headers: { 'X-Total-Count': String(found.length) },
    }
  }
}

/** Сервер контрагентов: роль, отключённые, поиск и порция. */
function counterpartiesServer(rows: Counterparty[]) {
  return (url: string): MockResponse => {
    const params = query(url)
    const role = params.get('role')
    const includeInactive = params.get('include_inactive') === 'true'
    const search = (params.get('search') ?? '').toLowerCase()
    const limit = Number(params.get('limit') ?? rows.length)
    const offset = Number(params.get('offset') ?? 0)
    const found = rows
      .filter((row) => includeInactive || row.is_active)
      .filter((row) => {
        if (role === 'customer') return row.is_customer
        if (role === 'local_supplier') return row.is_local_supplier
        if (role === 'import_supplier') return row.is_import_supplier
        return true
      })
      .filter((row) => search === '' || row.name.toLowerCase().includes(search))
      .sort((left, right) => left.name.localeCompare(right.name))
    return {
      body: found.slice(offset, offset + limit),
      headers: { 'X-Total-Count': String(found.length) },
    }
  }
}

describe('CounterpartiesPage', () => {
  it('показывает роли контрагента; отключённые скрыты до запроса', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/counterparties': { handler: counterpartiesServer(COUNTERPARTIES) } })
    render(<CounterpartiesPage />)

    expect(await screen.findByText('ООО Ромашка')).toBeInTheDocument()
    expect(screen.getByTestId('counterparties-count')).toHaveTextContent('1')
    expect(screen.queryByText('Комус')).not.toBeInTheDocument()

    await user.click(screen.getByLabelText('показывать отключённых'))
    await waitFor(() => expect(screen.getByTestId('counterparties-count')).toHaveTextContent('2'))
    expect(screen.getByText('Покупатель, Локальный поставщик')).toBeInTheDocument()
  })

  it('контрагент из сообщения показывается первым и подсвечивается', async () => {
    const base: Counterparty = {
      id: 'base',
      name: 'Клиент',
      inn: null,
      note: null,
      is_customer: true,
      is_local_supplier: false,
      is_import_supplier: false,
      source: '1c',
      is_active: true,
      manager_id: null,
      manager_name: null,
    }
    const many: Counterparty[] = Array.from({ length: 120 }, (_, index) => ({
      ...base,
      id: `c-${index}`,
      name: `Клиент ${index}`,
    }))
    const target: Counterparty = { ...base, id: 'target-id', name: 'ООО Поздний' }
    many.push(target)
    mockApi({
      '/api/v1/counterparties/': { body: target },
      '/api/v1/counterparties': { handler: counterpartiesServer(many) },
    })
    render(<CounterpartiesPage focusId="target-id" />)

    const table = await screen.findByTestId('counterparties-table')
    await waitFor(() => {
      const firstRow = within(table).getAllByRole('row')[1]
      expect(firstRow).toHaveClass('focus-row')
      expect(firstRow).toHaveTextContent('ООО Поздний')
    })
  })

  it('фильтрует по поиску на сервере', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/counterparties': { handler: counterpartiesServer(COUNTERPARTIES) } })
    render(<CounterpartiesPage />)

    await screen.findByText('ООО Ромашка')
    await user.type(screen.getByLabelText('Поиск по наименованию'), 'ромашка')

    await waitFor(() => expect(screen.getByTestId('counterparties-count')).toHaveTextContent('1'))
    expect(screen.getByText('ООО Ромашка')).toBeInTheDocument()

    await user.clear(screen.getByLabelText('Поиск по наименованию'))
    await user.type(screen.getByLabelText('Поиск по наименованию'), 'нетакого')
    await waitFor(() => expect(screen.getByTestId('counterparties-count')).toHaveTextContent('0'))
  })

  it('добавляет контрагента с признаками', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /api/v1/counterparties': { body: COUNTERPARTIES[0] },
      '/api/v1/counterparties': { handler: counterpartiesServer(COUNTERPARTIES) },
    })
    render(<CounterpartiesPage />)

    await screen.findByText('ООО Ромашка')
    await user.type(screen.getByLabelText('Наименование контрагента'), 'Новый Поставщик')
    await user.click(screen.getByLabelText('импортный поставщик'))
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    const posted = bodies().some((body) => body.includes('"is_import_supplier":true'))
    expect(posted).toBe(true)
  })

  it('показывает ошибку при дубле наименования', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /api/v1/counterparties': {
        status: 409,
        body: { detail: 'Контрагент «Комус» уже есть' },
      },
      '/api/v1/counterparties': { handler: counterpartiesServer(COUNTERPARTIES) },
    })
    render(<CounterpartiesPage />)

    await screen.findByText('ООО Ромашка')
    await user.type(screen.getByLabelText('Наименование контрагента'), 'Комус')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('уже есть')
  })

  it('администратор может менять контрагентов', async () => {
    mockApi({ '/api/v1/counterparties': { handler: counterpartiesServer(COUNTERPARTIES) } })
    render(<CounterpartiesPage user={ADMIN} />)

    expect(await screen.findByText('ООО Ромашка')).toBeInTheDocument()
    expect(screen.getByLabelText('Наименование контрагента')).toBeInTheDocument()
    expect(screen.getByLabelText('Менеджер клиента ООО Ромашка')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Отключить' })).toBeInTheDocument()
  })

  it('показывает «Показать ещё» и догружает следующую сотню', async () => {
    const user = userEvent.setup()
    const base: Counterparty = {
      id: 'base',
      name: 'Клиент',
      inn: null,
      note: null,
      is_customer: true,
      is_local_supplier: false,
      is_import_supplier: false,
      source: '1c',
      is_active: true,
    }
    const many = Array.from({ length: 250 }, (_, index) => ({
      ...base,
      id: `c-${index}`,
      name: `Клиент ${String(index).padStart(3, '0')}`,
    }))
    mockApi({ '/api/v1/counterparties': { handler: counterpartiesServer(many) } })
    render(<CounterpartiesPage />)

    expect(await screen.findByTestId('counterparties-shown')).toHaveTextContent(
      'Показано 100 из 250',
    )
    await user.click(screen.getByRole('button', { name: 'Показать ещё 100' }))
    await waitFor(() =>
      expect(screen.getByTestId('counterparties-shown')).toHaveTextContent('Показано 200 из 250'),
    )
  })
})

describe('NomenclaturePage', () => {
  it('фильтрует по виду и ищет по коду — на сервере', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/products': { handler: productsServer(PRODUCTS) } })
    render(<NomenclaturePage />)

    expect(await screen.findByText('Антиоксидант')).toBeInTheDocument()
    // Отключённые позиции по умолчанию скрыты.
    expect(screen.getByTestId('products-count')).toHaveTextContent('1')

    await user.click(screen.getByLabelText('показывать отключённые'))
    await waitFor(() => expect(screen.getByTestId('products-count')).toHaveTextContent('2'))

    await user.selectOptions(screen.getByLabelText('Фильтр по виду'), 'raw')
    await waitFor(() => expect(screen.getByTestId('products-count')).toHaveTextContent('1'))
    expect(screen.getByText('Абрикос цукаты')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Фильтр по виду'), '')
    await user.type(screen.getByLabelText('Поиск по коду или наименованию'), 'ТОВ3948')
    await waitFor(() => expect(screen.getByTestId('products-count')).toHaveTextContent('1'))
    expect(screen.getByText('Антиоксидант')).toBeInTheDocument()
  })

  it('заводит позицию номенклатуры', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /api/v1/products': { body: PRODUCTS[0] },
      '/api/v1/products': { handler: productsServer(PRODUCTS) },
    })
    render(<NomenclaturePage />)

    await screen.findByText('Антиоксидант')
    await user.type(screen.getByLabelText('Код'), 'ТОВ900')
    await user.type(screen.getByLabelText('Наименование'), 'Грунтовка')
    await user.type(screen.getByLabelText('Единица'), 'л')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    const posted = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.some((call) =>
      JSON.stringify(call[1] ?? {}).includes('ТОВ900'),
    )
    expect(posted).toBe(true)
  })

  it('показывает «Показать ещё» и догружает следующую сотню', async () => {
    const user = userEvent.setup()
    const many: Product[] = Array.from({ length: 250 }, (_, index) => ({
      id: `p-${index}`,
      code: `КОД${String(index).padStart(4, '0')}`,
      name: `Позиция ${index}`,
      kind: 'material',
      unit: 'шт',
      source: '1c',
      is_active: true,
    }))
    mockApi({ '/api/v1/products': { handler: productsServer(many) } })
    render(<NomenclaturePage />)

    expect(await screen.findByTestId('products-shown')).toHaveTextContent('Показано 100 из 250')
    await user.click(screen.getByRole('button', { name: 'Показать ещё 100' }))
    await waitFor(() =>
      expect(screen.getByTestId('products-shown')).toHaveTextContent('Показано 200 из 250'),
    )
    // Догруженные строки действительно попали в таблицу.
    expect(screen.getByTestId('products-table')).toHaveTextContent('Позиция 150')
  })

  it('позиция из сообщения показывается первой, даже если она вне порции', async () => {
    const many: Product[] = Array.from({ length: 150 }, (_, index) => ({
      id: `p-${index}`,
      code: `КОД${String(index).padStart(4, '0')}`,
      name: `Позиция ${index}`,
      kind: 'material',
      unit: 'шт',
      source: '1c',
      is_active: true,
    }))
    const target: Product = {
      id: 'target-id',
      code: 'ЯЯЯ-1',
      name: 'Поздняя позиция',
      kind: 'material',
      unit: 'шт',
      source: '1c',
      is_active: true,
    }
    mockApi({
      '/api/v1/products/': { body: target },
      '/api/v1/products': { handler: productsServer([...many, target]) },
    })
    render(<NomenclaturePage focusId="target-id" />)

    const table = await screen.findByTestId('products-table')
    await waitFor(() => {
      const firstRow = within(table).getAllByRole('row')[1]
      expect(firstRow).toHaveClass('focus-row')
      expect(firstRow).toHaveTextContent('Поздняя позиция')
    })
  })
})

const SALES: SessionUser = {
  id: 'u1',
  login: 'sales',
  full_name: 'Иван Петров',
  role: 'sales_manager',
  role_title: 'Менеджер по продажам',
}

const IMPORTER: SessionUser = {
  id: 'u2',
  login: 'import',
  full_name: 'Шахидул Ислам',
  role: 'import_manager',
  role_title: 'Менеджер по закупкам (импорт)',
}

describe('ImportsPage', () => {
  it('показывает карточки типов и журнал загрузок', async () => {
    mockApi({
      '/api/v1/imports/kinds': { body: KINDS },
      '/api/v1/imports?limit=20': { body: [SESSION] },
    })
    render(<ImportsPage user={SALES} />)

    expect(await screen.findByTestId('import-card-customers')).toHaveTextContent('Покупатели')
    expect(screen.getByTestId('import-card-nomenclature')).toHaveTextContent(
      'Код, Полное наименование, Базовая единица измерения, Вид номенклатуры',
    )
    // Менеджеру по продажам импортные поступления недоступны.
    expect(screen.queryByTestId('import-card-import_receipts')).toBeNull()
    expect(screen.getByTestId('imports-journal')).toHaveTextContent('Покупатели.xlsx')
    expect(screen.getByTestId('imports-journal')).toHaveTextContent('775')
    // Замечания загрузки (что изменилось или почему строка не прошла) видны в журнале.
    expect(screen.getByTestId('imports-journal')).toHaveTextContent(
      'Изменено 2 поз. (наименование 1, вид 1): ТОВ1, ТОВ2',
    )
  })

  it('показывает закупщику только импортные поступления', async () => {
    mockApi({
      '/api/v1/imports/kinds': { body: KINDS },
      '/api/v1/imports?limit=20': { body: [] },
    })
    render(<ImportsPage user={IMPORTER} />)

    const card = await screen.findByTestId('import-card-import_receipts')
    expect(card).toHaveTextContent('Импортные поступления')
    expect(card).toHaveTextContent('Номер, Дата, Контрагент, Комментарий')
    expect(card).toHaveTextContent('черновики поступлений')
    expect(screen.queryByTestId('import-card-customers')).toBeNull()
    expect(screen.queryByTestId('import-card-nomenclature')).toBeNull()
  })

  it('администратор видит все карточки загрузки', async () => {
    mockApi({
      '/api/v1/imports/kinds': { body: KINDS },
      '/api/v1/imports?limit=20': { body: [] },
    })
    render(<ImportsPage user={ADMIN} />)

    expect(await screen.findByTestId('import-card-customers')).toBeInTheDocument()
    expect(screen.getByTestId('import-card-nomenclature')).toBeInTheDocument()
    expect(screen.getByTestId('import-card-import_receipts')).toBeInTheDocument()
  })

  it('загружает файл и показывает итог', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/imports/kinds': { body: KINDS },
      '/api/v1/imports?limit=20': { body: [] },
      '/api/v1/imports/customers': { body: SESSION },
    })
    render(<ImportsPage user={SALES} />)

    await screen.findByTestId('import-card-customers')
    const file = new File(['xlsx'], 'Покупатели.xlsx', { type: 'text/plain' })
    await user.upload(screen.getByLabelText('Файл: Покупатели'), file)
    const card = screen.getByTestId('import-card-customers')
    await user.click(within(card).getByRole('button', { name: 'Загрузить' }))

    await waitFor(() => {
      expect(screen.getByTestId('import-result-customers')).toHaveTextContent('Создано: 775')
    })
    expect(screen.getByTestId('import-result-customers')).toHaveTextContent('пропущено дублей: 10')
  })

  it('показывает «Показать ещё» и догружает журнал загрузок', async () => {
    const user = userEvent.setup()
    const sessions = Array.from({ length: 30 }, (_, index) => ({
      ...SESSION,
      id: `s-${index}`,
      file_name: `Файл ${index}.xlsx`,
    }))
    mockApi({
      '/api/v1/imports/kinds': { body: KINDS },
      '/api/v1/imports': {
        handler: (url) => ({
          body: sessions.slice(0, Number(query(url).get('limit') ?? 20)),
        }),
      },
    })
    render(<ImportsPage user={SALES} />)

    expect(await screen.findByTestId('imports-shown')).toHaveTextContent(
      'Показаны последние 20 загрузок',
    )
    await user.click(screen.getByRole('button', { name: 'Показать ещё 20' }))
    await waitFor(() =>
      expect(screen.getByTestId('imports-journal')).toHaveTextContent('Файл 25.xlsx'),
    )
  })
})
