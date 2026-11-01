import { EmptyState } from '../../components/Panel'
import type { ApiClient } from '../../lib/api'
import { useRunTasks } from './useRunTasks'

interface Props {
  api: ApiClient
  runId: string | null
}

/** The run's Blackboard: every task with its real status, owner and attempts. */
export function TasksPanel({ api, runId }: Props) {
  const { tasks, error } = useRunTasks(api, runId)

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
