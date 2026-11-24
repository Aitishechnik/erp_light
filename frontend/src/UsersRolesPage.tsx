import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import {
  type AccessLevel,
  type AccessPayload,
  type AdminUser,
  type BlockRights,
  createAdminUser,
  errorMessage,
  fetchAccess,
  fetchAdminUsers,
  type Role,
  resetAdminPassword,
  saveAccess,
  updateAdminUser,
} from './api'
import { PageHelp } from './PageHelp'

type Tab = 'staff' | 'rights'

type StaffForm = { full_name: string; login: string; password: string; role: Role }

const EMPTY_STAFF: StaffForm = { full_name: '', login: '', password: '', role: 'sales_manager' }

const GROUP_TITLES: Record<string, string> = {
  planning: 'Планирование',
  purchases: 'Закупки',
  catalogs: 'Справочники',
  reports: 'Отчёты',
  tasks: 'Задачи',
  admin: 'Администрирование',
}

const ACTION_ORDER = [
  'view',
  'edit',
  'create',
  'submit',
  'propose',
  'approve',
  'dispatch',
  'delete',
]

function cloneRights(level: AccessLevel): Record<string, BlockRights> {
  return Object.fromEntries(
    Object.entries(level.rights).map(([block, rights]) => [
      block,
      { actions: [...rights.actions], scope: rights.scope },
    ]),
  )
}

function sortActions(actions: string[]): string[] {
  return [...actions].sort((a, b) => {
    const left = ACTION_ORDER.indexOf(a)
    const right = ACTION_ORDER.indexOf(b)
    return (left === -1 ? 99 : left) - (right === -1 ? 99 : right) || a.localeCompare(b)
  })
}

/**
 * «Пользователи и роли»: сотрудники и конструктор прав уровней.
 *
 * Обе вкладки видит только администратор. Админ один: его учётная запись
 * не редактируется отсюда, но пароль себе он сменить может.
 */
export function UsersRolesPage({ user }: { user: { id: string } }) {
  const [tab, setTab] = useState<Tab>('staff')
  const [access, setAccess] = useState<AccessPayload | null>(null)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    try {
      const [nextAccess, nextUsers] = await Promise.all([fetchAccess(), fetchAdminUsers()])
      setAccess(nextAccess)
      setUsers(nextUsers)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const levelTitle = useMemo(() => {
    const map = new Map<string, string>()
    for (const level of access?.levels ?? []) map.set(level.key, level.title)
    map.set('admin', 'Администратор')
    return map
  }, [access])

  return (
    <section>
      <header className="page-head">
        <h1>Пользователи и роли</h1>
        <PageHelp>
          Сотрудники заводятся здесь: логин, пароль и уровень доступа. Уровни — фиксированные, а их
          права собираются во вкладке «Права уровней» и действуют сразу на всех сотрудников уровня.
          Администратор один, его права не редактируются.
        </PageHelp>
      </header>

      <div className="toolbar" role="tablist" aria-label="Разделы страницы">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'staff'}
          className={tab === 'staff' ? 'primary' : 'mini'}
          onClick={() => setTab('staff')}
        >
          Сотрудники
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'rights'}
          className={tab === 'rights' ? 'primary' : 'mini'}
          onClick={() => setTab('rights')}
        >
          Права уровней
        </button>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {notice ? <p className="hint">{notice}</p> : null}

      {tab === 'staff' ? (
        <StaffTab
          users={users}
          meId={user.id}
          levelTitle={levelTitle}
          levels={access?.levels ?? []}
          busy={busy}
          setBusy={setBusy}
          setError={setError}
          setNotice={setNotice}
          reload={reload}
        />
      ) : (
        <RightsTab
          access={access}
          busy={busy}
          setBusy={setBusy}
          setError={setError}
          setNotice={setNotice}
          reload={reload}
        />
      )}
    </section>
  )
}

type StaffProps = {
  users: AdminUser[]
  meId: string
  levelTitle: Map<string, string>
  levels: AccessLevel[]
  busy: boolean
  setBusy: (value: boolean) => void
  setError: (value: string) => void
  setNotice: (value: string) => void
  reload: () => Promise<void>
}

