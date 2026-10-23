import { describe, expect, it, vi } from 'vitest'

import { checkHealth } from './useBackendHealth'

const config = { url: 'http://127.0.0.1:8765', token: 'secret-token-123456' }

const HEALTH = {
  status: 'ok',
  version: '0.1.0',
  db: 'ok',
  providers: { ollama: { provider: 'ollama', available: true, model: 'qwen2.5-coder:7b', detail: null } }
}

function respond(status: number, body: unknown = {}): typeof fetch {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))
}

describe('checkHealth', () => {
  it('reports connected with the health payload and sends the bearer token', async () => {
    const fetchFn = respond(200, HEALTH)
    await expect(checkHealth(config, fetchFn)).resolves.toEqual({ kind: 'connected', health: HEALTH })
    expect(fetchFn).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/health',
      expect.objectContaining({ headers: { Authorization: 'Bearer secret-token-123456' } })
    )
  })

  it('does not call the backend when no token is configured', async () => {
    const fetchFn = respond(200)
    await expect(checkHealth({ ...config, token: null }, fetchFn)).resolves.toEqual({ kind: 'misconfigured' })
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('reports unauthorized on 401', async () => {
    await expect(checkHealth(config, respond(401))).resolves.toEqual({ kind: 'unauthorized' })
  })

  it('reports unreachable on other HTTP errors', async () => {
    await expect(checkHealth(config, respond(500))).resolves.toEqual({ kind: 'unreachable', error: 'HTTP 500' })
  })

  it('reports unreachable on malformed responses', async () => {
    for (const body of [{ status: 'nope' }, { ...HEALTH, db: 'maybe' }, { ...HEALTH, providers: null }]) {
      const result = await checkHealth(config, respond(200, body))
      expect(result.kind).toBe('unreachable')
    }
  })

  it('reports unreachable when the request fails', async () => {
    const fetchFn = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(checkHealth(config, fetchFn)).resolves.toEqual({ kind: 'unreachable', error: 'Failed to fetch' })
  })
})
