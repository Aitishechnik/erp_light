import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  addTaskReport,
  addTaskStep,
  changeTaskStatus,
  createTask,
  deleteTask,
  deleteTaskReportFile,
  deleteTaskStep,
  errorMessage,
  fetchTask,
  fetchTaskAssignees,
  fetchTasks,
  type SessionUser,
  type Task,
  type TaskAssignee,
  type TaskDetail,
  type TaskPriority,
  taskFileUrl,
  updateTaskStep,
  uploadTaskReportFile,
} from './api'
import {
  barGeometry,
  buildWindow,
  dayOffset,
  monthSpans,
  shortDate,
  windowDays,
} from './tasksGantt'

/** Ширина левой колонки с названиями задач и ширина одного дня шкалы. */
const LABEL_WIDTH = 372
const DAY_WIDTH = 26

const DIRECTOR_ROLES: SessionUser['role'][] = [
  'commercial_director',
  'purchase_director',
  'executive_director',
]

const PRIORITIES: { value: TaskPriority; title: string }[] = [
  { value: 'green', title: 'Низкий' },
  { value: 'yellow', title: 'Обычный' },
  { value: 'red', title: 'Высокий' },
]

const STATUS_OPTIONS = [
  { value: '', title: 'Все статусы' },
  { value: 'new', title: 'Новая' },
  { value: 'in_progress', title: 'В работе' },
  { value: 'postponed', title: 'Отложена' },
  { value: 'done', title: 'Выполнена' },
  { value: 'cancelled', title: 'Отменена' },
]

