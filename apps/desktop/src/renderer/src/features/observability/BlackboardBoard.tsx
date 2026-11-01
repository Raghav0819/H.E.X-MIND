import { useEffect, useState } from 'react'

import { EmptyState } from '../../components/Panel'
import type { AgentEvent } from '../../generated/events'
import type { Task } from '../../lib/api'
import { deriveClaimLog, leaseSecondsLeft } from './derive'

const COLUMNS: { id: string; title: string; statuses: string[] }[] = [
  { id: 'pending', title: 'Pending', statuses: ['pending'] },
  { id: 'claimed', title: 'Claimed', statuses: ['claimed'] },
  { id: 'running', title: 'Running', statuses: ['running'] },
  { id: 'review', title: 'Review', statuses: ['review', 'changes_requested'] },
  { id: 'completed', title: 'Completed', statuses: ['completed'] },
  { id: 'stopped', title: 'Blocked / failed', statuses: ['blocked', 'failed', 'cancelled'] }
]

interface Props {
  tasks: Task[]
  events: AgentEvent[]
}

/** Criterion 1: the shared Blackboard, live. Columns are the tasks' real statuses. */
export function BlackboardBoard({ tasks, events }: Props) {
  const now = useNow(1000)
  const titles = new Map(tasks.map((t) => [t.id, t.title]))
  const log = deriveClaimLog(events)

  if (tasks.length === 0) {
    return <EmptyState title="The Blackboard is empty">Tasks appear here when the Planner posts them.</EmptyState>
  }

  return (
    <div className="obs-blackboard">
      <div className="board" role="list" aria-label="Blackboard tasks by status">
        {COLUMNS.map((column) => {
          const items = tasks.filter((t) => column.statuses.includes(t.status))
          return (
            <section key={column.id} className="board__column" aria-label={column.title}>
              <header className="board__column-header">
                <span>{column.title}</span>
                <span className="board__count">{items.length}</span>
              </header>
              {items.map((task) => {
                const lease = leaseSecondsLeft(task.lease_expires_at, now)
                const open = !['completed', 'blocked', 'failed', 'cancelled'].includes(task.status)
                return (
                  <article key={task.id} className="task-card" role="listitem" data-status={task.status}>
                    <div className="task-card__title" title={task.description}>
                      {task.title}
                    </div>
                    <div className="task-card__meta">
                      <span className="task-status" data-status={task.status}>
                        {task.status}
                      </span>
                      <span className="mono">{task.claimed_by ?? 'unclaimed'}</span>
                      <span className="mono" title="Attempts used / allowed">
                        {task.attempts}/{task.max_attempts}
                      </span>
                    </div>
                    {open && lease !== null && (
                      <div className="task-card__lease mono" title="Worker lease: the task returns to pending if it is not renewed">
                        lease {formatLease(lease)}
                      </div>
                    )}
                    {task.target_files.length > 0 && (
                      <div className="task-card__files mono">{task.target_files.join(', ')}</div>
                    )}
                    {task.depends_on.length > 0 && (
                      <div className="task-card__deps">
                        waits for {task.depends_on.map((id) => titles.get(id) ?? id.slice(0, 8)).join(', ')}
                      </div>
                    )}
                  </article>
                )
              })}
            </section>
          )
        })}
      </div>

      <section className="obs-section" aria-label="Claim log">
        <h3 className="obs-section__title">Claim log</h3>
        <table className="events-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Time</th>
              <th scope="col">Action</th>
              <th scope="col">By</th>
              <th scope="col">Task</th>
              <th scope="col">Details</th>
            </tr>
          </thead>
          <tbody>
            {log.map((entry) => (
              <tr key={entry.seq}>
                <td className="mono">{entry.seq}</td>
                <td className="mono">{new Date(entry.ts).toLocaleTimeString()}</td>
                <td className="mono">{entry.action}</td>
                <td className="mono">{entry.worker ?? '—'}</td>
                <td>{entry.taskId ? (titles.get(entry.taskId) ?? entry.taskId.slice(0, 8)) : '—'}</td>
                <td className="events-table__details">{entry.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function formatLease(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}
