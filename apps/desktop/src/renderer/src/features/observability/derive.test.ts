import { describe, expect, it } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import {
  callbackEvents,
  callbackHook,
  deriveA2AExchanges,
  deriveAgents,
  deriveClaimLog,
  deriveTopology,
  leaseSecondsLeft,
  schemaChecks
} from './derive'

let seq = 0
function ev(type: AgentEvent['type'], payload: object, agent_id: string | null = null, task_id: string | null = null): AgentEvent {
  seq += 1
  return { schema_version: 3, event_id: `e${seq}`, run_id: 'r1', seq, ts: '2026-11-02T10:00:00Z', type, agent_id, task_id, payload } as AgentEvent
}

function runEvents(): AgentEvent[] {
  seq = 0
  return [
    ev('agent_started', { agent: 'run_orchestrator', framework: 'adk', kind: 'sequential', parent: null }),
    ev('agent_started', { agent: 'plan', framework: 'adk', kind: 'custom', parent: 'run_orchestrator' }),
    ev('agent_started', { agent: 'planner', framework: 'crewai', kind: 'crew', parent: 'plan' }, 'planner'),
    ev('callback_fired', { framework: 'crewai', hook: 'step_callback', agent: 'planner', detail: 'AgentAction: read_file' }, 'planner'),
    ev('llm_call_completed', { provider: 'groq', model: 'm', purpose: 'planner', ok: true, latency_ms: 5, input_tokens: 100, output_tokens: 40, attempts: 1, error: null }, 'planner'),
    ev('tool_called', { tool: 'read_file', ok: true, summary: 'README.md' }, 'planner'),
    ev('agent_finished', { agent: 'planner', framework: 'crewai', ok: true, duration_ms: 1500 }, 'planner'),
    ev('schema_validated', { agent: 'planner', schema_name: 'Plan', status: 'repaired', errors: ['bad json'] }, 'planner'),
    ev('task_created', { title: 'Todo model', complexity: 'low', depends_on: [], target_files: [] }, null, 't1'),
    ev('agent_finished', { agent: 'plan', framework: 'adk', ok: true, duration_ms: 1600 }),
    ev('agent_started', { agent: 'execute', framework: 'adk', kind: 'custom', parent: 'run_orchestrator' }),
    ev('task_claimed', { worker: 'coder_01' }, 'coder_01', 't1'),
    ev('agent_started', { agent: 'reflection_loop', framework: 'adk', kind: 'loop', parent: 'execute' }, 'reflection_loop', 't1'),
    ev('agent_started', { agent: 'reviewer', framework: 'adk', kind: 'llm', parent: 'reflection_loop' }, 'reviewer', 't1'),
    ev('callback_fired', { framework: 'adk', hook: 'before_model_callback', agent: 'reviewer', detail: '1 message(s), 0 tool(s)' }, 'reviewer', 't1')
  ]
}

describe('deriveAgents', () => {
  it('tracks status, framework, model usage and tools per agent', () => {
    const agents = new Map(deriveAgents(runEvents()).map((a) => [a.name, a]))
    const planner = agents.get('planner')!
    expect(planner).toMatchObject({
      framework: 'crewai',
      kind: 'crew',
      parent: 'plan',
      active: 0,
      invocations: 1,
      lastDurationMs: 1500,
      llmCalls: 1,
      inputTokens: 100,
      outputTokens: 40,
      toolCalls: 1,
      callbacks: 1
    })
    expect(agents.get('reviewer')).toMatchObject({ framework: 'adk', active: 1, lastActivity: 'before_model_callback: 1 message(s), 0 tool(s)' })
    expect(agents.get('execute')!.active).toBe(1)
  })

  it('marks agents whose last invocation failed', () => {
    seq = 0
    const events = [
      ev('agent_started', { agent: 'coder', framework: 'adk', kind: 'custom', parent: null }),
      ev('agent_finished', { agent: 'coder', framework: 'adk', ok: false, duration_ms: 10 })
    ]
    expect(deriveAgents(events)[0]).toMatchObject({ active: 0, lastFailed: true })
    expect(deriveTopology(events)[0]).toMatchObject({ active: false, failed: true })
  })
})

describe('deriveTopology', () => {
  it('builds the tree that actually ran from recorded parents', () => {
    const [root, ...others] = deriveTopology(runEvents())
    expect(others).toEqual([])
    expect(root.name).toBe('run_orchestrator')
    expect(root.children.map((c) => c.name)).toEqual(['plan', 'execute'])
    const [plan, execute] = root.children
    expect(plan.children.map((c) => [c.name, c.framework, c.active])).toEqual([['planner', 'crewai', false]])
    expect(execute.children[0].name).toBe('reflection_loop')
    expect(execute.children[0].children[0]).toMatchObject({ name: 'reviewer', active: true })
  })
})

describe('Blackboard and callbacks', () => {
  it('lists claims in order with the acting worker', () => {
    const log = deriveClaimLog(runEvents())
    expect(log.map((l) => [l.action, l.worker, l.detail])).toEqual([
      ['created', 'planner', 'Todo model'],
      ['claimed', 'coder_01', '']
    ])
  })

  it('names before/after agent callbacks and keeps framework hooks', () => {
    const hooks = callbackEvents(runEvents()).map(callbackHook)
    expect(hooks.slice(0, 4)).toEqual(['before_agent_callback', 'before_agent_callback', 'before_kickoff', 'step_callback'])
    expect(hooks).toContain('after_kickoff')
  })

  it('collects schema checks', () => {
    expect(schemaChecks(runEvents()).map((c) => c.payload.status)).toEqual(['repaired'])
  })

  it('counts a lease down and never below zero', () => {
    const now = Date.parse('2026-11-02T10:00:00Z')
    expect(leaseSecondsLeft('2026-11-02T10:01:30Z', now)).toBe(90)
    expect(leaseSecondsLeft('2026-11-02T09:59:00Z', now)).toBe(0)
    expect(leaseSecondsLeft(null, now)).toBeNull()
  })
})

describe('deriveA2AExchanges', () => {
  it('joins both sides of an exchange with its lifecycle and shared trace', () => {
    seq = 0
    const msg = (side: 'client' | 'server', direction: 'sent' | 'received', task_state: string | null, extra: object = {}) =>
      ev('a2a_message', {
        side,
        direction,
        agent: side === 'client' ? 'orchestrator' : 'coder_crew',
        peer: side === 'client' ? 'coder_crew' : 'orchestrator',
        exchange_id: 'x1',
        a2a_task_id: side === 'server' || direction === 'received' ? 'a2a-1' : null,
        context_id: null,
        task_state,
        trace_id: 'trace-1',
        duration_ms: null,
        summary: null,
        ...extra
      }, 'coder_crew', 't1')
    const [exchange, ...rest] = deriveA2AExchanges([
      msg('client', 'sent', null),
      msg('server', 'received', 'submitted'),
      msg('server', 'sent', 'working'),
      msg('server', 'sent', 'completed'),
      msg('client', 'received', 'completed', { duration_ms: 4200, trace_id: null })
    ])
    expect(rest).toEqual([])
    expect(exchange).toMatchObject({ crew: 'coder_crew', a2aTaskId: 'a2a-1', taskId: 't1', state: 'completed', durationMs: 4200, traceShared: true })
    expect(exchange.steps.map((s) => s.state)).toEqual([null, 'submitted', 'working', 'completed', 'completed'])
  })
})
