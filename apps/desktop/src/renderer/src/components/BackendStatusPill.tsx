import { RotateCw } from 'lucide-react'

import type { BackendStatus } from '../hooks/useBackendHealth'

const LABELS: Record<BackendStatus['kind'], string> = {
  connecting: 'Connecting…',
  connected: 'Backend connected',
  misconfigured: 'Backend token not configured',
  unauthorized: 'Backend rejected token',
  unreachable: 'Backend unreachable'
}

const TONES: Record<BackendStatus['kind'], 'neutral' | 'success' | 'warning' | 'danger'> = {
  connecting: 'neutral',
  connected: 'success',
  misconfigured: 'warning',
  unauthorized: 'danger',
  unreachable: 'danger'
}

function detail(status: BackendStatus): string | undefined {
  switch (status.kind) {
    case 'connected':
      return `Version ${status.version}`
    case 'unreachable':
      return status.error
    case 'misconfigured':
      return 'Set HEXMIND_API_TOKEN in the repository .env file'
    case 'unauthorized':
      return 'The desktop token does not match the backend token'
    default:
      return undefined
  }
}

interface Props {
  status: BackendStatus
  onRetry: () => void
}

export function BackendStatusPill({ status, onRetry }: Props) {
  const canRetry = status.kind !== 'connected' && status.kind !== 'connecting'
  return (
    <div className="status-pill" data-tone={TONES[status.kind]} role="status" title={detail(status)}>
      <span className="status-dot" aria-hidden="true" />
      <span>{LABELS[status.kind]}</span>
      {canRetry && (
        <button
          type="button"
          className="icon-button icon-button--small"
          onClick={onRetry}
          aria-label="Retry backend connection"
          title="Retry"
        >
          <RotateCw size={12} />
        </button>
      )}
    </div>
  )
}
