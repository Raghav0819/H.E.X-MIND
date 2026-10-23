import { useCallback, useEffect, useState } from 'react'

import type { ApiClient, ChatMessage, ChatMode, Conversation, MessageExchange } from '../../lib/api'

export interface Chat {
  conversations: Conversation[]
  active: Conversation | null
  messages: ChatMessage[]
  /** The message currently being processed (shown optimistically until the reply arrives). */
  pending: { content: string; mode: ChatMode; startedAt: number } | null
  error: string | null
  select: (conversationId: string) => Promise<void>
  startNew: () => void
  send: (content: string, mode: ChatMode) => Promise<MessageExchange | null>
}

export function useChat(api: ApiClient, projectId: string | null): Chat {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [active, setActive] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState<Chat['pending']>(null)
  const [error, setError] = useState<string | null>(null)

  const refreshList = useCallback(async () => {
    if (!projectId) return []
    const list = await api.get<Conversation[]>(`/projects/${projectId}/conversations`)
    setConversations(list)
    return list
  }, [api, projectId])

  const select = useCallback(
    async (conversationId: string) => {
      setError(null)
      try {
        const [conversation, history] = await Promise.all([
          api.get<Conversation>(`/conversations/${conversationId}`),
          api.get<ChatMessage[]>(`/conversations/${conversationId}/messages`)
        ])
        setActive(conversation)
        setMessages(history)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    },
    [api]
  )

  // New project: load its conversations and reopen the most recent one.
  useEffect(() => {
    setActive(null)
    setMessages([])
    setConversations([])
    setError(null)
    if (!projectId) return
    refreshList()
      .then((list) => (list[0] ? select(list[0].id) : undefined))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [projectId, refreshList, select])

  const startNew = useCallback(() => {
    setActive(null)
    setMessages([])
    setError(null)
  }, [])

  const send = useCallback(
    async (content: string, mode: ChatMode) => {
      if (!projectId || pending) return null
      setError(null)
      setPending({ content, mode, startedAt: Date.now() })
      try {
        let conversation = active
        if (!conversation) {
          conversation = await api.post<Conversation>(`/projects/${projectId}/conversations`, {})
          setActive(conversation)
        }
        const exchange = await api.post<MessageExchange>(`/conversations/${conversation.id}/messages`, {
          content,
          mode
        })
        setMessages((prev) => [...prev, exchange.user_message, exchange.assistant_message])
        const list = await refreshList()
        setActive(list.find((c) => c.id === conversation.id) ?? conversation)
        return exchange
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
        return null
      } finally {
        setPending(null)
      }
    },
    [api, projectId, active, pending, refreshList]
  )

  return { conversations, active, messages, pending, error, select, startNew, send }
}
