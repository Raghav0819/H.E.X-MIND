import { useEffect, useState } from 'react'

import { EmptyState } from '../../components/Panel'
import type { ApiClient, Run } from '../../lib/api'
import { useRunEvents } from '../runs/useRunEvents'
import { useRunTasks } from '../runs/useRunTasks'
import { AgentGrid } from './AgentGrid'
import { BlackboardBoard } from './BlackboardBoard'
import { CallbackStream } from './CallbackStream'
import { PatternTopology } from './PatternTopology'
import { SchemaChecks } from './SchemaChecks'

const TABS = ['Blackboard', 'Agents', 'Callbacks', 'Schema checks', 'Topology'] as const
type Tab = (typeof TABS)[number]

interface Props {
  api: ApiClient
  runId: string | null
}

/** The Observability activity: live views of one run, all derived from recorded data. */
export function ObservabilityView({ api, runId }: Props) {
  const [tab, setTab] = useState<Tab>('Blackboard')
  const { run, events, error } = useRunEvents(api, runId)
  const { tasks } = useRunTasks(api, runId)

  if (!runId) {
    return (
      <EmptyState title="No run selected">Pick a run in the sidebar, or start an Edit request in the chat.</EmptyState>
    )
  }

  return (
    <div className="observability">
      <header className="observability__header">
        <span className="observability__title">{run?.title ?? 'Loading run…'}</span>
        {run && (
          <span className="run-events__status" data-status={run.status}>
            {run.status}
          </span>
        )}
        {run?.strategy && <span className="observability__meta">{run.strategy}</span>}
        <span className="observability__meta">{events.length} events</span>
        {error && (
          <span className="run-events__error" role="alert">
            {error}
          </span>
        )}
      </header>
      <div className="tabs" role="tablist" aria-label="Observability views">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" className="tabs__tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="observability__body" role="tabpanel" aria-label={tab}>
        {tab === 'Blackboard' ? (
          <BlackboardBoard tasks={tasks} events={events} />
        ) : tab === 'Agents' ? (
          <AgentGrid events={events} />
        ) : tab === 'Callbacks' ? (
          <CallbackStream events={events} />
        ) : tab === 'Schema checks' ? (
          <SchemaChecks events={events} />
        ) : (
          <PatternTopology events={events} />
        )}
      </div>
    </div>
  )
}

const RUNS_POLL_MS = 3000

/** Sidebar list of the project's runs, newest first. */
export function RunList({
  api,
  projectId,
  selectedRunId,
  onSelect
}: {
  api: ApiClient
  projectId: string | null
  selectedRunId: string | null
  onSelect: (runId: string) => void
}) {
  const [runs, setRuns] = useState<Run[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRuns([])
    if (!projectId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const list = await api.get<Run[]>('/runs', { project_id: projectId })
        if (cancelled) return
        setRuns(list)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
      if (!cancelled) timer = setTimeout(poll, RUNS_POLL_MS)
    }
    void poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [api, projectId])

  if (!projectId) return <EmptyState title="No workspace open" />
  if (error) return <EmptyState title="Could not load runs">{error}</EmptyState>
  if (runs.length === 0) return <EmptyState title="No runs yet">Edit requests in the chat start runs.</EmptyState>

  return (
    <ul className="run-list" aria-label="Runs">
      {runs.map((run) => (
        <li key={run.id}>
          <button
            type="button"
            className="run-list__item"
            aria-current={run.id === selectedRunId ? 'true' : undefined}
            onClick={() => onSelect(run.id)}
          >
            <span className="run-list__title">{run.title}</span>
            <span className="run-list__meta">
              <span className="run-events__status" data-status={run.status}>
                {run.status}
              </span>
              <span>{new Date(run.created_at).toLocaleString()}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
