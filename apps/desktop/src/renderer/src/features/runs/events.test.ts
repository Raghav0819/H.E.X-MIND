import { describe, expect, it } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import { contiguousSeq, describeEvent, isStub, mergeEvents } from './events'

function statusEvent(seq: number, status = 'executing', stub = true): AgentEvent {
  return {
    schema_version: 2,
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

describe('describeEvent for monitoring events', () => {
  const base = { schema_version: 2 as const, event_id: 'e', run_id: 'r1', seq: 1, ts: '2026-10-23T10:00:00Z', agent_id: null, task_id: null }

  it('describes callbacks, agents and schema checks', () => {
    expect(
      describeEvent({ ...base, type: 'callback_fired', payload: { framework: 'adk', hook: 'after_model_callback', agent: 'reviewer', detail: 'groq/m' } })
    ).toBe('adk after_model_callback (reviewer): groq/m')
    expect(
      describeEvent({ ...base, type: 'agent_finished', payload: { agent: 'planner', framework: 'crewai', ok: true, duration_ms: 2500 } })
    ).toBe('planner [crewai] done in 2.5s')
    expect(
      describeEvent({ ...base, type: 'schema_validated', payload: { agent: 'reviewer', schema_name: 'ReviewResult', status: 'repaired', errors: ['x'] } })
    ).toBe('reviewer → ReviewResult: repaired (1 error(s))')
  })
})
