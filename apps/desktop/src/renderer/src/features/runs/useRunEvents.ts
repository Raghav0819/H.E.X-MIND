import { useEffect, useRef, useState } from 'react'

import type { AgentEvent } from '../../generated/events'
import { TERMINAL_RUN_STATUSES, type ApiClient, type Run } from '../../lib/api'
import { contiguousSeq, mergeEvents } from './events'

const POLL_MS = 1000

export interface RunEvents {
  run: Run | null
  events: AgentEvent[]
  error: string | null
}

/**
 * Polls a run and its events until the run reaches a terminal status.
 * (Replaced by the WebSocket stream with snapshot reconciliation in M5.)
 */
export function useRunEvents(api: ApiClient, runId: string | null): RunEvents {
  const [state, setState] = useState<RunEvents>({ run: null, events: [], error: null })
  const eventsRef = useRef<AgentEvent[]>([])

  useEffect(() => {
    eventsRef.current = []
    setState({ run: null, events: [], error: null })
    if (!runId) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const poll = async () => {
      try {
        const after = String(contiguousSeq(eventsRef.current))
        const [run, incoming] = await Promise.all([
          api.get<Run>(`/runs/${runId}`),
          api.get<AgentEvent[]>(`/runs/${runId}/events`, { after_seq: after })
        ])
        if (cancelled) return
        eventsRef.current = mergeEvents(eventsRef.current, incoming)
        setState({ run, events: eventsRef.current, error: null })
        const caughtUp = contiguousSeq(eventsRef.current) >= run.last_event_seq
        if (TERMINAL_RUN_STATUSES.has(run.status) && caughtUp) return
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
