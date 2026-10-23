import {
  Bot,
  Files,
  FolderOpen,
  History,
  PanelBottom,
  PanelRight,
  RefreshCw,
  Settings,
  type LucideIcon
} from 'lucide-react'
import { useState } from 'react'

import { BackendStatusPill } from './components/BackendStatusPill'
import { EmptyState, PanelHeader } from './components/Panel'
import { EditorArea } from './features/editor/EditorArea'
import { disposeModel } from './features/editor/monaco'
import { useEditorTabs } from './features/editor/useEditorTabs'
import { FileTree } from './features/explorer/FileTree'
import { Welcome } from './features/workspace/Welcome'
import { useWorkspace } from './features/workspace/useWorkspace'
import { useBackendHealth } from './hooks/useBackendHealth'
import { useBackend } from './lib/backend'

type View = 'explorer' | 'agents' | 'runs' | 'settings'

const VIEWS: { id: View; label: string; icon: LucideIcon }[] = [
  { id: 'explorer', label: 'Explorer', icon: Files },
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'runs', label: 'Runs', icon: History },
  { id: 'settings', label: 'Settings', icon: Settings }
]

const BOTTOM_TABS = ['Problems', 'Tasks', 'Agent Events', 'Logs'] as const
type BottomTab = (typeof BOTTOM_TABS)[number]

const SIDEBAR_EMPTY: Record<Exclude<View, 'explorer'>, string> = {
  agents: 'No agents running',
  runs: 'No runs yet',
  settings: 'Settings are not available yet'
}

export function App() {
  const { config, api } = useBackend()
  const { status, retry } = useBackendHealth(config)
  const workspace = useWorkspace(api, status.kind === 'connected')
  const project = workspace.project
  const editor = useEditorTabs(api, project?.id ?? null, disposeModel)

  const [view, setView] = useState<View>('explorer')
  const [rightOpen, setRightOpen] = useState(true)
  const [bottomOpen, setBottomOpen] = useState(true)
  const [bottomTab, setBottomTab] = useState<BottomTab>('Problems')
  const [treeRefresh, setTreeRefresh] = useState(0)

  const viewLabel = VIEWS.find((v) => v.id === view)?.label ?? ''

  return (
    <div className="app" data-right={rightOpen} data-bottom={bottomOpen}>
      <header className="topbar">
        <div className="topbar__brand">
          <span className="brand-mark" aria-hidden="true">
            HX
          </span>
          <span className="brand-name">H.E.X Mind</span>
          <span className="topbar__divider" aria-hidden="true" />
          <span className="topbar__workspace" title={project?.workspace_path}>
            {project ? project.name : 'No workspace'}
          </span>
          {project && !project.git_enabled && (
            <span className="badge" title="Agent edits will require Git (milestone M3)">
              No Git
            </span>
          )}
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

      <aside className="sidebar" aria-label={viewLabel}>
        {view === 'explorer' ? (
          <>
            <PanelHeader
              title={project ? project.name : 'Explorer'}
              actions={
                <>
                  {project && (
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Refresh explorer"
                      title="Refresh"
                      onClick={() => setTreeRefresh((n) => n + 1)}
                    >
                      <RefreshCw size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Open folder"
                    title="Open folder"
                    disabled={status.kind !== 'connected'}
                    onClick={() => void workspace.pickAndOpen()}
                  >
                    <FolderOpen size={14} />
                  </button>
                </>
              }
            />
            {project ? (
              <FileTree
                api={api}
                projectId={project.id}
                activePath={editor.state.active}
                onOpenFile={(path) => void editor.openFile(path)}
                refreshKey={treeRefresh}
              />
            ) : (
              <EmptyState title="No workspace open" />
            )}
          </>
        ) : (
          <>
            <PanelHeader title={viewLabel} />
            <EmptyState title={SIDEBAR_EMPTY[view]} />
          </>
        )}
      </aside>

      <main className="editor">
        {project && editor.state.tabs.length > 0 ? (
          <EditorArea projectId={project.id} editor={editor} />
        ) : (
          <Welcome status={status} workspace={workspace} />
        )}
      </main>

      {rightOpen && (
        <aside className="rightpanel" aria-label="Agent chat">
          <PanelHeader title="Agent Chat" />
          <EmptyState title="Chat is not available yet">
            Agent chat arrives in a later milestone.
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