function StaffTab({
  users,
  meId,
  levelTitle,
  levels,
  busy,
  setBusy,
  setError,
  setNotice,
  reload,
}: StaffProps) {
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<StaffForm>(EMPTY_STAFF)
  const [editing, setEditing] = useState<AdminUser | null>(null)
  const [editForm, setEditForm] = useState({
    full_name: '',
    role: 'sales_manager' as Role,
    is_active: true,
  })
  const [passwordFor, setPasswordFor] = useState<AdminUser | null>(null)
  const [password, setPassword] = useState('')

  const needle = search.trim().toLowerCase()
  const filtered = users.filter((row) =>
    needle
      ? row.full_name.toLowerCase().includes(needle) || row.login.toLowerCase().includes(needle)
      : true,
  )

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await createAdminUser(form)
      setCreating(false)
      setForm(EMPTY_STAFF)
      setNotice('Сотрудник заведён')
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (row: AdminUser) => {
    setEditing(row)
    setEditForm({
      full_name: row.full_name,
      role: row.role,
      is_active: row.is_active,
    })
    setError('')
    setNotice('')
  }

  const submitEdit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!editing) return
    setBusy(true)
    setError('')
    try {
      await updateAdminUser(editing.id, editForm)
      setEditing(null)
      setNotice('Изменения сохранены')
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const submitPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!passwordFor) return
    setBusy(true)
    setError('')
    try {
      await resetAdminPassword(passwordFor.id, password)
      setPasswordFor(null)
      setPassword('')
      setNotice('Пароль сменён')
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="toolbar">
        <button type="button" className="primary" onClick={() => setCreating(true)}>
          Добавить сотрудника
        </button>
        <label className="field">
          Поиск
          <input
            aria-label="Поиск сотрудника"
            placeholder="Имя или логин"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Имя</th>
              <th>Логин</th>
              <th>Уровень доступа</th>
              <th>Статус</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.id}>
                <td>{row.full_name}</td>
                <td>{row.login}</td>
                <td>{levelTitle.get(row.role) ?? row.role_title}</td>
                <td>{row.is_active ? 'Работает' : 'Заблокирован'}</td>
                <td className="row-actions">
                  {row.is_admin ? null : (
                    <button type="button" className="mini" onClick={() => startEdit(row)}>
                      Изменить
                    </button>
                  )}
                  <button type="button" className="mini" onClick={() => setPasswordFor(row)}>
                    Пароль
                  </button>
                  {row.id === meId && !row.is_admin ? <span className="hint">это вы</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {creating ? (
        <div className="modal-backdrop">
          <form
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Новый сотрудник"
            onSubmit={submitCreate}
          >
            <h3 className="section-title">Новый сотрудник</h3>
            <label className="field">
              Имя и фамилия
              <input
                aria-label="Имя сотрудника"
                required
                value={form.full_name}
                onChange={(event) => setForm({ ...form, full_name: event.target.value })}
              />
            </label>
            <label className="field">
              Логин
              <input
                aria-label="Логин сотрудника"
                required
                minLength={3}
                autoComplete="off"
                value={form.login}
                onChange={(event) => setForm({ ...form, login: event.target.value })}
              />
            </label>
            <label className="field">
              Пароль
              <input
                aria-label="Пароль сотрудника"
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
              />
            </label>
            <label className="field">
              Уровень доступа
              <select
                aria-label="Уровень доступа"
                value={form.role}
                onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
              >
                {levels.map((level) => (
                  <option key={level.key} value={level.key}>
                    {level.title}
                  </option>
                ))}
              </select>
            </label>
            <footer className="modal-actions">
              <button type="button" className="mini" onClick={() => setCreating(false)}>
                Отмена
              </button>
              <button type="submit" className="primary" disabled={busy}>
                Завести
              </button>
            </footer>
          </form>
        </div>
      ) : null}

      {editing ? (
        <div className="modal-backdrop">
          <form
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={`Изменить ${editing.full_name}`}
            onSubmit={submitEdit}
          >
            <h3 className="section-title">Изменить сотрудника</h3>
            <label className="field">
              Имя и фамилия
              <input
                aria-label="Имя сотрудника"
                required
                value={editForm.full_name}
                onChange={(event) => setEditForm({ ...editForm, full_name: event.target.value })}
              />
            </label>
            <label className="field">
              Уровень доступа
              <select
                aria-label="Уровень доступа"
                value={editForm.role}
                onChange={(event) => setEditForm({ ...editForm, role: event.target.value as Role })}
              >
                {levels.map((level) => (
                  <option key={level.key} value={level.key}>
                    {level.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="field checkbox-field">
              <input
                type="checkbox"
                checked={editForm.is_active}
                onChange={(event) => setEditForm({ ...editForm, is_active: event.target.checked })}
              />
              Работает (снятая галочка блокирует вход)
            </label>
            <footer className="modal-actions">
              <button type="button" className="mini" onClick={() => setEditing(null)}>
                Отмена
              </button>
              <button type="submit" className="primary" disabled={busy}>
                Сохранить
              </button>
            </footer>
          </form>
        </div>
      ) : null}

      {passwordFor ? (
        <div className="modal-backdrop">
          <form
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={`Пароль ${passwordFor.full_name}`}
            onSubmit={submitPassword}
          >
            <h3 className="section-title">Новый пароль: {passwordFor.full_name}</h3>
            <label className="field">
              Пароль (не короче 8 символов)
              <input
                aria-label="Новый пароль"
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <footer className="modal-actions">
              <button type="button" className="mini" onClick={() => setPasswordFor(null)}>
                Отмена
              </button>
              <button type="submit" className="primary" disabled={busy}>
                Сменить пароль
              </button>
            </footer>
          </form>
        </div>
      ) : null}
    </>
  )
}

type RightsProps = {
  access: AccessPayload | null
  busy: boolean
  setBusy: (value: boolean) => void
  setError: (value: string) => void
  setNotice: (value: string) => void
  reload: () => Promise<void>
}

function RightsTab({ access, busy, setBusy, setError, setNotice, reload }: RightsProps) {
  const [selected, setSelected] = useState<string>('sales_manager')
  const [draft, setDraft] = useState<Record<string, BlockRights>>({})
  const [dirty, setDirty] = useState(false)

  const level = access?.levels.find((row) => row.key === selected) ?? null

  useEffect(() => {
    if (level) {
      setDraft(cloneRights(level))
      setDirty(false)
    }
  }, [level])

  const groups = useMemo(() => {
    const result: { key: string; blocks: NonNullable<AccessPayload['blocks']> }[] = []
    for (const block of access?.blocks ?? []) {
      const group = result.find((row) => row.key === block.group)
      if (group) group.blocks.push(block)
      else result.push({ key: block.group, blocks: [block] })
    }
    return result
  }, [access])

  const toggle = (block: string, action: string) => {
    setDraft((current) => {
      const rights = current[block] ?? { actions: [], scope: 'all' as const }
      const actions = rights.actions.includes(action)
        ? rights.actions.filter((row) => row !== action)
        : [...rights.actions, action]
      return { ...current, [block]: { ...rights, actions: sortActions(actions) } }
    })
    setDirty(true)
    setNotice('')
  }

  const setScope = (block: string, scope: 'own' | 'all') => {
    setDraft((current) => ({
      ...current,
      [block]: { ...(current[block] ?? { actions: [], scope }), scope },
    }))
    setDirty(true)
    setNotice('')
  }

  const save = async () => {
    if (!level) return
    setBusy(true)
    setError('')
    try {
      await saveAccess(level.key, draft)
      setDirty(false)
      setNotice(`Права уровня «${level.title}» сохранены`)
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!access) return <p className="hint">Загрузка прав…</p>

  return (
    <div className="access-layout">
      <nav className="access-levels" aria-label="Уровни доступа">
        {access.levels.map((row) => (
          <button
            key={row.key}
            type="button"
            className={row.key === selected ? 'primary' : 'mini'}
            onClick={() => {
              if (dirty && !window.confirm('Несохранённые изменения будут потеряны. Продолжить?')) {
                return
              }
              setSelected(row.key)
            }}
          >
            {row.title}
          </button>
        ))}
      </nav>

      <div className="access-blocks">
        {level ? <p className="hint">{level.description}</p> : null}
        {groups.map((group) => (
          <section key={group.key} className="access-group">
            <h3 className="section-title">{GROUP_TITLES[group.key] ?? group.key}</h3>
            {group.blocks.map((block) => {
              const rights = draft[block.key] ?? { actions: [], scope: 'all' as const }
              return (
                <div key={block.key} className="access-block">
                  <div className="access-block-head">
                    <strong>{block.title}</strong>
                    {block.scoped ? (
                      <label className="field">
                        Охват
                        <select
                          aria-label={`Охват: ${block.title}`}
                          value={rights.scope}
                          onChange={(event) =>
                            setScope(block.key, event.target.value as 'own' | 'all')
                          }
                        >
                          <option value="own">только свои</option>
                          <option value="all">все</option>
                        </select>
                      </label>
                    ) : null}
                  </div>
                  <div className="access-actions">
                    {block.actions.map((action) => (
                      <label key={action.key} className="access-action">
                        <input
                          type="checkbox"
                          aria-label={`${block.title}: ${action.title}`}
                          checked={rights.actions.includes(action.key)}
                          onChange={() => toggle(block.key, action.key)}
                        />
                        {action.title}
                      </label>
                    ))}
                  </div>
                </div>
              )
            })}
          </section>
        ))}
        <div className="toolbar">
          <button
            type="button"
            className="primary"
            disabled={busy || !dirty}
            onClick={() => void save()}
          >
            Сохранить права
          </button>
          <span className="hint">Изменения действуют сразу на всех сотрудников этого уровня.</span>
        </div>
      </div>
    </div>
  )
}
