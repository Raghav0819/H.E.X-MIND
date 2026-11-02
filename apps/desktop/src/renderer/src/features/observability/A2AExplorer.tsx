import { useEffect, useState } from 'react'

import { EmptyState } from '../../components/Panel'
import type { AgentEvent } from '../../generated/events'
import type { A2AAgent, ApiClient, Task } from '../../lib/api'
import { formatMs } from '../runs/events'
import { deriveA2AExchanges } from './derive'
import { FrameworkBadge } from './FrameworkBadge'

interface Props {
  api: ApiClient
  events: AgentEvent[]
  tasks: Task[]
}

/**
 * Criterion 6: the CrewAI crews the ADK orchestrator reaches over A2A. Agent cards come live
 * from the crew service; each exchange joins what the orchestrator (client) and the crew
 * (server) recorded, with the A2A task lifecycle and whether both sides share one trace.
 */
export function A2AExplorer({ api, events, tasks }: Props) {
  const [agents, setAgents] = useState<A2AAgent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const titles = new Map(tasks.map((t) => [t.id, t.title]))
  const exchanges = deriveA2AExchanges(events)

  useEffect(() => {
    let cancelled = false
    api
      .get<A2AAgent[]>('/a2a/agents')
      .then((list) => !cancelled && setAgents(list))
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [api])

  return (
    <div className="obs-a2a">
      <section className="obs-section" aria-label="Agent cards">
        <h3 className="obs-section__title">Agent cards</h3>
        {error && <p className="obs-note">Could not load agent cards: {error}</p>}
        <div className="a2a-cards">
          {(agents ?? []).map((agent) => (
            <article key={agent.role} className="a2a-card" data-reachable={agent.reachable}>
              <header className="a2a-card__header">
                <span className="mono">{agent.card?.name ?? `${agent.role}_crew`}</span>
                <FrameworkBadge framework="crewai" />
                <span className="a2a-card__status">{agent.reachable ? 'reachable' : 'unreachable'}</span>
              </header>
              {agent.card ? (
                <>
                  <p className="a2a-card__description">{agent.card.description}</p>
                  <dl className="a2a-card__facts">
                    <dt>Endpoint</dt>
                    <dd className="mono">{agent.card.url}</dd>
                    <dt>Version</dt>
                    <dd className="mono">
                      {agent.card.version}
                      {agent.card.protocolVersion ? ` · A2A ${agent.card.protocolVersion}` : ''}
                    </dd>
                    <dt>Skills</dt>
                    <dd>
                      {agent.card.skills.map((s) => (
                        <span key={s.id} className="a2a-card__skill" title={s.description}>
                          {s.name}
                        </span>
                      ))}
                    </dd>
                  </dl>
                </>
              ) : (
                <p className="obs-note">{agent.error}</p>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="obs-section" aria-label="A2A exchanges">
        <h3 className="obs-section__title">Exchanges ({exchanges.length})</h3>
        {exchanges.length === 0 ? (
          <EmptyState title="No A2A calls in this run yet" />
        ) : (
          <ol className="a2a-exchanges">
            {exchanges.map((x) => (
              <li key={x.exchangeId} className="a2a-exchange" data-state={x.state}>
                <header className="a2a-exchange__header">
                  <span className="mono">orchestrator → {x.crew}</span>
                  <span className="a2a-state" data-state={x.state}>
                    {x.state}
                  </span>
                  {x.taskId && <span className="a2a-exchange__task">{titles.get(x.taskId) ?? x.taskId.slice(0, 8)}</span>}
                  {x.durationMs !== null && <span className="mono">{formatMs(x.durationMs)}</span>}
                  <span
                    className="a2a-trace"
                    data-shared={x.traceShared}
                    title={x.traceId ? `trace ${x.traceId}` : 'no trace id recorded'}
                  >
                    {x.traceShared ? 'one trace across A2A' : 'trace not joined'}
                  </span>
                </header>
                <div className="a2a-exchange__ids mono">
                  A2A task {x.a2aTaskId ?? '—'} · exchange {x.exchangeId.slice(0, 8)}
                </div>
                <ol className="a2a-steps">
                  {x.steps.map((step) => (
                    <li key={step.seq} className="a2a-step" data-side={step.side}>
                      <span className="mono a2a-step__time">{new Date(step.ts).toLocaleTimeString()}</span>
                      <span className="a2a-step__who">
                        {step.side === 'client' ? 'ADK orchestrator' : 'CrewAI crew'} {step.direction}
                      </span>
                      {step.state && (
                        <span className="a2a-state" data-state={step.state}>
                          {step.state}
                        </span>
                      )}
                      {step.summary && (
                        <span className="a2a-step__summary" title={step.summary}>
                          {step.summary}
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}
