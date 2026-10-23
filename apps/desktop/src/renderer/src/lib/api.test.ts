import { describe, expect, it, vi } from 'vitest'

import { ApiError, createApiClient } from './api'

const config = { url: 'http://127.0.0.1:8765', token: 'secret-token-123456' }

function respond(status: number, body?: unknown) {
  return vi.fn<typeof fetch>().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), { status })
  )
}

describe('createApiClient', () => {
  it('sends the bearer token and query parameters', async () => {
    const fetchFn = respond(200, [{ name: 'src' }])
    const api = createApiClient(config, fetchFn)

    await expect(api.get('/projects/p1/tree', { path: 'src/a b', skip: undefined })).resolves.toEqual([
      { name: 'src' }
    ])
    const [url, init] = fetchFn.mock.calls[0]
    expect(String(url)).toBe('http://127.0.0.1:8765/api/projects/p1/tree?path=src%2Fa+b')
    expect(init?.headers).toEqual({ Authorization: 'Bearer secret-token-123456' })
  })

  it('serializes JSON bodies', async () => {
    const fetchFn = respond(200, { hash: 'h' })
    await createApiClient(config, fetchFn).put('/projects/p1/file', { path: 'a', content: 'x' })
    const [, init] = fetchFn.mock.calls[0]
    expect(init?.method).toBe('PUT')
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' })
    expect(init?.body).toBe('{"path":"a","content":"x"}')
  })

  it('throws ApiError with the backend detail and body', async () => {
    const api = createApiClient(config, respond(409, { detail: 'file changed on disk', current_hash: 'abc' }))
    const error = await api.put('/x', {}).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 409,
      message: 'file changed on disk',
      body: { current_hash: 'abc' }
    })
  })

  it('falls back to the status code when there is no detail', async () => {
    const api = createApiClient(config, respond(500))
    await expect(api.get('/x')).rejects.toMatchObject({ status: 500, message: 'HTTP 500' })
  })
})
