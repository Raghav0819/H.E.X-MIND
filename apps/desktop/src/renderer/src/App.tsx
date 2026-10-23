import {
  Bot,
  FolderOpen,
  Files,
  History,
  MessageSquare,
  PanelBottom,
  PanelRight,
  Settings,
  type LucideIcon
} from 'lucide-react'
import { useState } from 'react'

import { BackendStatusPill } from './components/BackendStatusPill'
import { EmptyState, PanelHeader } from './components/Panel'
import { useBackendHealth, type BackendStatus } from './hooks/useBackendHealth'

type View = 'explorer' | 'agents' | 'runs' | 'settings'

const VIEWS: { id: View; label: string; icon: LucideIcon }[] = [
  { id: 'explorer', label: 'Explorer', icon: Files },
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'runs', label: 'Runs', icon: History },
  { id: 'settings', label: 'Settings', icon: Settings }
]

const BOTTOM_TABS = ['Problems', 'Tasks', 'Agent Events', 'Logs'] as const
type BottomTab = (typeof BOTTOM_TABS)[number]

const SIDEBAR_EMPTY: Record<View, string> = {
  explorer: 'No workspace open',
  agents: 'No agents running',
  runs: 'No runs yet',
  settings: 'Settings are not available yet'
}

export function App() {
  const { status, retry } = useBackendHealth()
  const [view, setView] = useState<View>('explorer')
  const [rightOpen, setRightOpen] = useState(true)
  const [bottomOpen, setBottomOpen] = useState(true)
  const [bottomTab, setBottomTab] = useState<BottomTab>('Problems')

  return (
    <div className="app" data-right={rightOpen} data-bottom={bottomOpen}>
      <header className="topbar">
        <div className="topbar__brand">
          <span className="brand-mark" aria-hidden="true">
            HX
          </span>
          <span className="brand-name">H.E.X Mind</span>
          <span className="topbar__divider" aria-hidden="true" />
          <span className="topbar__workspace">No workspace</span>
        </div>
        <div className="topbar__actions">
          <BackendStatusPill status={status} onRetry={retry} />
          <button
            type="button"
            className="icon-button"
            aria-label="Toggle bottom panel"
            aria-pressed={bottomOpen}
            title="Toggle bottom panel"
            onClick={() => setBottomOpen((open) => !open)}
          >
            <PanelBottom size={16} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Toggle chat panel"
            aria-pressed={rightOpen}
            title="Toggle chat panel"
            onClick={() => setRightOpen((open) => !open)}
          >
            <PanelRight size={16} />
          </button>
        </div>
      </header>

      <nav className="activitybar" aria-label="Views">
        {VIEWS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className="activitybar__item"
            aria-label={label}
            aria-current={view === id ? 'page' : undefined}
            title={label}
            onClick={() => setView(id)}
          >
            <Icon size={20} />
          </button>
        ))}
      </nav>

      <aside className="sidebar" aria-label={VIEWS.find((v) => v.id === view)?.label}>
        <PanelHeader title={VIEWS.find((v) => v.id === view)?.label ?? ''} />
        <EmptyState title={SIDEBAR_EMPTY[view]} />
      </aside>

      <main className="editor">
        <Welcome status={status} />
      </main>

      {rightOpen && (
        <aside className="rightpanel" aria-label="Agent chat">
          <PanelHeader title="Agent Chat" />
          <EmptyState title="Chat is not available yet">
            Open a workspace to start a conversation with the agents.
          </EmptyState>
        </aside>
      )}

      {bottomOpen && (
        <section className="bottompanel" aria-label="Panels">
          <div className="tabs" role="tablist">
            {BOTTOM_TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                className="tabs__tab"
                aria-selected={bottomTab === tab}
                onClick={() => setBottomTab(tab)}
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="bottompanel__body" role="tabpanel" aria-label={bottomTab}>
            <EmptyState title={`No ${bottomTab.toLowerCase()} to show`} />
          </div>
        </section>
      )}
    </div>
  )
}

function Welcome({ status }: { status: BackendStatus }) {
  return (
    <div className="welcome">
      <h1 className="welcome__title">H.E.X Mind</h1>
      <p className="welcome__subtitle">Agent-native IDE with live multi-agent observability</p>
      <div className="welcome__actions">
        <button type="button" className="button button--primary" disabled title="Not available yet">
          <FolderOpen size={16} />
          Open folder
        </button>
        <button type="button" className="button" disabled title="Not available yet">
          <MessageSquare size={16} />
          New conversation
        </button>
      </div>
      <dl className="readiness">
        <div className="readiness__row">
          <dt>Backend</dt>
          <dd data-ok={status.kind === 'connected'}>
            {status.kind === 'connected' ? `Ready (v${status.version})` : 'Not ready'}
          </dd>
        </div>
        <div className="readiness__row">
          <dt>Model providers</dt>
          <dd>Not configured</dd>
        </div>
      </dl>
    </div>
  )
}
