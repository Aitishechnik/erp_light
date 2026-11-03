import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Counterparty, ImportKind, ImportSession, Product, Role, SessionUser } from './api'
import { mockApi } from './apiMock'
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

describe('CounterpartiesPage', () => {
  it('показывает роли контрагента; отключённые скрыты до запроса', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/counterparties': { body: COUNTERPARTIES } })
    render(<CounterpartiesPage />)

    expect(await screen.findByTestId('counterparties-table')).toHaveTextContent('ООО Ромашка')
    expect(screen.getByTestId('counterparties-count')).toHaveTextContent('1')
    expect(screen.queryByText('Комус')).not.toBeInTheDocument()

    await user.click(screen.getByLabelText('показывать отключённых'))
    expect(screen.getByTestId('counterparties-count')).toHaveTextContent('2')
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
    many.push({ ...base, id: 'target-id', name: 'ООО Поздний' })
    mockApi({ '/api/v1/counterparties': { body: many } })
    render(<CounterpartiesPage focusId="target-id" />)

    const table = await screen.findByTestId('counterparties-table')
    const firstRow = within(table).getAllByRole('row')[1]
    expect(firstRow).toHaveClass('focus-row')
    expect(firstRow).toHaveTextContent('ООО Поздний')
  })

  it('фильтрует по поиску', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/counterparties': { body: COUNTERPARTIES } })
    render(<CounterpartiesPage />)

    await screen.findByTestId('counterparties-table')
    await user.type(screen.getByLabelText('Поиск по наименованию'), 'ромашка')

    expect(screen.getByTestId('counterparties-count')).toHaveTextContent('1')
    expect(screen.getByText('ООО Ромашка')).toBeInTheDocument()

    await user.clear(screen.getByLabelText('Поиск по наименованию'))
    await user.type(screen.getByLabelText('Поиск по наименованию'), 'нетакого')
    expect(screen.getByTestId('counterparties-count')).toHaveTextContent('0')
  })

  it('добавляет контрагента с признаками', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/counterparties': { body: COUNTERPARTIES } })
    render(<CounterpartiesPage />)

    await screen.findByTestId('counterparties-table')
    await user.type(screen.getByLabelText('Наименование контрагента'), 'Новый Поставщик')
    await user.click(screen.getByLabelText('импортный поставщик'))
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    const posted = bodies().some((body) => body.includes('"is_import_supplier":true'))
    expect(posted).toBe(true)
  })

  it('показывает ошибку при дубле наименования', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/v1/counterparties': { status: 409, body: { detail: 'Контрагент «Комус» уже есть' } },
    })
    render(<CounterpartiesPage />)

    await screen.findByTestId('counterparties-table')
    await user.type(screen.getByLabelText('Наименование контрагента'), 'Комус')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('уже есть')
  })

  it('администратор может менять контрагентов', async () => {
    mockApi({ '/api/v1/counterparties': { body: COUNTERPARTIES } })
    render(<CounterpartiesPage user={ADMIN} />)

    await screen.findByTestId('counterparties-table')
    expect(screen.getByLabelText('Наименование контрагента')).toBeInTheDocument()
    expect(screen.getByLabelText('Менеджер клиента ООО Ромашка')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Отключить' })).toBeInTheDocument()
  })
})

describe('NomenclaturePage', () => {
  it('фильтрует по виду и ищет по коду', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/products': { body: PRODUCTS } })
    render(<NomenclaturePage />)

    expect(await screen.findByTestId('products-table')).toHaveTextContent('Антиоксидант')
    // Отключённые позиции по умолчанию скрыты.
    expect(screen.getByTestId('products-count')).toHaveTextContent('1')
    await user.click(screen.getByLabelText('показывать отключённые'))
    expect(screen.getByTestId('products-count')).toHaveTextContent('2')

    await user.selectOptions(screen.getByLabelText('Фильтр по виду'), 'raw')
    expect(screen.getByTestId('products-count')).toHaveTextContent('1')
    expect(screen.getByText('Абрикос цукаты')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Фильтр по виду'), '')
    await user.type(screen.getByLabelText('Поиск по коду или наименованию'), 'ТОВ3948')
    expect(screen.getByTestId('products-count')).toHaveTextContent('1')
  })

  it('заводит позицию номенклатуры', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/v1/products': { body: PRODUCTS } })
    render(<NomenclaturePage />)

    await screen.findByTestId('products-table')
    await user.type(screen.getByLabelText('Код'), 'ТОВ900')
    await user.type(screen.getByLabelText('Наименование'), 'Грунтовка')
    await user.type(screen.getByLabelText('Единица'), 'л')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    const posted = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.some((call) =>
      JSON.stringify(call[1] ?? {}).includes('ТОВ900'),
    )
    expect(posted).toBe(true)
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
})
