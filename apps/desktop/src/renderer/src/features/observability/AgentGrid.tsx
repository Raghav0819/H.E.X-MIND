import { EmptyState } from '../../components/Panel'
import type { AgentEvent } from '../../generated/events'
import { formatMs } from '../runs/events'
import { deriveAgents } from './derive'
import { FrameworkBadge } from './FrameworkBadge'

/** Criterion 5: every agent with its status, current step, model usage and tool calls. */
export function AgentGrid({ events }: { events: AgentEvent[] }) {
  const agents = deriveAgents(events).sort((a, b) => Number(b.active > 0) - Number(a.active > 0) || b.lastSeq - a.lastSeq)

  if (agents.length === 0) return <EmptyState title="No agents have started" />

  return (
    <div className="agent-grid" role="list" aria-label="Agents">
      {agents.map((agent) => (
        <article key={agent.name} className="agent-card" role="listitem" data-active={agent.active > 0}>
          <header className="agent-card__header">
            <span className="agent-card__name mono">{agent.name}</span>
            <FrameworkBadge framework={agent.framework} />
          </header>
          <div className="agent-card__status">
            <span className="agent-card__dot" aria-hidden="true" />
            {agent.active > 0 ? 'running' : 'idle'} · {agent.kind}
            {agent.parent && <span className="agent-card__parent"> in {agent.parent}</span>}
          </div>
          <dl className="agent-card__stats">
            <div>
              <dt>Runs</dt>
              <dd>{agent.invocations}</dd>
            </div>
            <div>
              <dt>Last</dt>
              <dd>{agent.lastDurationMs === null ? '—' : formatMs(agent.lastDurationMs)}</dd>
            </div>
            <div>
              <dt>LLM calls</dt>
              <dd>{agent.llmCalls}</dd>
            </div>
            <div>
              <dt>Tokens</dt>
              <dd>
                {agent.inputTokens}→{agent.outputTokens}
              </dd>
            </div>
            <div>
              <dt>Tools</dt>
              <dd>{agent.toolCalls}</dd>
            </div>
            <div>
              <dt>Callbacks</dt>
              <dd>{agent.callbacks}</dd>
            </div>
          </dl>
          {agent.lastActivity && (
            <div className="agent-card__activity" title={agent.lastActivity}>
              {agent.lastActivity}
            </div>
          )}
        </article>
      ))}
    </div>
  )
}
