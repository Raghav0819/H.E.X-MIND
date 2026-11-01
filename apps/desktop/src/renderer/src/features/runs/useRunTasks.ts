import { useEffect, useState } from 'react'

import { SETTLED_RUN_STATUSES, type ApiClient, type Run, type Task } from '../../lib/api'

const POLL_MS = 1500

export interface RunTasks {
  tasks: Task[]
  error: string | null
}

/** Polls a run's Blackboard tasks until the run settles. */
export function useRunTasks(api: ApiClient, runId: string | null): RunTasks {
  const [state, setState] = useState<RunTasks>({ tasks: [], error: null })

  useEffect(() => {
    setState({ tasks: [], error: null })
    if (!runId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const [run, tasks] = await Promise.all([
          api.get<Run>(`/runs/${runId}`),
          api.get<Task[]>('/tasks', { run_id: runId })
        ])
        if (cancelled) return
        setState({ tasks, error: null })
        if (SETTLED_RUN_STATUSES.has(run.status)) return
      } catch (err) {
        if (cancelled) return
        setState((s) => ({ ...s, error: err instanceof Error ? err.message : String(err) }))
      }
      timer = setTimeout(poll, POLL_MS)
    }
    void poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [api, runId])

  return state
}
