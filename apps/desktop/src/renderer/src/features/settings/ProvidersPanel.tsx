import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { EmptyState, PanelHeader } from '../../components/Panel'
import type { ApiClient, LlmTestResult, ProvidersInfo } from '../../lib/api'
import { PROVIDER_LABELS } from '../workspace/Welcome'

interface Props {
  api: ApiClient
}

/** Model providers: policy order, health, quota cooldowns and a one-call connectivity test.
 * API keys are configured in the backend .env and never shown here. */
export function ProvidersPanel({ api }: Props) {
  const [info, setInfo] = useState<ProvidersInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tests, setTests] = useState<Record<string, LlmTestResult | 'running'>>({})

  const load = useCallback(async () => {
    try {
      setInfo(await api.get<ProvidersInfo>('/providers'))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const test = async (name: string) => {
    setTests((t) => ({ ...t, [name]: 'running' }))
    try {
      const result = await api.post<LlmTestResult>(`/providers/${name}/test`)
      setTests((t) => ({ ...t, [name]: result }))
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setTests((t) => ({
        ...t,
        [name]: { provider: name, model: '', content: null, latency_ms: 0, input_tokens: null, output_tokens: null, error: message }
      }))
    }
    void load()
  }

  return (
    <>
      <PanelHeader
        title="Model providers"
        actions={
          <button type="button" className="icon-button" aria-label="Refresh providers" title="Refresh" onClick={() => void load()}>
            <RefreshCw size={14} />
          </button>
        }
      />
      {error ? (
        <EmptyState title="Could not load providers">{error}</EmptyState>
      ) : !info ? (
        <EmptyState title="Loading…" />
      ) : (
        <div className="providers">
          <p className="providers__order">
            Order: {info.order.map((n) => PROVIDER_LABELS[n] ?? n).join(' → ')}
          </p>
          <ul className="providers__list">
            {Object.entries(info.providers).map(([name, p]) => {
              const result = tests[name]
              const state = p.cooldown_s > 0 ? 'cooldown' : p.health.available ? 'ready' : p.health.configured === false ? 'missing' : 'down'
              return (
                <li key={name} className="provider" data-state={state}>
                  <div className="provider__head">
                    <span className="status-dot" aria-hidden="true" />
                    <span className="provider__name">{PROVIDER_LABELS[name] ?? name}</span>
                    <span className="provider__model mono">{p.health.model}</span>
                  </div>
                  <div className="provider__detail">
                    {state === 'ready' && 'Ready'}
                    {state === 'missing' && (p.health.detail ?? 'Not configured')}
                    {state === 'down' && (p.health.detail ?? 'Unavailable')}
                    {state === 'cooldown' && `Skipped for ${p.cooldown_s}s: ${p.cooldown_reason}`}
                  </div>
                  {Object.keys(p.rate_limit).length > 0 && (
                    <div className="provider__limits mono" title="Latest rate-limit headers from the provider">
                      {Object.entries(p.rate_limit)
                        .filter(([k]) => k.startsWith('remaining'))
                        .map(([k, v]) => `${k.replace('remaining-', '')}: ${v}`)
                        .join(' · ')}
                    </div>
                  )}
                  <div className="provider__actions">
                    <button
                      type="button"
                      className="button button--small"
                      disabled={state === 'missing' || result === 'running'}
                      onClick={() => void test(name)}
                    >
                      {result === 'running' ? 'Testing…' : 'Test'}
                    </button>
                    {result && result !== 'running' && (
                      <span className="provider__test" data-ok={!result.error}>
                        {result.error
                          ? `Failed: ${result.error.slice(0, 120)}`
                          : `OK in ${(result.latency_ms / 1000).toFixed(1)}s (“${(result.content ?? '').trim().slice(0, 20)}”)`}
                      </span>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
          <p className="providers__hint">
            Add API keys as <code>HEXMIND_GROQ_API_KEY</code> / <code>HEXMIND_GEMINI_API_KEY</code> in the
            project <code>.env</code> and restart the backend. Keys are never shown in the app.
          </p>
        </div>
      )}
    </>
  )
}
