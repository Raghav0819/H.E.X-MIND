import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ApiClient, ProvidersInfo } from '../../lib/api'
import { ProvidersPanel } from './ProvidersPanel'

const INFO: ProvidersInfo = {
  order: ['groq', 'gemini', 'ollama'],
  order_by_complexity: {},
  providers: {
    ollama: {
      health: { provider: 'ollama', available: true, model: 'qwen2.5-coder:7b', configured: true, detail: null },
      order_position: 2,
      cooldown_s: 0,
      cooldown_reason: null,
      rate_limit: {}
    },
    groq: {
      health: { provider: 'groq', available: true, model: 'llama-3.3-70b-versatile', configured: true, detail: null },
      order_position: 0,
      cooldown_s: 240,
      cooldown_reason: 'quota exhausted',
      rate_limit: { 'remaining-requests': '0', 'reset-requests': '4m' }
    },
    gemini: {
      health: { provider: 'gemini', available: false, model: 'gemini-2.5-flash', configured: false, detail: 'no API key (set HEXMIND_GEMINI_API_KEY)' },
      order_position: 1,
      cooldown_s: 0,
      cooldown_reason: null,
      rate_limit: {}
    }
  }
}

describe('ProvidersPanel', () => {
  it('shows order, readiness, cooldowns and missing keys', async () => {
    const api = { get: vi.fn().mockResolvedValue(INFO), post: vi.fn(), put: vi.fn() } as unknown as ApiClient
    render(<ProvidersPanel api={api} />)

    expect(await screen.findByText('Order: Groq → Gemini → Ollama (local)')).toBeInTheDocument()
    expect(screen.getByText('Skipped for 240s: quota exhausted')).toBeInTheDocument()
    expect(screen.getByText('requests: 0')).toBeInTheDocument()
    expect(screen.getByText('no API key (set HEXMIND_GEMINI_API_KEY)')).toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeInTheDocument()
  })

  it('runs a provider test and shows the real result', async () => {
    const post = vi.fn().mockResolvedValue({
      provider: 'ollama', model: 'qwen2.5-coder:7b', content: 'ready', latency_ms: 2300,
      input_tokens: 30, output_tokens: 2, error: null
    })
    const api = { get: vi.fn().mockResolvedValue(INFO), post, put: vi.fn() } as unknown as ApiClient
    render(<ProvidersPanel api={api} />)

    const buttons = await screen.findAllByRole('button', { name: 'Test' })
    expect(buttons.filter((b) => (b as HTMLButtonElement).disabled)).toHaveLength(1) // gemini: no key
    fireEvent.click(buttons[0])
    expect(await screen.findByText('OK in 2.3s (“ready”)')).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/providers/ollama/test')
  })
})
