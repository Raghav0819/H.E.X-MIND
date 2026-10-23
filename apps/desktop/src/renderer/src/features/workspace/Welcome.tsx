import { FolderOpen } from 'lucide-react'

import type { BackendStatus } from '../../hooks/useBackendHealth'
import type { Workspace } from './useWorkspace'

interface Props {
  status: BackendStatus
  workspace: Workspace
}

export function Welcome({ status, workspace }: Props) {
  const connected = status.kind === 'connected'
  const health = connected ? status.health : null
  const ollama = health?.providers['ollama']

  return (
    <div className="welcome">
      <h1 className="welcome__title">H.E.X Mind</h1>
      <p className="welcome__subtitle">
        {workspace.project
          ? `${workspace.project.name}: select a file in the explorer to start editing.`
          : 'Agent-native IDE with live multi-agent observability'}
      </p>

      <div className="welcome__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={!connected}
          title={connected ? undefined : 'Backend is not connected'}
          onClick={() => void workspace.pickAndOpen()}
        >
          <FolderOpen size={16} />
          Open folder
        </button>
      </div>
      {workspace.error && (
        <p className="welcome__error" role="alert">
          Could not open workspace: {workspace.error}
        </p>
      )}

      {workspace.recent.length > 0 && (
        <section className="welcome__section" aria-label="Recent workspaces">
          <h2 className="welcome__heading">Recent</h2>
          <ul className="recent">
            {workspace.recent.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className="recent__item"
                  title={p.workspace_path}
                  onClick={() => void workspace.open(p.workspace_path)}
                >
                  <span className="recent__name">{p.name}</span>
                  <span className="recent__path">{p.workspace_path}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="welcome__section" aria-label="Readiness">
        <h2 className="welcome__heading">Readiness</h2>
        <dl className="readiness">
          <ReadinessRow label="Backend" ok={connected} value={health ? `Ready (v${health.version})` : 'Not ready'} />
          <ReadinessRow
            label="Database"
            ok={health?.db === 'ok'}
            value={health ? (health.db === 'ok' ? 'Connected' : 'Unavailable') : 'Unknown'}
          />
          <ReadinessRow
            label="Ollama"
            ok={ollama?.available === true}
            value={ollama ? (ollama.available ? ollama.model : 'Unavailable') : 'Unknown'}
            detail={ollama?.detail ?? undefined}
          />
        </dl>
      </section>
    </div>
  )
}

function ReadinessRow({ label, ok, value, detail }: { label: string; ok: boolean; value: string; detail?: string }) {
  return (
    <div className="readiness__row">
      <dt>{label}</dt>
      <dd data-ok={ok} title={detail}>
        {value}
      </dd>
    </div>
  )
}
