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
    case 'run_completed':
      return event.payload.summary ?? 'completed'
    case 'run_failed':
      return event.payload.error
    default:
      return JSON.stringify(event.payload)
  }
}
