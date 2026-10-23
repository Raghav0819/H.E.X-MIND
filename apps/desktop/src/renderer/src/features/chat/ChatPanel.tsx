import { Plus, Send } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

import { EmptyState, PanelHeader } from '../../components/Panel'
import type { ChatMode } from '../../lib/api'
import { MessageView } from './MessageView'
import type { Chat } from './useChat'

const MODES: { id: ChatMode; label: string; hint: string }[] = [
  { id: 'ask', label: 'Ask', hint: 'Answer questions; never changes files' },
  { id: 'edit', label: 'Edit', hint: 'Agents may plan and change files' },
  { id: 'auto', label: 'Auto', hint: 'The Router decides, and asks when unsure' }
]

interface Props {
  chat: Chat
  enabled: boolean
  disabledReason: string
  onOpenRun: (runId: string) => void
  onOpenFile: (path: string) => void
}

export function ChatPanel({ chat, enabled, disabledReason, onOpenRun, onOpenFile }: Props) {
  const [draft, setDraft] = useState('')
  const [mode, setMode] = useState<ChatMode>('ask')
  const listRef = useRef<HTMLDivElement>(null)
  const elapsed = useElapsedSeconds(chat.pending?.startedAt ?? null)

  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [chat.messages.length, chat.pending])

  const submit = async () => {
    const content = draft.trim()
    if (!content || !enabled || chat.pending) return
    setDraft('')
    const exchange = await chat.send(content, mode)
    if (!exchange) setDraft(content) // keep the text so it can be retried
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <div className="chat">
      <PanelHeader
        title="Agent Chat"
        actions={
          <button
            type="button"
            className="icon-button"
            aria-label="New conversation"
            title="New conversation"
            disabled={!enabled}
            onClick={chat.startNew}
          >
            <Plus size={14} />
          </button>
        }
      />
      {chat.conversations.length > 0 && (
        <select
          className="chat__select"
          aria-label="Conversation"
          value={chat.active?.id ?? ''}
          onChange={(e) => (e.target.value ? void chat.select(e.target.value) : chat.startNew())}
        >
          <option value="">New conversation</option>
          {chat.conversations.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
      )}

      <div className="chat__messages" ref={listRef} aria-live="polite">
        {!enabled ? (
          <EmptyState title="Chat is unavailable">{disabledReason}</EmptyState>
        ) : chat.messages.length === 0 && !chat.pending ? (
          <EmptyState title="Ask about this project">
            Ask mode answers using the current files. Edit mode starts an agent run.
          </EmptyState>
        ) : (
          chat.messages.map((m) => (
            <MessageView key={m.id} message={m} onOpenRun={onOpenRun} onOpenFile={onOpenFile} />
          ))
        )}
        {chat.pending && (
          <>
            <div className="msg msg--user">
              <div className="msg__meta">
                You<span className="msg__mode">{chat.pending.mode}</span>
              </div>
              <div className="msg__body msg__body--plain">{chat.pending.content}</div>
            </div>
            <div className="msg msg--assistant msg--pending" role="status">
              Routing and thinking… {elapsed}s
            </div>
          </>
        )}
      </div>

      {chat.error && (
        <div className="banner banner--danger" role="alert">
          <span>{chat.error}</span>
        </div>
      )}

      <div className="composer">
        <div className="segmented" role="radiogroup" aria-label="Mode">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={mode === m.id}
              className="segmented__item"
              title={m.hint}
              onClick={() => setMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className="composer__row">
          <textarea
            className="composer__input"
            aria-label="Message"
            placeholder={enabled ? 'Message the agents (Enter to send, Shift+Enter for a new line)' : disabledReason}
            value={draft}
            disabled={!enabled}
            rows={3}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button
            type="button"
            className="icon-button composer__send"
            aria-label="Send"
            title="Send"
            disabled={!enabled || !draft.trim() || chat.pending !== null}
            onClick={() => void submit()}
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}

function useElapsedSeconds(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (startedAt === null) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [startedAt])
  return startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000))
}