function todayIso(): string {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

function addDaysIso(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function ruDate(value: string): string {
  return `${value.slice(8, 10)}.${value.slice(5, 7)}.${value.slice(0, 4)}`
}

function ruTime(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  return `${Math.max(1, Math.round(bytes / 1024))} КБ`
}

export function TasksPage({ user, focus }: { user: SessionUser; focus: string[] }) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [onlyMine, setOnlyMine] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')
  const [onlyOverdue, setOnlyOverdue] = useState(false)
  const [openId, setOpenId] = useState<string | null>(focus[0] ?? null)
  const [expanded, setExpanded] = useState<string[]>([])
  const [creating, setCreating] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const centered = useRef(false)

  const isDirector = DIRECTOR_ROLES.includes(user.role)

  const loadTasks = useCallback(async () => {
    try {
      const rows = await fetchTasks({
        mine: onlyMine,
        status: statusFilter || undefined,
        priority: priorityFilter || undefined,
        overdue: onlyOverdue,
      })
      setTasks(rows)
      setError('')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [onlyMine, statusFilter, priorityFilter, onlyOverdue])

  useEffect(() => {
    setLoading(true)
    void loadTasks()
  }, [loadTasks])

  useEffect(() => {
    setOpenId(focus[0] ?? null)
  }, [focus])

  const reload = useCallback(() => {
    void loadTasks()
  }, [loadTasks])

  const toggleExpanded = (taskId: string) => {
    setExpanded((rows) =>
      rows.includes(taskId) ? rows.filter((id) => id !== taskId) : [...rows, taskId],
    )
  }

  const openTask = (taskId: string) => {
    window.location.hash = `#/tasks/${taskId}`
    setOpenId(taskId)
  }

  const backToList = () => {
    window.location.hash = '#/tasks'
    setOpenId(null)
  }

  const today = todayIso()
  const gantt = useMemo(() => buildWindow(tasks, today), [tasks, today])
  const months = monthSpans(gantt)
  const days = windowDays(gantt)
  const trackWidth = gantt.days * DAY_WIDTH

  // Первый показ — сразу у сегодняшнего дня, а не у начала плана.
  useEffect(() => {
    const element = scrollRef.current
    if (!element || tasks.length === 0 || centered.current) return
    element.scrollLeft = Math.max(0, dayOffset(today, gantt) * DAY_WIDTH - 160)
    centered.current = true
  }, [tasks.length, today, gantt])

  if (openId) {
    return (
      <TaskCard
        taskId={openId}
        onBack={backToList}
        onChanged={reload}
        onDeleted={() => {
          reload()
          backToList()
        }}
      />
    )
  }

  return (
    <section className="tasks-page">
      <div className="page-head">
        <div>
          <h1>Задачи</h1>
          <p className="hint">
            План работ отдела: цвет — приоритет, заливка — готовность, красная рамка — просрочка.
          </p>
        </div>
        <div className="task-toolbar">
          <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
            ＋ Новая задача
          </button>
        </div>
      </div>

      <div className="task-filters">
        <label className="inline-check">
          <input
            type="checkbox"
            checked={onlyMine}
            onChange={(event) => setOnlyMine(event.target.checked)}
          />
          Только мои
        </label>
        <label className="inline-check">
          <input
            type="checkbox"
            checked={onlyOverdue}
            onChange={(event) => setOnlyOverdue(event.target.checked)}
          />
          Просроченные
        </label>
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.title}
            </option>
          ))}
        </select>
        <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
          <option value="">Все приоритеты</option>
          {PRIORITIES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.title}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn-link"
          onClick={() => {
            const element = scrollRef.current
            if (!element) return
            const left = Math.max(0, dayOffset(today, gantt) * DAY_WIDTH - 120)
            element.scrollTo({ left, behavior: 'smooth' })
          }}
        >
          Сегодня
        </button>
        <button
          type="button"
          className="btn-link"
          onClick={() => {
            setOnlyMine(false)
            setOnlyOverdue(false)
            setStatusFilter('')
            setPriorityFilter('')
          }}
        >
          Сбросить
        </button>
      </div>

      {creating ? (
        <NewTaskForm
          user={user}
          onCancel={() => setCreating(false)}
          onCreated={(task) => {
            setCreating(false)
            reload()
            openTask(task.id)
          }}
        />
      ) : null}

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="hint">Загрузка…</p> : null}

      {!loading && tasks.length === 0 ? (
        <div className="task-empty">
          <p>Задач пока нет — поставьте первую.</p>
          <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
            ＋ Новая задача
          </button>
        </div>
      ) : null}

      {tasks.length > 0 ? (
        <div className="gantt" data-testid="gantt">
          <div className="gantt-scroll" ref={scrollRef}>
            <div className="gantt-inner" style={{ width: LABEL_WIDTH + trackWidth }}>
              <div className="gantt-head">
                <div className="gantt-head-label" style={{ width: LABEL_WIDTH }}>
                  Задача
                </div>
                <div className="gantt-head-track" style={{ width: trackWidth }}>
                  <div className="gantt-months">
                    {months.map((month) => (
                      <div
                        key={month.key}
                        className="gantt-month"
                        style={{ width: month.days * DAY_WIDTH }}
                      >
                        {month.label}
                      </div>
                    ))}
                  </div>
                  <div className="gantt-days">
                    {days.map((day) => (
                      <div
                        key={day.iso}
                        className={[
                          'gantt-day',
                          day.isWeekend ? 'is-weekend' : '',
                          day.isMonday ? 'is-monday' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        style={{ width: DAY_WIDTH }}
                      >
                        {day.isMonday ? shortDate(day.iso) : ''}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="gantt-body">
                <div
                  className="gantt-today"
                  style={{ left: LABEL_WIDTH + dayOffset(today, gantt) * DAY_WIDTH }}
                  aria-hidden="true"
                />
                {tasks.map((task) => {
                  const bar = barGeometry(task.start_date, task.due_date, gantt, DAY_WIDTH)
                  const isOpen = expanded.includes(task.id)
                  const canToggle =
                    isDirector || task.assignee_id === user.id || task.created_by_id === user.id
                  return (
                    <div key={task.id}>
                      <div className={`gantt-row priority-${task.priority}`}>
                        <div className="gantt-label" style={{ width: LABEL_WIDTH }}>
                          {task.steps.length > 0 ? (
                            <button
                              type="button"
                              className="gantt-expand"
                              aria-label={isOpen ? 'Свернуть этапы' : 'Показать этапы'}
                              onClick={() => toggleExpanded(task.id)}
                            >
                              {isOpen ? '▾' : '▸'}
                            </button>
                          ) : (
                            <span className="gantt-expand-spacer" aria-hidden="true" />
                          )}
                          <span className={`priority-dot ${task.priority}`} aria-hidden="true" />
                          <div className="gantt-label-main">
                            <button
                              type="button"
                              className="gantt-title"
                              title={task.title}
                              onClick={() => openTask(task.id)}
                            >
                              {task.title}
                            </button>
                            <div className="gantt-meta-line">
                              <span
                                className="gantt-meta"
                                title={`${task.assignee_name} · ${task.start_date} — ${task.due_date}`}
                              >
                                {task.assignee_name} · {shortDate(task.start_date)}–
                                {shortDate(task.due_date)}
                              </span>
                              {task.is_overdue ? (
                                <span className="gantt-overdue">
                                  просрочено на {task.days_overdue} дн.
                                </span>
                              ) : null}
                            </div>
                          </div>
                        </div>
                        <div className="gantt-track" style={{ width: trackWidth }}>
                          <div
                            className={['gantt-bar', task.is_overdue ? 'overdue' : '']
                              .filter(Boolean)
                              .join(' ')}
                            style={{ left: bar.left, width: bar.width }}
                          >
                            <span
                              className="gantt-progress"
                              style={{ width: `${Math.min(100, Math.max(0, task.progress))}%` }}
                            />
                            <span className="gantt-bar-text">
                              {task.progress > 0 ? `${task.progress}%` : task.status_title}
                            </span>
                          </div>
                        </div>
                      </div>

                      {isOpen
                        ? task.steps.map((step) => {
                            const stepBar = barGeometry(
                              step.start_date,
                              step.due_date,
                              gantt,
                              DAY_WIDTH,
                            )
                            return (
                              <div className="gantt-row gantt-row-step" key={step.id}>
                                <div
                                  className="gantt-label gantt-label-step"
                                  style={{ width: LABEL_WIDTH }}
                                >
                                  <span className="gantt-step-pad" />
                                  <label className="gantt-step-check">
                                    <input
                                      type="checkbox"
                                      checked={step.is_done}
                                      disabled={!canToggle}
                                      onChange={async (event) => {
                                        try {
                                          await updateTaskStep(task.id, step.id, {
                                            is_done: event.target.checked,
                                          })
                                          reload()
                                        } catch (err) {
                                          setError(errorMessage(err))
                                        }
                                      }}
                                    />
                                  </label>
                                  <span
                                    className={
                                      step.is_done ? 'gantt-step-done' : 'gantt-step-title'
                                    }
                                  >
                                    {step.title}
                                  </span>
                                  <span className="gantt-meta">
                                    {shortDate(step.start_date)}–{shortDate(step.due_date)}
                                  </span>
                                </div>
                                <div className="gantt-track" style={{ width: trackWidth }}>
                                  <div
                                    className={[
                                      'gantt-bar',
                                      'gantt-bar-step',
                                      step.is_done ? 'done' : '',
                                    ]
                                      .filter(Boolean)
                                      .join(' ')}
                                    style={{ left: stepBar.left, width: stepBar.width }}
                                  />
                                </div>
                              </div>
                            )
                          })
                        : null}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}

function NewTaskForm({
  user,
  onCancel,
  onCreated,
}: {
  user: SessionUser
  onCancel: () => void
  onCreated: (task: TaskDetail) => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('yellow')
  const [startDate, setStartDate] = useState(todayIso())
  const [dueDate, setDueDate] = useState(addDaysIso(todayIso(), 7))
  const [assigneeId, setAssigneeId] = useState('')
  const [people, setPeople] = useState<TaskAssignee[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchTaskAssignees()
      .then((rows) => {
        setPeople(rows)
        setAssigneeId((current) => current || user.id)
      })
      .catch((err) => setError(errorMessage(err)))
  }, [user.id])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!title.trim()) {
      setError('Название задачи обязательно')
      return
    }
    if (dueDate < startDate) {
      setError('Дата окончания раньше даты начала')
      return
    }
    setSaving(true)
    try {
      const created = await createTask({
        title: title.trim(),
        description: description.trim() || null,
        priority,
        start_date: startDate,
        due_date: dueDate,
        assignee_id: assigneeId || null,
      })
      onCreated(created)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="task-form" onSubmit={submit}>
      <h2>Новая задача</h2>
      <label>
        Название
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Что нужно сделать"
          maxLength={255}
        />
      </label>
      <label>
        Описание
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={2}
          placeholder="Подробности, ожидаемый результат"
        />
      </label>
      <div className="task-form-row">
        <div className="field">
          <span>Приоритет</span>
          <div className="priority-picker">
            {PRIORITIES.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`priority-chip ${option.value}${priority === option.value ? ' active' : ''}`}
                aria-pressed={priority === option.value}
                onClick={() => setPriority(option.value)}
              >
                {option.title}
              </button>
            ))}
          </div>
        </div>
        <label>
          Исполнитель
          <select value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)}>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.full_name} — {person.role_title}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="task-form-row">
        <label>
          Начало
          <input
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
          />
        </label>
        <label>
          Окончание
          <input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} />
        </label>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <div className="task-form-actions">
        <button type="submit" className="btn-primary" disabled={saving}>
          Поставить задачу
        </button>
        <button type="button" className="btn-link" onClick={onCancel}>
          Отмена
        </button>
      </div>
    </form>
  )
}

function TaskCard({
  taskId,
  onBack,
  onChanged,
  onDeleted,
}: {
  taskId: string
  onBack: () => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reportKind, setReportKind] = useState<'interim' | 'final'>('interim')
  const [reportText, setReportText] = useState('')
  const [reportProgress, setReportProgress] = useState('50')
  const [reportFiles, setReportFiles] = useState<File[]>([])
  const [stepTitle, setStepTitle] = useState('')
  const [stepStart, setStepStart] = useState('')
  const [stepDue, setStepDue] = useState('')

  const load = useCallback(async () => {
    try {
      const row = await fetchTask(taskId)
      setTask(row)
      setStepStart(row.start_date)
      setStepDue(row.due_date)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [taskId])

  useEffect(() => {
    void load()
  }, [load])

  /** Общая обёртка: выполняем действие, обновляем карточку и список. */
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await action()
      await load()
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!task) {
    return (
      <section className="tasks-page">
        <button type="button" className="btn-link" onClick={onBack}>
          ← Все задачи
        </button>
        {error ? <p className="error">{error}</p> : <p className="hint">Загрузка…</p>}
      </section>
    )
  }

  const steps = task.steps
  const isClosed = task.status === 'done' || task.status === 'cancelled'

  const addReport = async (event: FormEvent) => {
    event.preventDefault()
    if (reportText.trim().length < 3) {
      setError('Опишите, что сделано: не короче 3 символов')
      return
    }
    setBusy(true)
    setError('')
    try {
      const updated = await addTaskReport(task.id, {
        kind: reportKind,
        text: reportText.trim(),
        progress: reportKind === 'final' ? 100 : Number(reportProgress),
      })
      const fresh = updated.reports[updated.reports.length - 1]
      if (fresh) {
        for (const file of reportFiles) {
          await uploadTaskReportFile(task.id, fresh.id, file)
        }
      }
      setReportText('')
      setReportFiles([])
      await load()
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="tasks-page">
      <button type="button" className="btn-link" onClick={onBack}>
        ← Все задачи
      </button>

      <div className="task-card-head">
        <div>
          <h1>{task.title}</h1>
          <p className="hint">
            Исполнитель: {task.assignee_name} · Постановщик: {task.created_by_name} · Срок:{' '}
            {ruDate(task.start_date)} — {ruDate(task.due_date)}
          </p>
        </div>
        <div className="task-card-badges">
          <span className={`priority-chip ${task.priority}`}>{task.priority_title}</span>
          <span className={`task-status status-${task.status}`}>{task.status_title}</span>
          {task.is_overdue ? (
            <span className="gantt-overdue">просрочено на {task.days_overdue} дн.</span>
          ) : null}
        </div>
      </div>

      <div className="task-progress-line">
        <span>Готовность: {task.progress}%</span>
        <div className="task-progress-bar">
          <span style={{ width: `${task.progress}%` }} />
        </div>
      </div>

      {task.description ? <p className="task-description">{task.description}</p> : null}

      {error ? <p className="error">{error}</p> : null}

      <div className="task-actions">
        {task.actions.can_change_status &&
        (task.status === 'new' || task.status === 'postponed') ? (
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={() => run(() => changeTaskStatus(task.id, 'start'))}
          >
            Взять в работу
          </button>
        ) : null}
        {task.actions.can_change_status && task.status === 'in_progress' ? (
          <button
            type="button"
            className="btn-link"
            disabled={busy}
            onClick={() => run(() => changeTaskStatus(task.id, 'postpone'))}
          >
            Отложить
          </button>
        ) : null}
        {task.actions.can_change_status ? (
          <button
            type="button"
            className="btn-link"
            disabled={busy}
            onClick={() => run(() => changeTaskStatus(task.id, 'cancel'))}
          >
            Отменить задачу
          </button>
        ) : null}
        {task.actions.can_reopen ? (
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={() => run(() => changeTaskStatus(task.id, 'reopen'))}
          >
            Вернуть в работу
          </button>
        ) : null}
        {task.actions.can_delete ? (
          <button
            type="button"
            className="btn-link danger"
            disabled={busy}
            onClick={() => {
              if (window.confirm('Удалить задачу?')) {
                void deleteTask(task.id)
                  .then(onDeleted)
                  .catch((err) => setError(errorMessage(err)))
              }
            }}
          >
            Удалить
          </button>
        ) : null}
      </div>

      <h2 className="section-title">Этапы</h2>
      {steps.length === 0 ? <p className="hint">Этапов нет — задача идёт одной полосой.</p> : null}
      <ul className="task-steps">
        {steps.map((step) => (
          <li key={step.id} className="task-step">
            <label className="inline-check">
              <input
                type="checkbox"
                checked={step.is_done}
                disabled={busy || isClosed}
                onChange={(event) =>
                  run(() => updateTaskStep(task.id, step.id, { is_done: event.target.checked }))
                }
              />
              <span className={step.is_done ? 'gantt-step-done' : ''}>{step.title}</span>
            </label>
            <span className="hint">
              {ruDate(step.start_date)} — {ruDate(step.due_date)}
            </span>
            {task.actions.can_edit ? (
              <button
                type="button"
                className="btn-link danger"
                disabled={busy}
                onClick={() => run(() => deleteTaskStep(task.id, step.id))}
              >
                Удалить этап
              </button>
            ) : null}
          </li>
        ))}
      </ul>

      {task.actions.can_edit ? (
        <form
          className="task-step-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (!stepTitle.trim() || !stepStart || !stepDue) {
              setError('Этап: название и обе даты обязательны')
              return
            }
            void run(async () => {
              await addTaskStep(task.id, {
                title: stepTitle.trim(),
                start_date: stepStart,
                due_date: stepDue,
              })
              setStepTitle('')
            })
          }}
        >
          <input
            value={stepTitle}
            onChange={(event) => setStepTitle(event.target.value)}
            placeholder="Название этапа"
            maxLength={255}
          />
          <input
            type="date"
            value={stepStart}
            onChange={(event) => setStepStart(event.target.value)}
          />
          <input type="date" value={stepDue} onChange={(event) => setStepDue(event.target.value)} />
          <button type="submit" className="btn-link" disabled={busy}>
            Добавить этап
          </button>
        </form>
      ) : null}

      <h2 className="section-title">Отчёты</h2>
      {task.reports.length === 0 ? <p className="hint">Отчётов пока нет.</p> : null}
      <ul className="task-reports">
        {task.reports.map((report) => (
          <li key={report.id} className="task-report">
            <div className="task-report-head">
              <span className={`task-kind ${report.kind}`}>{report.kind_title}</span>
              <span className="hint">
                {report.author_name} · {ruTime(report.created_at)} · готовность {report.progress}%
              </span>
            </div>
            <p className="task-report-text">{report.text}</p>
            {report.files.length > 0 ? (
              <ul className="task-files">
                {report.files.map((file) => (
                  <li key={file.id}>
                    <a href={taskFileUrl(task.id, report.id, file.id)} download>
                      {file.original_name}
                    </a>
                    <span className="hint"> · {fileSize(file.size_bytes)}</span>
                    {task.actions.can_report ? (
                      <button
                        type="button"
                        className="btn-link danger"
                        disabled={busy}
                        onClick={() => run(() => deleteTaskReportFile(task.id, report.id, file.id))}
                      >
                        убрать
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>

      {task.actions.can_report ? (
        <form className="task-report-form" onSubmit={addReport}>
          <h3>Добавить отчёт</h3>
          <div className="task-form-row">
            <label>
              Вид отчёта
              <select
                value={reportKind}
                onChange={(event) => setReportKind(event.target.value as 'interim' | 'final')}
              >
                <option value="interim">Промежуточный</option>
                <option value="final">Финальный — закрыть задачу</option>
              </select>
            </label>
            <label>
              Готовность, %
              <input
                type="number"
                min={0}
                max={100}
                value={reportProgress}
                disabled={reportKind === 'final'}
                onChange={(event) => setReportProgress(event.target.value)}
              />
            </label>
          </div>
          <label>
            Что сделано
            <textarea
              value={reportText}
              onChange={(event) => setReportText(event.target.value)}
              rows={3}
              placeholder="Результат, что сделано, что мешает"
            />
          </label>
          <label>
            Файлы (до 10 МБ каждый)
            <input
              type="file"
              multiple
              onChange={(event) => setReportFiles(Array.from(event.target.files ?? []))}
            />
          </label>
          <div className="task-form-actions">
            <button type="submit" className="btn-primary" disabled={busy}>
              {reportKind === 'final' ? 'Закрыть задачу' : 'Отправить отчёт'}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  )
}
