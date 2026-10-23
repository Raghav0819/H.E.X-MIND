import { useCallback, useEffect, useState } from 'react'

import type { ApiClient, Project } from '../../lib/api'

export interface Workspace {
  project: Project | null
  recent: Project[]
  error: string | null
  /** Shows the native folder picker, then registers the chosen folder with the backend. */
  pickAndOpen: () => Promise<void>
  open: (workspacePath: string) => Promise<void>
  /** Initializes Git for the open project (agent runs need it). */
  initGit: () => Promise<void>
}

export function useWorkspace(api: ApiClient, backendReady: boolean): Workspace {
  const [project, setProject] = useState<Project | null>(null)
  const [recent, setRecent] = useState<Project[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!backendReady) return
    api
      .get<Project[]>('/projects')
      .then(setRecent)
      .catch(() => setRecent([]))
  }, [api, backendReady, project])

  const open = useCallback(
    async (workspacePath: string) => {
      setError(null)
      try {
        setProject(await api.post<Project>('/projects', { workspace_path: workspacePath }))
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    },
    [api]
  )

  const pickAndOpen = useCallback(async () => {
    const path = await window.hex.pickWorkspace()
    if (path) await open(path)
  }, [open])

  const initGit = useCallback(async () => {
    if (!project) return
    setError(null)
    try {
      setProject(await api.post<Project>(`/projects/${project.id}/git/init`))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [api, project])

  return { project, recent, error, pickAndOpen, open, initGit }
}
