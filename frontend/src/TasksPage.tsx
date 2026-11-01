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
  type Role,
  type SessionUser,
  type Task,
  type TaskAssignee,
  type TaskDetail,
  type TaskPriority,
  type TaskStep,
  taskFileUrl,
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

/** Кто ставит задачи: коммерческий и исполнительный директора. */
const CREATOR_ROLES: Role[] = ['commercial_director', 'executive_director']

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

/** С какого дня может начаться следующий этап и когда он должен закончиться. */
function nextStepWindow(task: Task, steps: TaskStep[]): { start: string; due: string } {
  const last = steps[steps.length - 1]
  const start = last ? addDaysIso(last.due_date, 1) : task.start_date
  return { start: start < task.start_date ? task.start_date : start, due: task.due_date }
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

  const canCreate = CREATOR_ROLES.includes(user.role)

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
    const frame = requestAnimationFrame(() => {
      element.scrollLeft = Math.max(0, dayOffset(today, gantt) * DAY_WIDTH - 160)
      centered.current = true
    })
    return () => cancelAnimationFrame(frame)
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
            Задачи коммерческого отдела: цвет — приоритет, заливка — готовность, красная рамка —
            просрочка.
          </p>
        </div>
        {canCreate ? (
          <div className="task-toolbar">
            <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
              ＋ Новая задача
            </button>
          </div>
        ) : null}
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
          <p>
            {canCreate
              ? 'Задач пока нет — поставьте первую.'
              : 'Вам пока не поставили ни одной задачи.'}
          </p>
          {canCreate ? (
            <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
              ＋ Новая задача
            </button>
          ) : null}
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
                                  <span
                                    className={
                                      step.is_done ? 'gantt-step-done' : 'gantt-step-title'
                                    }
                                  >
                                    {step.title}
                                  </span>
                                  {step.needs_report ? (
                                    <span className="gantt-overdue">нужен отчёт</span>
                                  ) : null}
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
                                      step.needs_report ? 'overdue' : '',
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
  onCancel,
  onCreated,
}: {
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
        setAssigneeId((current) => current || rows[0]?.id || '')
      })
      .catch((err) => setError(errorMessage(err)))
  }, [])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!title.trim()) {
      setError('Название задачи обязательно')
      return
    }
    if (!assigneeId) {
      setError('Выберите исполнителя')
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
        assignee_id: assigneeId,
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
  const [reportStep, setReportStep] = useState('')
  const [reportFiles, setReportFiles] = useState<File[]>([])
  const [stepTitle, setStepTitle] = useState('')
  const [stepStart, setStepStart] = useState('')
  const [stepDue, setStepDue] = useState('')

  const load = useCallback(async () => {
    try {
      const row = await fetchTask(taskId)
      setTask(row)
      const suggestion = nextStepWindow(row, row.steps)
      setStepStart(suggestion.start)
      setStepDue(suggestion.due)
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

  const isClosed = task.status === 'done' || task.status === 'cancelled'
  const openSteps = task.steps.filter((step) => !step.is_done)
  const chosenStep = task.steps.find((step) => step.id === reportStep) ?? null
  const stepWindow = nextStepWindow(task, task.steps)
  const canAddStep = stepWindow.start <= task.due_date

  /** Быстрый отчёт по этапу: выбираем этап в форме и уводим к ней. */
  const reportOnStep = (step: TaskStep) => {
    setReportKind('interim')
    setReportStep(step.id)
    const form = document.querySelector('.task-report-form')
    form?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

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
        kind: reportStep ? 'interim' : reportKind,
        text: reportText.trim(),
        progress: reportStep ? 0 : reportKind === 'final' ? 100 : Number(reportProgress),
        step_id: reportStep || null,
      })
      const fresh = updated.reports[updated.reports.length - 1]
      if (fresh) {
        for (const file of reportFiles) {
          await uploadTaskReportFile(task.id, fresh.id, file)
        }
      }
      setReportText('')
      setReportFiles([])
      setReportStep('')
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
        {task.actions.can_change_status && task.status === 'new' ? (
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
        {task.actions.can_change_status && task.status === 'postponed' ? (
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={() => run(() => changeTaskStatus(task.id, 'resume'))}
          >
            Возобновить
          </button>
        ) : null}
        {task.actions.can_edit ? (
          <button
            type="button"
            className="btn-link danger"
            disabled={busy}
            onClick={() => run(() => changeTaskStatus(task.id, 'cancel'))}
          >
            Отозвать задачу
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
      {task.steps.length === 0 ? (
        <p className="hint">Этапов нет — задача идёт одной полосой.</p>
      ) : null}
      <ul className="task-steps">
        {task.steps.map((step) => (
          <li key={step.id} className="task-step">
            <span className={step.is_done ? 'gantt-step-done' : ''}>{step.title}</span>
            <span className="hint">
              {ruDate(step.start_date)} — {ruDate(step.due_date)}
            </span>
            {step.is_done ? <span className="task-kind final">Отчёт получен</span> : null}
            {step.needs_report ? <span className="gantt-overdue">нужен отчёт</span> : null}
            {task.actions.can_report && !step.is_done ? (
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => reportOnStep(step)}
              >
                Отчёт по этапу
              </button>
            ) : null}
            {task.actions.can_edit && !step.has_report ? (
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

      {task.actions.can_edit && canAddStep ? (
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
            min={stepWindow.start}
            max={task.due_date}
            onChange={(event) => setStepStart(event.target.value)}
          />
          <input
            type="date"
            value={stepDue}
            min={stepStart || stepWindow.start}
            max={task.due_date}
            onChange={(event) => setStepDue(event.target.value)}
          />
          <button type="submit" className="btn-link" disabled={busy}>
            Добавить этап
          </button>
        </form>
      ) : null}
      {task.actions.can_edit && !canAddStep ? (
        <p className="hint">
          Свободных сроков в задаче не осталось: следующий этап не помещается до{' '}
          {ruDate(task.due_date)}. Сдвиньте срок задачи или поправьте этапы.
        </p>
      ) : null}
      {task.actions.can_edit && canAddStep ? (
        <p className="hint">
          Этапы идут по порядку: следующий начинается не раньше{' '}
          {ruDate(addDaysIso(stepStart ?? task.start_date, 0))}, а последний заканчивается не позже{' '}
          {ruDate(task.due_date)}. Этап закрывается промежуточным отчётом исполнителя.
        </p>
      ) : null}

      <h2 className="section-title">Отчёты</h2>
      {task.reports.length === 0 ? <p className="hint">Отчётов пока нет.</p> : null}
      <ul className="task-reports">
        {task.reports.map((report) => (
          <li key={report.id} className="task-report">
            <div className="task-report-head">
              <span className={`task-kind ${report.kind}`}>{report.kind_title}</span>
              {report.step_title ? (
                <span className="task-kind">Этап: {report.step_title}</span>
              ) : null}
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
              Этап
              <select
                value={reportStep}
                onChange={(event) => {
                  setReportStep(event.target.value)
                  if (event.target.value) setReportKind('interim')
                }}
              >
                <option value="">Вся задача</option>
                {openSteps.map((step) => (
                  <option key={step.id} value={step.id}>
                    {step.title} (до {shortDate(step.due_date)})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Вид отчёта
              <select
                value={chosenStep ? 'interim' : reportKind}
                disabled={Boolean(chosenStep)}
                onChange={(event) => setReportKind(event.target.value as 'interim' | 'final')}
              >
                <option value="interim">Промежуточный</option>
                <option value="final">Финальный — закрыть задачу</option>
              </select>
            </label>
            {chosenStep ? (
              <div className="field">
                <span>Готовность</span>
                <span className="hint">посчитается по закрытым этапам</span>
              </div>
            ) : (
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
            )}
          </div>
          <label>
            Что сделано
            <textarea
              value={reportText}
              onChange={(event) => setReportText(event.target.value)}
              rows={3}
              placeholder={
                chosenStep
                  ? `Итог этапа «${chosenStep.title}»`
                  : 'Результат, что сделано, что мешает'
              }
            />
          </label>
          {chosenStep ? (
            <p className="hint">
              Отчёт по этапу закроет его; следующий этап закрывается своим отчётом.
            </p>
          ) : null}
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
              {chosenStep
                ? 'Закрыть этап отчётом'
                : reportKind === 'final'
                  ? 'Закрыть задачу'
                  : 'Отправить отчёт'}
            </button>
          </div>
        </form>
      ) : null}

      {isClosed ? <p className="hint">Задача закрыта: отчёты и файлы только читаются.</p> : null}
    </section>
  )
}
