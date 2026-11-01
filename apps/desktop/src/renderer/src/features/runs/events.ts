import type { AgentEvent } from '../../generated/events'

/**
 * Merge newly fetched events into the known list: dedupe by seq and keep seq order.
 * Events are append-only and immutable, so a duplicate seq is the same event.
 */
export function mergeEvents(known: AgentEvent[], incoming: AgentEvent[]): AgentEvent[] {
  if (incoming.length === 0) return known
  const bySeq = new Map(known.map((e) => [e.seq, e]))
  for (const event of incoming) {
    if (!bySeq.has(event.seq)) bySeq.set(event.seq, event)
  }
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq)
}

/** Highest seq such that every event 1..seq is present (the safe `after_seq` cursor). */
export function contiguousSeq(events: AgentEvent[]): number {
  let expected = 1
  for (const event of events) {
    if (event.seq !== expected) break
    expected += 1
  }
  return expected - 1
}

export function isStub(event: AgentEvent): boolean {
  return 'stub' in event.payload && event.payload.stub === true
}

/** One-line, human-readable description of an event's payload. */
export function describeEvent(event: AgentEvent): string {
  switch (event.type) {
    case 'run_created':
      return event.payload.title
    case 'run_status_changed':
      return `${event.payload.previous ?? '—'} → ${event.payload.status}`
    case 'router_decided': {
      const p = event.payload
      const confidence = p.confidence === null ? 'n/a' : `${Math.round(p.confidence * 100)}%`
      return `${p.request_type}, ${p.complexity}, ${p.route}${p.strategy ? ` (${p.strategy})` : ''}, confidence ${confidence}${p.fallback_used ? ', fallback' : ''}`
    }
    case 'llm_call_started':
      return `${event.payload.purpose} via ${event.payload.provider}/${event.payload.model}`
    case 'llm_call_completed': {
      const p = event.payload
      const tokens = p.input_tokens === null ? '' : `, ${p.input_tokens}→${p.output_tokens ?? '?'} tokens`
      return `${p.purpose} ${p.ok ? 'ok' : `failed: ${p.error}`} in ${p.latency_ms} ms${tokens}`
    }
    case 'provider_fallback':
      return `${event.payload.from_provider} → ${event.payload.to_provider}: ${event.payload.reason}`
    case 'task_created': {
      const files = event.payload.target_files.length ? ` [${event.payload.target_files.join(', ')}]` : ''
      return `${event.payload.title}${files}`
    }
    case 'task_claimed':
    case 'task_started':
      return event.payload.worker
    case 'tool_called':
      return `${event.payload.tool}${event.payload.ok ? '' : ' (error)'}: ${event.payload.summary ?? ''}`
    case 'check_started':
      return event.payload.name
    case 'check_completed': {
      const p = event.payload
      const result = p.exit_code === null ? 'did not complete' : p.exit_code === 0 ? 'passed' : `failed (exit ${p.exit_code})`
      return `${p.name} ${result}${p.duration_ms ? ` in ${(p.duration_ms / 1000).toFixed(1)}s` : ''}`
    }
    case 'review_started':
      return event.payload.reviewer
    case 'review_completed':
      return `${event.payload.verdict}${event.payload.findings ? `, ${event.payload.findings} finding(s)` : ''}`
    case 'task_completed':
      return event.payload.summary ?? 'completed'
    case 'task_failed':
      return event.payload.error
    case 'task_blocked':
      return event.payload.reason
    case 'diff_ready':
      return `${event.payload.files.length} file(s): ${event.payload.files.join(', ')}`
    case 'run_completed':
      return event.payload.summary ?? 'completed'
    case 'run_failed':
      return event.payload.error
    case 'agent_started': {
      const p = event.payload
      return `${p.agent} [${p.framework} ${p.kind}]${p.parent ? ` in ${p.parent}` : ''}`
    }
    case 'agent_finished': {
      const p = event.payload
      return `${p.agent} [${p.framework}] ${p.ok ? 'done' : 'failed'}${p.duration_ms === null ? '' : ` in ${formatMs(p.duration_ms)}`}`
    }
    case 'callback_fired': {
      const p = event.payload
      return `${p.framework} ${p.hook} (${p.agent})${p.detail ? `: ${p.detail}` : ''}`
    }
    case 'schema_validated': {
      const p = event.payload
      return `${p.agent} → ${p.schema_name}: ${p.status}${p.errors.length ? ` (${p.errors.length} error(s))` : ''}`
    }
    case 'guardrail_triggered':
      return `${event.payload.guardrail} ${event.payload.action}: ${event.payload.reason}`
    case 'a2a_message': {
      const p = event.payload
      return `${p.direction} ${p.direction === 'sent' ? 'to' : 'from'} ${p.peer}${p.task_state ? ` [${p.task_state}]` : ''}${p.summary ? `: ${p.summary}` : ''}`
    }
    case 'prompt_variant_selected':
      return `${event.payload.role}: ${event.payload.variant}`
    default:
      return JSON.stringify(event.payload)
  }
}

export function formatMs(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)}s`
}
