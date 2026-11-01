import { useMemo, useState } from 'react'

import { EmptyState } from '../../components/Panel'
import type { AgentEvent } from '../../generated/events'
import { formatMs } from '../runs/events'
import { callbackEvents, callbackHook, type CallbackEvent, type Framework } from './derive'
import { FrameworkBadge } from './FrameworkBadge'

const MAX_ROWS = 500

/** Criterion 5: every ADK and CrewAI callback the TelemetryHub received, newest first. */
export function CallbackStream({ events }: { events: AgentEvent[] }) {
  const [framework, setFramework] = useState<Framework | 'all'>('all')
  const [hook, setHook] = useState('all')
  const [query, setQuery] = useState('')

  const all = useMemo(() => callbackEvents(events), [events])
  const hooks = useMemo(() => [...new Set(all.map(callbackHook))].sort(), [all])
  const counts = useMemo(() => {
    const c = new Map<string, number>()
    for (const e of all) c.set(callbackHook(e), (c.get(callbackHook(e)) ?? 0) + 1)
    return c
  }, [all])

  const q = query.trim().toLowerCase()
  const shown = all
    .filter((e) => framework === 'all' || e.payload.framework === framework)
    .filter((e) => hook === 'all' || callbackHook(e) === hook)
    .filter((e) => !q || `${e.payload.agent} ${detail(e)}`.toLowerCase().includes(q))
    .reverse()

  if (all.length === 0) {
    return <EmptyState title="No callbacks yet">Callbacks appear as soon as an agent starts.</EmptyState>
  }

  return (
    <div className="obs-stream">
      <div className="obs-toolbar">
        <label>
          Framework{' '}
          <select value={framework} onChange={(e) => setFramework(e.target.value as Framework | 'all')}>
            <option value="all">All</option>
            <option value="adk">ADK</option>
            <option value="crewai">CrewAI</option>
          </select>
        </label>
        <label>
          Callback{' '}
          <select value={hook} onChange={(e) => setHook(e.target.value)}>
            <option value="all">All ({all.length})</option>
            {hooks.map((h) => (
              <option key={h} value={h}>
                {h} ({counts.get(h)})
              </option>
            ))}
          </select>
        </label>
        <input
          type="search"
          className="obs-toolbar__search"
          placeholder="Filter by agent or detail"
          aria-label="Filter callbacks"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="obs-toolbar__count">
          {shown.length} of {all.length}
        </span>
      </div>
      <table className="events-table">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Time</th>
            <th scope="col">Framework</th>
            <th scope="col">Callback</th>
            <th scope="col">Agent</th>
            <th scope="col">Details</th>
          </tr>
        </thead>
        <tbody>
          {shown.slice(0, MAX_ROWS).map((event) => (
            <tr key={event.seq}>
              <td className="mono">{event.seq}</td>
              <td className="mono">{new Date(event.ts).toLocaleTimeString()}</td>
              <td>
                <FrameworkBadge framework={event.payload.framework} />
              </td>
              <td className="mono">{callbackHook(event)}</td>
              <td className="mono">{event.payload.agent}</td>
              <td className="events-table__details">{detail(event)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {shown.length > MAX_ROWS && <p className="obs-note">Showing the newest {MAX_ROWS}; narrow the filter to see older callbacks.</p>}
    </div>
  )
}

function detail(event: CallbackEvent): string {
  switch (event.type) {
    case 'callback_fired':
      return event.payload.detail ?? ''
    case 'agent_started':
      return `${event.payload.kind}${event.payload.parent ? ` in ${event.payload.parent}` : ''}`
    case 'agent_finished':
      return `${event.payload.ok ? 'done' : 'failed'}${event.payload.duration_ms === null ? '' : ` in ${formatMs(event.payload.duration_ms)}`}`
  }
}
