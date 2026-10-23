import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient, type ChatMessage, type Conversation } from '../../lib/api'
import { useChat } from './useChat'

const CONVERSATION: Conversation = {
  id: 'c1',
  project_id: 'p1',
  title: 'New conversation',
  summary: null,
  created_at: '',
  updated_at: ''
}

function message(id: string, role: ChatMessage['role'], content: string): ChatMessage {
  return { id, conversation_id: 'c1', role, mode: 'ask', content, metadata: {}, created_at: '' }
}

function fakeApi(overrides: Partial<Record<'get' | 'post', ReturnType<typeof vi.fn>>> = {}) {
  const get = vi.fn(async (path: string) => {
    if (path === '/projects/p1/conversations') return []
    throw new Error(`unexpected GET ${path}`)
  })
  const post = vi.fn(async (path: string) => {
    if (path === '/projects/p1/conversations') return CONVERSATION
    if (path === '/conversations/c1/messages') {
      return {
        user_message: message('m1', 'user', 'hi'),
        assistant_message: message('m2', 'assistant', 'hello'),
        run_id: null
      }
    }
    throw new Error(`unexpected POST ${path}`)
  })
  return { get, post, put: vi.fn(), ...overrides } as unknown as ApiClient & {
    get: typeof get
    post: typeof post
  }
}

describe('useChat', () => {
  it('creates a conversation on first send and appends the exchange', async () => {
    const api = fakeApi()
    const { result } = renderHook(() => useChat(api, 'p1'))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/projects/p1/conversations'))

    await act(() => result.current.send('hi', 'ask'))

    expect(api.post).toHaveBeenNthCalledWith(1, '/projects/p1/conversations', {})
    expect(api.post).toHaveBeenNthCalledWith(2, '/conversations/c1/messages', { content: 'hi', mode: 'ask' })
    expect(result.current.messages.map((m) => m.content)).toEqual(['hi', 'hello'])
    expect(result.current.active?.id).toBe('c1')
    expect(result.current.pending).toBeNull()
  })

  it('reopens the most recent conversation for a project', async () => {
    const api = fakeApi({
      get: vi.fn(async (path: string) => {
        if (path === '/projects/p1/conversations') return [CONVERSATION]
        if (path === '/conversations/c1') return CONVERSATION
        if (path === '/conversations/c1/messages') return [message('m1', 'user', 'earlier')]
        throw new Error(path)
      })
    })
    const { result } = renderHook(() => useChat(api, 'p1'))
    await waitFor(() => expect(result.current.messages.map((m) => m.content)).toEqual(['earlier']))
    expect(result.current.active?.id).toBe('c1')
  })

  it('reports failures and returns null so the draft can be kept', async () => {
    const api = fakeApi({
      post: vi.fn(async (path: string) => {
        if (path === '/projects/p1/conversations') return CONVERSATION
        throw new ApiError(500, 'HTTP 500', null)
      })
    })
    const { result } = renderHook(() => useChat(api, 'p1'))

    let exchange: unknown
    await act(async () => {
      exchange = await result.current.send('hi', 'edit')
    })

    expect(exchange).toBeNull()
    expect(result.current.error).toBe('HTTP 500')
    expect(result.current.pending).toBeNull()
  })

  it('does nothing without a project', async () => {
    const api = fakeApi()
    const { result } = renderHook(() => useChat(api, null))
    await act(async () => {
      await result.current.send('hi', 'ask')
    })
    expect(api.post).not.toHaveBeenCalled()
  })
})
