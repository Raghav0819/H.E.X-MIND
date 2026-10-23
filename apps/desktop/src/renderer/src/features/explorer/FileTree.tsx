import { ChevronDown, ChevronRight, File, Folder, FolderOpen } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import type { ApiClient, TreeEntry } from '../../lib/api'

type DirState =
  | { kind: 'loading' }
  | { kind: 'loaded'; entries: TreeEntry[] }
  | { kind: 'error'; message: string }

interface Props {
  api: ApiClient
  projectId: string
  activePath: string | null
  onOpenFile: (path: string) => void
  /** Changing this value reloads every loaded directory. */
  refreshKey?: number
}

/** Lazily loaded workspace tree: a directory's children are fetched when it is first expanded. */
export function FileTree({ api, projectId, activePath, onOpenFile, refreshKey = 0 }: Props) {
  const [dirs, setDirs] = useState<Record<string, DirState>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const load = useCallback(
    async (path: string) => {
      setDirs((d) => ({ ...d, [path]: d[path]?.kind === 'loaded' ? d[path] : { kind: 'loading' } }))
      try {
        const entries = await api.get<TreeEntry[]>(`/projects/${projectId}/tree`, { path })
        setDirs((d) => ({ ...d, [path]: { kind: 'loaded', entries } }))
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        setDirs((d) => ({ ...d, [path]: { kind: 'error', message } }))
      }
    },
    [api, projectId]
  )

  // New project: reset and load the root.
  useEffect(() => {
    setDirs({})
    setExpanded(new Set())
    void load('')
  }, [load])

  // Manual refresh: reload the root and every expanded directory.
  useEffect(() => {
    if (refreshKey === 0) return
    void load('')
    expanded.forEach((path) => void load(path))
  }, [refreshKey]) // intentionally only on explicit refresh

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
        if (!dirs[path]) void load(path)
      }
      return next
    })
  }

  const renderDir = (path: string, depth: number) => {
    const state = dirs[path]
    if (!state || state.kind === 'loading') {
      return <div className="tree__status" style={{ paddingLeft: indent(depth) }}>Loading…</div>
    }
    if (state.kind === 'error') {
      return (
        <div className="tree__status tree__status--error" style={{ paddingLeft: indent(depth) }}>
          {state.message}
        </div>
      )
    }
    if (state.entries.length === 0 && depth > 0) {
      return <div className="tree__status" style={{ paddingLeft: indent(depth) }}>Empty</div>
    }
    return state.entries.map((entry) => {
      const isDir = entry.type === 'directory'
      const isOpen = expanded.has(entry.path)
      return (
        <div key={entry.path} role="none">
          <button
            type="button"
            role="treeitem"
            aria-expanded={isDir ? isOpen : undefined}
            aria-selected={entry.path === activePath}
            className="tree__item"
            style={{ paddingLeft: indent(depth) }}
            title={entry.path}
            onClick={() => (isDir ? toggle(entry.path) : onOpenFile(entry.path))}
          >
            <span className="tree__chevron" aria-hidden="true">
              {isDir && (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />)}
            </span>
            <span className="tree__icon" aria-hidden="true">
              {isDir ? isOpen ? <FolderOpen size={14} /> : <Folder size={14} /> : <File size={14} />}
            </span>
            <span className="tree__name">{entry.name}</span>
          </button>
          {isDir && isOpen && <div role="group">{renderDir(entry.path, depth + 1)}</div>}
        </div>
      )
    })
  }

  return (
    <div className="tree" role="tree" aria-label="Workspace files">
      {renderDir('', 0)}
    </div>
  )
}

function indent(depth: number): number {
  return 8 + depth * 12
}
