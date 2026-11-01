import { EmptyState } from '../../components/Panel'
import type { AgentEvent } from '../../generated/events'
import { deriveTopology, type TopologyNode } from './derive'
import { FrameworkBadge } from './FrameworkBadge'

const PATTERN: Record<string, string> = {
  sequential: 'Sequential',
  loop: 'Loop · reflection',
  parallel: 'Parallel',
  llm: 'LLM agent',
  custom: 'Deterministic step',
  crew: 'CrewAI crew'
}

/**
 * Criteria 4 and 7: the agent pattern as it actually ran (built from the parent recorded on
 * each agent_started event), with running agents highlighted and each node's framework.
 */
export function PatternTopology({ events }: { events: AgentEvent[] }) {
  const roots = deriveTopology(events)
  if (roots.length === 0) return <EmptyState title="No agents have started" />

  return (
    <div className="obs-topology">
      <p className="obs-note">
        Google ADK orchestrates (<FrameworkBadge framework="adk" />); CrewAI crews do the planning and coding (
        <FrameworkBadge framework="crewai" />). Highlighted nodes are running now.
      </p>
      <ul className="topology" role="tree" aria-label="Agent topology">
        {roots.map((node) => (
          <TopologyItem key={node.name} node={node} />
        ))}
      </ul>
    </div>
  )
}

function TopologyItem({ node }: { node: TopologyNode }) {
  return (
    <li role="treeitem" aria-expanded={node.children.length > 0 ? true : undefined}>
      <div className="topology__node" data-active={node.active} data-kind={node.kind}>
        <span className="topology__name mono">{node.name}</span>
        <FrameworkBadge framework={node.framework} />
        <span className="topology__pattern">{PATTERN[node.kind] ?? node.kind}</span>
        {node.invocations > 1 && (
          <span className="topology__count" title="Times this agent ran">
            ×{node.invocations}
          </span>
        )}
      </div>
      {node.children.length > 0 && (
        <ul role="group">
          {node.children.map((child) => (
            <TopologyItem key={child.name} node={child} />
          ))}
        </ul>
      )}
    </li>
  )
}
