import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import type { ApiClient, Task } from '../../lib/api'
import { ObservabilityView } from './ObservabilityView'

const TASKS: Task[] = [
  {
    id: 't1',
    run_id: 'r1',
    title: 'Todo model',
    description: '',
    acceptance_criteria: [],
    target_files: ['src/todos.js'],
    status: 'completed',
    complexity: 'low',
    priority: 0,
    claimed_by: 'coder_01',
    claimed_at: null,
    lease_expires_at: null,
    attempts: 1,
    max_attempts: 3,
    created_at: '',
    updated_at: '',
    depends_on: []
  },
  {
    id: 't2',
    run_id: 'r1',
    title: 'Filter helper',
    description: '',
    acceptance_criteria: [],
    target_files: [],
    status: 'running',
    complexity: 'low',
    priority: 0,
    claimed_by: 'coder_02',
    claimed_at: null,
    lease_expires_at: new Date(Date.now() + 120_000).toISOString(),
    attempts: 1,
    max_attempts: 3,
    created_at: '',
    updated_at: '',
    depends_on: ['t1']
  }
]

const base = { schema_version: 3 as const, run_id: 'r1', ts: '2026-11-02T10:00:00Z', agent_id: null, task_id: null }
const EVENTS: AgentEvent[] = [
  { ...base, event_id: 'e1', seq: 1, type: 'agent_started', payload: { agent: 'reviewer', framework: 'adk', kind: 'llm', parent: null } },
  { ...base, event_id: 'e2', seq: 2, type: 'callback_fired', payload: { framework: 'adk', hook: 'after_model_callback', agent: 'reviewer', detail: 'groq/m' } },
  { ...base, event_id: 'e3', seq: 3, type: 'agent_started', payload: { agent: 'coder_02', framework: 'crewai', kind: 'crew', parent: 'coder' } },
  { ...base, event_id: 'e4', seq: 4, type: 'schema_validated', payload: { agent: 'reviewer', schema_name: 'ReviewResult', status: 'fallback', errors: ['provider error: quota'] } },
  {
    ...base,
    event_id: 'e5',
    seq: 5,
    type: 'a2a_message',
    payload: { direction: 'sent', side: 'client', agent: 'orchestrator', peer: 'coder_crew', exchange_id: 'x1', a2a_task_id: null, context_id: null, task_state: null, trace_id: 't', duration_ms: null, summary: 'Implement it' }
  },
  {
    ...base,
    event_id: 'e6',
    seq: 6,
    type: 'a2a_message',
    payload: { direction: 'received', side: 'server', agent: 'coder_crew', peer: 'orchestrator', exchange_id: 'x1', a2a_task_id: 'a2a-1', context_id: 'c', task_state: 'submitted', trace_id: 't', duration_ms: null, summary: null }
  }
]

function api(): ApiClient {
  return {
    get: vi.fn(async (path: string) => {
      if (path === '/tasks') return TASKS
      if (path === '/runs/r1/events') return EVENTS
      if (path === '/a2a/agents')
        return [
          {
            role: 'coder',
            reachable: true,
            card: { name: 'coder_crew', description: 'CrewAI Coder crew', url: 'http://127.0.0.1:8766/coder/', version: '0.1.0', skills: [{ id: 'code', name: 'Implement a task', description: '' }] }
          }
        ]
      return { id: 'r1', title: 'Build todo', status: 'executing', strategy: 'plan_execute_review', last_event_seq: 4 }
    }),
    post: vi.fn(),
    put: vi.fn()
  } as unknown as ApiClient
}

describe('ObservabilityView', () => {
  it('shows the live Blackboard with workers, leases and dependencies', async () => {
    render(<ObservabilityView api={api()} runId="r1" />)
    expect(await screen.findByText('Filter helper')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Running' })).toHaveTextContent('coder_02')
    expect(screen.getByRole('region', { name: 'Completed' })).toHaveTextContent('Todo model')
    expect(screen.getByText(/^lease \d:\d\d$/)).toBeInTheDocument()
    expect(screen.getByText('waits for Todo model')).toBeInTheDocument()
  })

  it('switches to callbacks, agents and schema checks', async () => {
    render(<ObservabilityView api={api()} runId="r1" />)
    await screen.findByText('Filter helper')

    fireEvent.click(screen.getByRole('tab', { name: 'Callbacks' }))
    expect(await screen.findByText('after_model_callback')).toBeInTheDocument()
    expect(screen.getAllByText('ADK').length).toBeGreaterThan(0)
    expect(screen.getAllByText('CrewAI').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('tab', { name: 'Agents' }))
    expect(screen.getByRole('list', { name: 'Agents' })).toHaveTextContent('reviewer')
    expect(screen.getByText('coder_02')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'Schema checks' }))
    expect(screen.getByText('provider error: quota')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'Topology' }))
    expect(screen.getByRole('tree', { name: 'Agent topology' })).toHaveTextContent('reviewer')
  })

  it('shows agent cards and A2A exchanges', async () => {
    render(<ObservabilityView api={api()} runId="r1" />)
    await screen.findByText('Filter helper')
    fireEvent.click(screen.getByRole('tab', { name: 'A2A' }))
    expect(await screen.findByText('http://127.0.0.1:8766/coder/')).toBeInTheDocument()
    expect(screen.getByText('Implement a task')).toBeInTheDocument()
    const exchanges = screen.getByRole('region', { name: 'A2A exchanges' })
    expect(exchanges).toHaveTextContent('orchestrator → coder_crew')
    expect(exchanges).toHaveTextContent('A2A task a2a-1')
    expect(exchanges).toHaveTextContent('one trace across A2A')
  })
})
