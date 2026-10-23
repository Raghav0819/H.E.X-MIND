import { AlertTriangle, FileText, GitBranch, HelpCircle, Play } from 'lucide-react'
import Markdown from 'react-markdown'

import type { ChatMessage } from '../../lib/api'

interface Props {
  message: ChatMessage
  onOpenRun: (runId: string) => void
  onOpenFile: (path: string) => void
}

const REASON_LABEL = { mentioned: 'mentioned', prior_run: 'changed earlier', search: 'search match' } as const

export function MessageView({ message, onOpenRun, onOpenFile }: Props) {
  if (message.role === 'user') {
    return (
      <div className="msg msg--user">
        <div className="msg__meta">
          You{message.mode && <span className="msg__mode">{message.mode}</span>}
        </div>
        <div className="msg__body msg__body--plain">{message.content}</div>
      </div>
    )
  }

  const { kind, route, context, llm, run_id: runId } = message.metadata
  return (
    <div className="msg msg--assistant" data-kind={kind}>
      <div className="msg__meta">
        {kind === 'clarification' && <HelpCircle size={12} aria-hidden="true" />}
        {kind === 'error' && <AlertTriangle size={12} aria-hidden="true" />}
        {kind === 'run_started' && <Play size={12} aria-hidden="true" />}
        H.E.X Mind
        {llm && (
          <span className="msg__llm" title={`${llm.provider} · ${llm.input_tokens ?? '?'} in / ${llm.output_tokens ?? '?'} out tokens`}>
            {llm.model} · {(llm.latency_ms / 1000).toFixed(1)}s
          </span>
        )}
      </div>

      <div className="msg__body markdown">
        <Markdown>{message.content}</Markdown>
      </div>

      {runId && (
        <button type="button" className="button button--small msg__run" onClick={() => onOpenRun(runId)}>
          <GitBranch size={12} />
          View run events
        </button>
      )}

      {route && (
        <div className="msg__route" title={route.reason}>
          <span className="chip">{route.request_type}</span>
          <span className="chip">{route.complexity}</span>
          {route.strategy && <span className="chip">{route.strategy}</span>}
          <span className="chip">
            confidence {route.confidence === null ? 'n/a' : `${Math.round(route.confidence * 100)}%`}
          </span>
          {route.fallback_used && (
            <span className="chip chip--warning" title="The Router's output was invalid; a conservative fallback route was used">
              fallback
            </span>
          )}
          {route.policy_note && <span className="msg__note">{route.policy_note}</span>}
        </div>
      )}

      {context && context.files.length > 0 && (
        <div className="msg__context" aria-label="Files used as context">
          {context.files.map((file) => (
            <button
              key={file.path}
              type="button"
              className="chip chip--file"
              title={`${REASON_LABEL[file.reason]}${file.truncated ? ' (truncated)' : ''}: open in editor`}
              onClick={() => onOpenFile(file.path)}
            >
              <FileText size={11} />
              {file.path}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
