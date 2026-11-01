import type { Framework } from './derive'

const LABELS: Record<Framework, string> = { adk: 'ADK', crewai: 'CrewAI' }
const TITLES: Record<Framework, string> = {
  adk: 'Google Agent Development Kit agent',
  crewai: 'CrewAI crew'
}

/** Criterion 7: which framework runs this agent, colour-coded everywhere it appears. */
export function FrameworkBadge({ framework }: { framework: Framework }) {
  return (
    <span className="framework-badge" data-framework={framework} title={TITLES[framework]}>
      {LABELS[framework]}
    </span>
  )
}
