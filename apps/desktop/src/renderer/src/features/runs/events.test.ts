import { describe, expect, it } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import { contiguousSeq, describeEvent, isStub, mergeEvents } from './events'

function statusEvent(seq: number, status = 'executing', stub = true): AgentEvent {
  return {
    schema_version: 1,
    event_id: `e${seq}`,
    run_id: 'r1',
    seq,
    ts: '2026-10-23T10:00:00Z',
    type: 'run_status_changed',
    agent_id: null,
    task_id: null,
    payload: { status, previous: 'queued', stub }
  }
}

describe('mergeEvents', () => {
  it('dedupes by seq and keeps order regardless of arrival order', () => {
    const merged = mergeEvents([statusEvent(1), statusEvent(3)], [statusEvent(3), statusEvent(2), statusEvent(1)])
    expect(merged.map((e) => e.seq)).toEqual([1, 2, 3])
  })

  it('returns the same array when nothing new arrives', () => {
    const known = [statusEvent(1)]
    expect(mergeEvents(known, [])).toBe(known)
  })
})

describe('contiguousSeq', () => {
  it('stops at the first gap', () => {
    expect(contiguousSeq([])).toBe(0)
    expect(contiguousSeq([statusEvent(1), statusEvent(2)])).toBe(2)
    expect(contiguousSeq([statusEvent(1), statusEvent(3)])).toBe(1)
    expect(contiguousSeq([statusEvent(2)])).toBe(0)
  })
})

describe('describeEvent', () => {
  it('summarizes known event types and flags stubs', () => {
    expect(describeEvent(statusEvent(1))).toBe('queued → executing')
    expect(isStub(statusEvent(1))).toBe(true)
    expect(isStub(statusEvent(1, 'executing', false))).toBe(false)

    const routed: AgentEvent = {
      ...statusEvent(2),
      type: 'router_decided',
      payload: {
        request_type: 'code_edit',
        complexity: 'medium',
        confidence: 0.82,
        route: 'run',
        strategy: 'plan_execute_review',
        fallback_used: false
      }
    }
    expect(describeEvent(routed)).toBe('code_edit, medium, run (plan_execute_review), confidence 82%')
    expect(isStub(routed)).toBe(false)
  })
})
