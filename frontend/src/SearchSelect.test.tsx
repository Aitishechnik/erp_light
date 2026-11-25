import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { SearchSelect, type SearchSelectOption } from './SearchSelect'

const CLIENTS: SearchSelectOption[] = [
  { value: 'client-1', label: 'ООО Ромашка' },
  { value: 'client-2', label: 'ООО Вектор' },
  { value: 'client-3', label: 'АО Поле' },
]

function Harness({
  options = CLIENTS,
  maxResults,
  wide,
}: {
  options?: SearchSelectOption[]
  maxResults?: number
  wide?: boolean
}) {
  const [value, setValue] = useState('')
  return (
    <div>
      <SearchSelect
        label="Клиент"
        value={value}
        options={options}
        onChange={setValue}
        maxResults={maxResults}
        wide={wide}
      />
      <span data-testid="picked">{value}</span>
    </div>
  )
}

describe('SearchSelect', () => {
  it('фильтрует длинный список по части названия и выбирает вариант', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const input = screen.getByLabelText('Клиент')

    await user.click(input)
    expect(screen.getByRole('option', { name: 'ООО Ромашка' })).toBeInTheDocument()

    await user.type(input, 'век')
    expect(screen.queryByRole('option', { name: 'ООО Ромашка' })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'ООО Вектор' })).toBeInTheDocument()

    await user.keyboard('{Enter}')
    expect(screen.getByTestId('picked')).toHaveTextContent('client-2')
    expect(input).toHaveValue('ООО Вектор')
  })

  it('ищет позицию по коду 1С, а не только по названию', async () => {
    const user = userEvent.setup()
    const products: SearchSelectOption[] = [
      { value: 'p-1', label: 'SKU-1 · Товар 1', keywords: 'SKU-1' },
      { value: 'p-2', label: 'SKU-2 · Изюм', keywords: 'SKU-2' },
    ]
    render(<Harness options={products} />)
    const input = screen.getByLabelText('Клиент')

    await user.click(input)
    await user.type(input, 'sku-2')
    await user.click(screen.getByRole('option', { name: /Изюм/ }))

    expect(screen.getByTestId('picked')).toHaveTextContent('p-2')
  })

  it('для номенклатуры включает широкий режим поля и списка', () => {
    const { container } = render(<Harness wide />)
    expect(container.querySelector('.search-select.wide')).not.toBeNull()
  })

  it('показывает, что список сокращён, и предлагает уточнить запрос', async () => {
    const user = userEvent.setup()
    render(<Harness maxResults={2} />)

    await user.click(screen.getByLabelText('Клиент'))
    expect(screen.getByText('Показано 2 из 3 — уточните запрос')).toBeInTheDocument()
  })
})
