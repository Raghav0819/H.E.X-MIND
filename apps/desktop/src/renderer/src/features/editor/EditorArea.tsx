import Editor, { type OnMount } from '@monaco-editor/react'
import { AlertTriangle, X } from 'lucide-react'
import { useRef } from 'react'

import { EmptyState } from '../../components/Panel'
import { HEX_THEME, modelPath, monaco } from './monaco'
import { isDirty } from './tabs'
import type { EditorTabs } from './useEditorTabs'

interface Props {
  projectId: string
  editor: EditorTabs
}

export function EditorArea({ projectId, editor }: Props) {
  const { state } = editor
  const tab = state.tabs.find((t) => t.path === state.active) ?? null

  // Monaco commands are registered once; read the latest values through refs.
  const activeRef = useRef<string | null>(null)
  activeRef.current = state.active
  const saveRef = useRef(editor.save)
  saveRef.current = editor.save

  const handleMount: OnMount = (instance) => {
    instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      if (activeRef.current) void saveRef.current(activeRef.current)
    })
  }

  const requestClose = (path: string) => {
    const target = state.tabs.find((t) => t.path === path)
    if (target && isDirty(target) && !window.confirm(`Discard unsaved changes to ${path}?`)) return
    editor.close(path)
  }

  return (
    <div className="editor-area">
      <div className="editor-tabs" role="tablist" aria-label="Open files">
        {state.tabs.map((t) => (
          <div key={t.path} className="editor-tab" data-active={t.path === state.active}>
            <button
              type="button"
              role="tab"
              aria-selected={t.path === state.active}
              className="editor-tab__label"
              title={t.path}
              onClick={() => editor.activate(t.path)}
            >
              {basename(t.path)}
              {isDirty(t) && (
                <span className="editor-tab__dirty" aria-label="Unsaved changes" title="Unsaved changes" />
              )}
            </button>
            <button
              type="button"
              className="icon-button icon-button--small"
              aria-label={`Close ${t.path}`}
              title="Close"
              onClick={() => requestClose(t.path)}
            >
              <X size={12} />
            </button>
          </div>
        ))}
      </div>

      {tab && (
        <>
          <div className="breadcrumbs" aria-label="File path">
            {tab.path.split('/').map((part, i, parts) => (
              <span key={i} className="breadcrumbs__part">
                {part}
                {i < parts.length - 1 && <span className="breadcrumbs__sep">/</span>}
              </span>
            ))}
            {tab.saving && <span className="breadcrumbs__status">Saving…</span>}
          </div>

          {tab.conflict && (
            <div className="banner banner--warning" role="alert">
              <AlertTriangle size={14} />
              <span>This file changed on disk after you opened it. Your edits were not saved.</span>
              <button type="button" className="button button--small" onClick={() => void editor.reloadFromDisk(tab.path)}>
                Reload from disk
              </button>
              <button type="button" className="button button--small" onClick={() => void editor.overwrite(tab.path)}>
                Overwrite
              </button>
            </div>
          )}
          {tab.error && (
            <div className="banner banner--danger" role="alert">
              <AlertTriangle size={14} />
              <span>Save failed: {tab.error}</span>
            </div>
          )}

          <div className="editor-body">
            {tab.content === null ? (
              <EmptyState title={tab.binary ? 'Binary file' : 'File too large to edit'}>
                {tab.binary
                  ? 'This file is not UTF-8 text and cannot be edited here.'
                  : 'Large files are not opened in the editor.'}
              </EmptyState>
            ) : (
              <Editor
                path={modelPath(projectId, tab.path)}
                value={tab.content}
                theme={HEX_THEME}
                onMount={handleMount}
                onChange={(value) => editor.edit(tab.path, value ?? '')}
                options={{
                  fontFamily: "'Cascadia Code', 'JetBrains Mono', Consolas, monospace",
                  fontSize: 13,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  renderWhitespace: 'selection',
                  tabSize: 2
                }}
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}

function basename(path: string): string {
  return path.slice(path.lastIndexOf('/') + 1)
}
