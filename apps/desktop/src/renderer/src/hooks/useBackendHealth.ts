import { useCallback, useEffect, useRef, useState } from 'react'

import type { BackendConfig } from '../../../preload/api'

export type BackendStatus =
  | { kind: 'connecting' }
  | { kind: 'connected'; version: string }
  | { kind: 'misconfigured' }
  | { kind: 'unauthorized' }
  | { kind: 'unreachable'; error: string }

const CONNECTED_POLL_MS = 5000
const DISCONNECTED_POLL_MS = 3000
const REQUEST_TIMEOUT_MS = 3000

export async function checkHealth(
  config: BackendConfig,
  fetchFn: typeof fetch = fetch,
  timeoutMs = REQUEST_TIMEOUT_MS
): Promise<BackendStatus> {
  if (!config.token) return { kind: 'misconfigured' }
  try {
    const response = await fetchFn(`${config.url}/api/health`, {
      headers: { Authorization: `Bearer ${config.token}` },
      signal: AbortSignal.timeout(timeoutMs)
    })
    if (response.status === 401) return { kind: 'unauthorized' }
    if (!response.ok) return { kind: 'unreachable', error: `HTTP ${response.status}` }
    const body = (await response.json()) as { status?: unknown; version?: unknown }
    if (body.status !== 'ok' || typeof body.version !== 'string') {
      return { kind: 'unreachable', error: 'Unexpected health response' }
    }
    return { kind: 'connected', version: body.version }
  } catch (err) {
    return { kind: 'unreachable', error: err instanceof Error ? err.message : String(err) }
  }
}

/** Polls the backend health endpoint; `retry` forces an immediate check. */
export function useBackendHealth(): { status: BackendStatus; retry: () => void } {
  const [status, setStatus] = useState<BackendStatus>({ kind: 'connecting' })
  const [attempt, setAttempt] = useState(0)
  const configRef = useRef<BackendConfig | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const run = async (): Promise<void> => {
      configRef.current ??= await window.hex.getBackend()
      const next = await checkHealth(configRef.current)
      if (cancelled) return
      setStatus(next)
      if (next.kind === 'misconfigured') return
      timer = setTimeout(run, next.kind === 'connected' ? CONNECTED_POLL_MS : DISCONNECTED_POLL_MS)
    }
    void run()

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [attempt])

  const retry = useCallback(() => {
    setStatus({ kind: 'connecting' })
    setAttempt((n) => n + 1)
  }, [])

  return { status, retry }
}
