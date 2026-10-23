import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { BackendStatus } from '../hooks/useBackendHealth'
import { BackendStatusPill } from './BackendStatusPill'

describe('BackendStatusPill', () => {
  it.each<[BackendStatus, string]>([
    [{ kind: 'connecting' }, 'Connecting…'],
    [{ kind: 'connected', version: '0.1.0' }, 'Backend connected'],
    [{ kind: 'misconfigured' }, 'Backend token not configured'],
    [{ kind: 'unauthorized' }, 'Backend rejected token'],
    [{ kind: 'unreachable', error: 'Failed to fetch' }, 'Backend unreachable']
  ])('renders %o as "%s"', (status, label) => {
    render(<BackendStatusPill status={status} onRetry={() => {}} />)
    expect(screen.getByRole('status')).toHaveTextContent(label)
  })

  it('offers retry only when disconnected', () => {
    const onRetry = vi.fn()
    const { rerender } = render(<BackendStatusPill status={{ kind: 'connected', version: '0.1.0' }} onRetry={onRetry} />)
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()

    rerender(<BackendStatusPill status={{ kind: 'unreachable', error: 'down' }} onRetry={onRetry} />)
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('shows the error detail as a tooltip', () => {
    render(<BackendStatusPill status={{ kind: 'unreachable', error: 'Failed to fetch' }} onRetry={() => {}} />)
    expect(screen.getByRole('status')).toHaveAttribute('title', 'Failed to fetch')
  })
})
