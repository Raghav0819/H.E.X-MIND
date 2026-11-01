import { EmptyState } from '../../components/Panel'
import type { AgentEvent } from '../../generated/events'
import { schemaChecks } from './derive'

const STATUS_HELP = {
  valid: 'Valid on the first attempt',
  repaired: 'Invalid at first; valid after one repair call',
  fallback: 'Still invalid (or the model call failed); a schema-valid fallback was used'
} as const

/** Criterion 3: every structured (Pydantic) output and how it validated. */
export function SchemaChecks({ events }: { events: AgentEvent[] }) {
  const checks = schemaChecks(events)
  if (checks.length === 0) {
    return <EmptyState title="No structured outputs yet">The Planner and Reviewer outputs are validated here.</EmptyState>
  }

  const totals = { valid: 0, repaired: 0, fallback: 0 }
  for (const c of checks) totals[c.payload.status] += 1

  return (
    <div className="obs-schema">
      <div className="obs-summary" aria-label="Schema check totals">
        {(Object.keys(totals) as (keyof typeof totals)[]).map((status) => (
          <div key={status} className="obs-summary__item" title={STATUS_HELP[status]}>
            <span className="schema-status" data-status={status}>
              {status}
            </span>
            <span className="obs-summary__value">{totals[status]}</span>
          </div>
        ))}
      </div>
      <table className="events-table">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Time</th>
            <th scope="col">Agent</th>
            <th scope="col">Schema</th>
            <th scope="col">Result</th>
            <th scope="col">Validation errors</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((check) => (
            <tr key={check.seq}>
              <td className="mono">{check.seq}</td>
              <td className="mono">{new Date(check.ts).toLocaleTimeString()}</td>
              <td className="mono">{check.payload.agent}</td>
              <td className="mono">{check.payload.schema_name}</td>
              <td>
                <span className="schema-status" data-status={check.payload.status} title={STATUS_HELP[check.payload.status]}>
                  {check.payload.status}
                </span>
              </td>
              <td className="events-table__details mono">{check.payload.errors.join(' · ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
