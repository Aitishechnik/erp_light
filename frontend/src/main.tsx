import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './index.css'
import { applyTheme, readTheme } from './theme'

// Тему ставим до первого рендера, иначе на секунду мигнёт светлый фон.
applyTheme(readTheme())

const root = document.getElementById('root')
if (root === null) throw new Error('Не найден элемент #root')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
