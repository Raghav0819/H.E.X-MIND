import { useCallback, useEffect, useState } from 'react'

import type { BackendConfig } from '../../../preload/api'
import type { HealthInfo } from '../lib/api'

export type BackendStatus =
  | { kind: 'connecting' }
  | { kind: 'connected'; health: HealthInfo }
  | { kind: 'misconfigured' }
  | { kind: 'unauthorized' }
  | { kind: 'unreachable'; error: string }

const CONNECTED_POLL_MS = 5000
const DISCONNECTED_POLL_MS = 3000
const REQUEST_TIMEOUT_MS = 3000

function isHealthInfo(body: unknown): body is HealthInfo {
  const b = body as Partial<HealthInfo> | null
  return (
    b?.status === 'ok' &&
    typeof b.version === 'string' &&
    (b.db === 'ok' || b.db === 'unavailable') &&
    typeof b.providers === 'object' &&
    b.providers !== null
  )
}

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
    const body: unknown = await response.json()
    if (!isHealthInfo(body)) return { kind: 'unreachable', error: 'Unexpected health response' }
    return { kind: 'connected', health: body }
  } catch (err) {
    return { kind: 'unreachable', error: err instanceof Error ? err.message : String(err) }
  }
}

/** Polls the backend health endpoint; `retry` forces an immediate check. */
export function useBackendHealth(config: BackendConfig): { status: BackendStatus; retry: () => void } {
  const [status, setStatus] = useState<BackendStatus>({ kind: 'connecting' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const run = async (): Promise<void> => {
      const next = await checkHealth(config)
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
  }, [config, attempt])

  const retry = useCallback(() => {
    setStatus({ kind: 'connecting' })
    setAttempt((n) => n + 1)
  }, [])

  return { status, retry }
}
