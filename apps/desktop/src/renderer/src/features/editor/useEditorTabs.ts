import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, type ApiClient, type FileContent, type FileWritten } from '../../lib/api'
import { initialTabs, isDirty, tabsReducer, type TabsAction, type TabsState } from './tabs'

export interface EditorTabs {
  state: TabsState
  openFile: (path: string) => Promise<void>
  activate: (path: string) => void
  close: (path: string) => void
  edit: (path: string, content: string) => void
  /** Saves using the tab's base hash; the backend rejects it if the file changed on disk. */
  save: (path: string) => Promise<void>
  /** Conflict resolution: discard local edits and load the current file from disk. */
  reloadFromDisk: (path: string) => Promise<void>
  /** Conflict resolution: explicitly overwrite the newer on-disk version. */
  overwrite: (path: string) => Promise<void>
}

export function useEditorTabs(
  api: ApiClient,
  projectId: string | null,
  /** Called for every tab that closes, including all tabs when the project changes. */
  onClosed: (projectId: string, path: string) => void
): EditorTabs {
  // The ref is updated synchronously on every dispatch (not on the next render), so a save
  // triggered immediately after a keystroke (e.g. Ctrl+S) always sees the latest content.
  const [state, setState] = useState<TabsState>(initialTabs)
  const stateRef = useRef(state)
  const dispatch = useCallback((action: TabsAction) => {
    stateRef.current = tabsReducer(stateRef.current, action)
    setState(stateRef.current)
  }, [])

  // Switching projects (or unmounting) closes every tab of the previous project.
  useEffect(() => {
    return () => {
      if (projectId) stateRef.current.tabs.forEach((tab) => onClosed(projectId, tab.path))
      dispatch({ type: 'closeAll' })
    }
  }, [projectId, onClosed, dispatch])

  const fetchFile = useCallback(
    (path: string) => api.get<FileContent>(`/projects/${projectId}/file`, { path }),
    [api, projectId]
  )

  const openFile = useCallback(
    async (path: string) => {
      if (!projectId) return
      if (stateRef.current.tabs.some((t) => t.path === path)) {
        dispatch({ type: 'activate', path })
        return
      }
      dispatch({ type: 'opened', file: await fetchFile(path) })
    },
    [projectId, fetchFile]
  )

  const write = useCallback(
    async (path: string, baseHash: string | null) => {
      const tab = stateRef.current.tabs.find((t) => t.path === path)
      if (!projectId || !tab || tab.content === null || tab.saving) return
      const content = tab.content
      dispatch({ type: 'saveStarted', path })
      try {
        const result = await api.put<FileWritten>(`/projects/${projectId}/file`, {
          path,
          content,
          base_hash: baseHash
        })
        dispatch({ type: 'saved', path, hash: result.hash, content })
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          const body = err.body as { current_hash?: string | null } | null
          dispatch({ type: 'conflict', path, currentHash: body?.current_hash ?? null })
        } else {
          dispatch({ type: 'saveFailed', path, error: err instanceof Error ? err.message : String(err) })
        }
      }
    },
    [api, projectId]
  )

  const save = useCallback(
    async (path: string) => {
      const tab = stateRef.current.tabs.find((t) => t.path === path)
      if (tab && isDirty(tab)) await write(path, tab.hash)
    },
    [write]
  )

  const overwrite = useCallback(
    async (path: string) => {
      const tab = stateRef.current.tabs.find((t) => t.path === path)
      if (tab?.conflict) await write(path, tab.conflict.currentHash)
    },
    [write]
  )

  const reloadFromDisk = useCallback(
    async (path: string) => {
      dispatch({ type: 'reloaded', file: await fetchFile(path) })
    },
    [fetchFile]
  )

  const close = useCallback(
    (path: string) => {
      dispatch({ type: 'close', path })
      if (projectId) onClosed(projectId, path)
    },
    [projectId, onClosed]
  )

  const activate = useCallback((path: string) => dispatch({ type: 'activate', path }), [])
  const edit = useCallback(
    (path: string, content: string) => dispatch({ type: 'edit', path, content }),
    []
  )

  return { state, openFile, activate, close, edit, save, reloadFromDisk, overwrite }
}
