import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ChatMessage } from '../../lib/api'
import { ChatPanel } from './ChatPanel'
import { MessageView } from './MessageView'
import type { Chat } from './useChat'

function fakeChat(overrides: Partial<Chat> = {}): Chat {
  return {
    conversations: [],
    active: null,
    messages: [],
    pending: null,
    error: null,
    select: vi.fn(),
    startNew: vi.fn(),
    send: vi.fn().mockResolvedValue({}),
    ...overrides
  }
}

const ASSISTANT: ChatMessage = {
  id: 'm2',
  conversation_id: 'c1',
  role: 'assistant',
  mode: null,
  content: 'Started a **medium** run.',
  created_at: '',
  metadata: {
    kind: 'run_started',
    run_id: 'r1',
    llm: null,
    route: {
      route: 'run',
      request_type: 'code_edit',
      complexity: 'medium',
      confidence: 0.82,
      strategy: 'plan_execute_review',
      fallback_used: true,
      policy_note: null,
      reason: 'several files',
      decision_id: 'd1'
    },
    context: {
      files: [{ path: 'src/app.ts', reason: 'mentioned', truncated: false }],
      omitted_files: [],
      messages: 0,
      summary: false,
      prior_runs: 0
    }
  }
}

describe('ChatPanel', () => {
  it('sends the draft with the selected mode on Enter', () => {
    const chat = fakeChat()
    render(<ChatPanel chat={chat} enabled disabledReason="" onOpenRun={() => {}} onOpenFile={() => {}} />)

    fireEvent.click(screen.getByRole('radio', { name: 'Edit' }))
    expect(screen.getByRole('radio', { name: 'Edit' })).toHaveAttribute('aria-checked', 'true')
    const input = screen.getByRole('textbox', { name: 'Message' })
    fireEvent.change(input, { target: { value: '  Add dark mode  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(chat.send).toHaveBeenCalledWith('Add dark mode', 'edit')
  })

  it('Shift+Enter does not send', () => {
    const chat = fakeChat()
    render(<ChatPanel chat={chat} enabled disabledReason="" onOpenRun={() => {}} onOpenFile={() => {}} />)
    const input = screen.getByRole('textbox', { name: 'Message' })
    fireEvent.change(input, { target: { value: 'line one' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(chat.send).not.toHaveBeenCalled()
  })

  it('is disabled with a reason when no workspace is open', () => {
    render(
      <ChatPanel
        chat={fakeChat()}
        enabled={false}
        disabledReason="Open a workspace first."
        onOpenRun={() => {}}
        onOpenFile={() => {}}
      />
    )
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled()
    expect(screen.getByText('Open a workspace first.')).toBeInTheDocument()
  })

  it('shows the pending message and progress while waiting', () => {
    const chat = fakeChat({ pending: { content: 'Explain x', mode: 'ask', startedAt: Date.now() } })
    render(<ChatPanel chat={chat} enabled disabledReason="" onOpenRun={() => {}} onOpenFile={() => {}} />)
    expect(screen.getByText('Explain x')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Routing and thinking…')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
})

describe('MessageView', () => {
  it('shows route, fallback, context files and the run link', () => {
    const onOpenRun = vi.fn()
    const onOpenFile = vi.fn()
    render(<MessageView message={ASSISTANT} onOpenRun={onOpenRun} onOpenFile={onOpenFile} />)

    expect(screen.getByText('medium', { selector: 'strong' })).toBeInTheDocument() // markdown
    expect(screen.getByText('confidence 82%')).toBeInTheDocument()
    expect(screen.getByText('fallback')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /src\/app.ts/ }))
    expect(onOpenFile).toHaveBeenCalledWith('src/app.ts')
    fireEvent.click(screen.getByRole('button', { name: /View run events/ }))
    expect(onOpenRun).toHaveBeenCalledWith('r1')
  })

  it('does not render raw HTML from model output', () => {
    const { container } = render(
      <MessageView
        message={{ ...ASSISTANT, content: 'hi <img src=x onerror="alert(1)">' }}
        onOpenRun={() => {}}
        onOpenFile={() => {}}
      />
    )
    expect(container.querySelector('img')).toBeNull()
  })
})
