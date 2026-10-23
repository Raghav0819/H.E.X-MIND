import { EmptyState } from '../../components/Panel'
import type { ApiClient } from '../../lib/api'
import { describeEvent, isStub } from './events'
import { useRunEvents } from './useRunEvents'

interface Props {
  api: ApiClient
  runId: string | null
  onReview: (runId: string) => void
}

export function RunEventsPanel({ api, runId, onReview }: Props) {
  const { run, events, error } = useRunEvents(api, runId)

  if (!runId) {
    return <EmptyState title="No run selected">Start an Edit request in the chat to see its events here.</EmptyState>
  }

  return (
    <div className="run-events">
      <div className="run-events__header">
        <span className="run-events__title">{run?.title ?? 'Loading run…'}</span>
        {run && (
          <span className="run-events__status" data-status={run.status}>
            {run.status}
          </span>
        )}
        {run?.status === 'awaiting_approval' && (
          <button type="button" className="button button--small button--primary" onClick={() => onReview(run.id)}>
            Review changes
          </button>
        )}
        {error && (
          <span className="run-events__error" role="alert">
            {error}
          </span>
        )}
      </div>
      <table className="events-table">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Time</th>
            <th scope="col">Event</th>
            <th scope="col">Agent</th>
            <th scope="col">Details</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.seq}>
              <td className="mono">{event.seq}</td>
              <td className="mono">{new Date(event.ts).toLocaleTimeString()}</td>
              <td className="mono">
                {event.type}
                {isStub(event) && (
                  <span className="stub-badge" title="Placeholder step: no agent work was performed">
                    stub
                  </span>
                )}
              </td>
              <td>{event.agent_id ?? '—'}</td>
              <td className="events-table__details">{describeEvent(event)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
