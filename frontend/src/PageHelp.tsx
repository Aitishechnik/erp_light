import type { ReactNode } from 'react'

/**
 * Справка у заголовка экрана: длинные пояснения не занимают место на экране,
 * пока пользователь сам их не раскроет. Заменяет серые абзацы в шапках.
 */
export function PageHelp({
  children,
  label = 'Как это работает',
}: {
  children: ReactNode
  label?: string
}) {
  return (
    <details className="page-help">
      <summary>{label}</summary>
      <div className="page-help-body">{children}</div>
    </details>
  )
}
