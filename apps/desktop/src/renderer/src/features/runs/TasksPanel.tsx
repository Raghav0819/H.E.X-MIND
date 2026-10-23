import { useEffect, useState } from 'react'

import { EmptyState } from '../../components/Panel'
import { SETTLED_RUN_STATUSES, type ApiClient, type Run, type Task } from '../../lib/api'

const POLL_MS = 1500

interface Props {
  api: ApiClient
  runId: string | null
}

/** The run's Blackboard: every task with its real status, owner and attempts. */
export function TasksPanel({ api, runId }: Props) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setTasks([])
    setError(null)
    if (!runId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const [run, list] = await Promise.all([
          api.get<Run>(`/runs/${runId}`),
          api.get<Task[]>('/tasks', { run_id: runId })
        ])
        if (cancelled) return
        setTasks(list)
        setError(null)
        if (SETTLED_RUN_STATUSES.has(run.status)) return
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
      }
      timer = setTimeout(poll, POLL_MS)
    }
    void poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [api, runId])

  if (!runId) return <EmptyState title="No run selected" />
  if (error) return <EmptyState title="Could not load tasks">{error}</EmptyState>
  if (tasks.length === 0) return <EmptyState title="No tasks yet">The Planner has not created tasks for this run.</EmptyState>

  return (
    <table className="events-table">
      <thead>
        <tr>
          <th scope="col">Task</th>
          <th scope="col">Status</th>
          <th scope="col">Worker</th>
          <th scope="col">Attempts</th>
          <th scope="col">Files</th>
        </tr>
      </thead>
      <tbody>
        {tasks.map((task) => (
          <tr key={task.id}>
            <td title={task.description}>{task.title}</td>
            <td>
              <span className="task-status" data-status={task.status}>
                {task.status}
              </span>
            </td>
            <td className="mono">{task.claimed_by ?? '—'}</td>
            <td className="mono">
              {task.attempts}/{task.max_attempts}
            </td>
            <td className="events-table__details mono">{task.target_files.join(', ') || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
