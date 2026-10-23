import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import type { ApiClient, Task } from '../../lib/api'
import { describeEvent } from './events'
import { TasksPanel } from './TasksPanel'

const TASK: Task = {
  id: 't1',
  run_id: 'r1',
  title: 'Filter helper',
  description: 'Filter todos',
  acceptance_criteria: ['filters'],
  target_files: ['src/filter.js', 'src/filter.test.js'],
  status: 'review',
  complexity: 'low',
  priority: 0,
  claimed_by: 'coder_01',
  attempts: 2,
  max_attempts: 3,
  created_at: '',
  updated_at: ''
}

describe('TasksPanel', () => {
  it('shows each task with its real status, worker and attempts', async () => {
    const api = {
      get: vi.fn(async (path: string) => (path === '/tasks' ? [TASK] : { id: 'r1', status: 'awaiting_approval' })),
      post: vi.fn(),
      put: vi.fn()
    } as unknown as ApiClient
    render(<TasksPanel api={api} runId="r1" />)

    expect(await screen.findByText('Filter helper')).toBeInTheDocument()
    expect(screen.getByText('review')).toHaveAttribute('data-status', 'review')
    expect(screen.getByText('coder_01')).toBeInTheDocument()
    expect(screen.getByText('2/3')).toBeInTheDocument()
    expect(screen.getByText('src/filter.js, src/filter.test.js')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/tasks', { run_id: 'r1' })
  })
})

describe('describeEvent (worker events)', () => {
  const base = {
    schema_version: 1 as const,
    event_id: 'e',
    run_id: 'r1',
    seq: 1,
    ts: '',
    agent_id: 'sandbox',
    task_id: 't1'
  }

  it('describes checks, reviews, tools and diffs', () => {
    const events: [AgentEvent, string][] = [
      [{ ...base, type: 'check_completed', payload: { name: 'test', exit_code: 0, duration_ms: 2500 } }, 'test passed in 2.5s'],
      [{ ...base, type: 'check_completed', payload: { name: 'test', exit_code: 1, duration_ms: null } }, 'test failed (exit 1)'],
      [{ ...base, type: 'check_completed', payload: { name: 'test', exit_code: null, duration_ms: 0 } }, 'test did not complete'],
      [{ ...base, type: 'review_completed', payload: { verdict: 'changes_requested', findings: 2 } }, 'changes_requested, 2 finding(s)'],
      [{ ...base, type: 'tool_called', payload: { tool: 'read_file', ok: false, summary: '.env: ERROR' } }, 'read_file (error): .env: ERROR'],
      [{ ...base, type: 'diff_ready', payload: { files: ['a.js', 'b.js'] } }, '2 file(s): a.js, b.js']
    ]
    for (const [event, text] of events) expect(describeEvent(event)).toBe(text)
  })
})
