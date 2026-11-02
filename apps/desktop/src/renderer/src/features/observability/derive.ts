import type { AgentEvent } from '../../generated/events'

/**
 * Observability views are derived only from the run's event log (and the task list), so every
 * view shows what the backend recorded: nothing here is simulated.
 */

export type Framework = 'adk' | 'crewai'

type EventOf<T extends AgentEvent['type']> = Extract<AgentEvent, { type: T }>

function ofType<T extends AgentEvent['type']>(events: AgentEvent[], type: T): EventOf<T>[] {
  return events.filter((e): e is EventOf<T> => e.type === type)
}

// ---------- agents ----------

export interface AgentStats {
  /** Agent name; CrewAI coders are per worker (coder_01, ...). */
  name: string
  framework: Framework
  kind: string
  parent: string | null
  /** Started but not yet finished invocations. */
  active: number
  invocations: number
  lastDurationMs: number | null
  /** The most recent invocation ended with an error. */
  lastFailed: boolean
  llmCalls: number
  inputTokens: number
  outputTokens: number
  toolCalls: number
  callbacks: number
  /** The most recent callback detail: what the agent is doing now. */
  lastActivity: string | null
  lastSeq: number
}

/** Agents are keyed by name: `agent_id` on model and tool events is the same name. */
export function deriveAgents(events: AgentEvent[]): AgentStats[] {
  const agents = new Map<string, AgentStats>()
  const get = (name: string, framework: Framework = 'adk', kind = 'custom'): AgentStats => {
    let agent = agents.get(name)
    if (!agent) {
      agent = {
        name,
        framework,
        kind,
        parent: null,
        active: 0,
        invocations: 0,
        lastDurationMs: null,
        lastFailed: false,
        llmCalls: 0,
        inputTokens: 0,
        outputTokens: 0,
        toolCalls: 0,
        callbacks: 0,
        lastActivity: null,
        lastSeq: 0
      }
      agents.set(name, agent)
    }
    return agent
  }

  for (const event of events) {
    switch (event.type) {
      case 'agent_started': {
        const p = event.payload
        const agent = get(p.agent, p.framework, p.kind)
        Object.assign(agent, { framework: p.framework, kind: p.kind, parent: p.parent ?? agent.parent })
        agent.active += 1
        agent.invocations += 1
        agent.lastSeq = event.seq
        break
      }
      case 'agent_finished': {
        const agent = get(event.payload.agent, event.payload.framework)
        agent.active = Math.max(0, agent.active - 1)
        agent.lastDurationMs = event.payload.duration_ms
        agent.lastFailed = !event.payload.ok
        agent.lastSeq = event.seq
        break
      }
      case 'callback_fired': {
        const agent = get(event.payload.agent, event.payload.framework)
        agent.callbacks += 1
        agent.lastActivity = `${event.payload.hook}${event.payload.detail ? `: ${event.payload.detail}` : ''}`
        agent.lastSeq = event.seq
        break
      }
      case 'llm_call_completed': {
        if (!event.agent_id || !agents.has(event.agent_id)) break
        const agent = get(event.agent_id)
        agent.llmCalls += 1
        agent.inputTokens += event.payload.input_tokens ?? 0
        agent.outputTokens += event.payload.output_tokens ?? 0
        break
      }
      case 'tool_called': {
        if (!event.agent_id || !agents.has(event.agent_id)) break
        get(event.agent_id).toolCalls += 1
        break
      }
    }
  }
  return [...agents.values()]
}

// ---------- topology ----------

export interface TopologyNode {
  name: string
  framework: Framework
  kind: string
  active: boolean
  failed: boolean
  invocations: number
  children: TopologyNode[]
}

/**
 * The agent tree as it actually ran, built from the `parent` recorded on `agent_started`.
 * Children keep first-start order, so the tree reads in execution order.
 */
export function deriveTopology(events: AgentEvent[]): TopologyNode[] {
  const stats = new Map(deriveAgents(events).map((a) => [a.name, a]))
  const order: string[] = []
  for (const e of ofType(events, 'agent_started')) {
    if (!order.includes(e.payload.agent)) order.push(e.payload.agent)
  }
  const nodes = new Map<string, TopologyNode>()
  for (const name of order) {
    const a = stats.get(name)!
    nodes.set(name, {
      name,
      framework: a.framework,
      kind: a.kind,
      active: a.active > 0,
      failed: a.active === 0 && a.lastFailed,
      invocations: a.invocations,
      children: []
    })
  }
  const roots: TopologyNode[] = []
  for (const name of order) {
    const parent = stats.get(name)!.parent
    const parentNode = parent ? nodes.get(parent) : undefined
    if (parentNode && parentNode !== nodes.get(name)) parentNode.children.push(nodes.get(name)!)
    else roots.push(nodes.get(name)!)
  }
  return roots
}

// ---------- Blackboard claim log ----------

export interface ClaimLogEntry {
  seq: number
  ts: string
  taskId: string | null
  worker: string | null
  action: string
  detail: string
}

const CLAIM_LOG_TYPES = new Set<AgentEvent['type']>([
  'task_created',
  'task_claimed',
  'task_started',
  'review_started',
  'review_completed',
  'task_completed',
  'task_failed',
  'task_blocked'
])

/** Who did what to which Blackboard task, in order. */
export function deriveClaimLog(events: AgentEvent[]): ClaimLogEntry[] {
  return events
    .filter((e) => CLAIM_LOG_TYPES.has(e.type))
    .map((e) => {
      let detail = ''
      let worker = e.agent_id
      switch (e.type) {
        case 'task_created':
          detail = e.payload.title
          worker = 'planner'
          break
        case 'task_claimed':
        case 'task_started':
          worker = e.payload.worker
          break
        case 'review_completed':
          detail = e.payload.verdict
          break
        case 'task_completed':
          detail = e.payload.summary ?? ''
          break
        case 'task_failed':
          detail = e.payload.error
          break
        case 'task_blocked':
          detail = e.payload.reason
          break
      }
      return { seq: e.seq, ts: e.ts, taskId: e.task_id, worker, action: e.type.replace('task_', ''), detail }
    })
}

// ---------- callbacks and schema checks ----------

export type CallbackEvent = EventOf<'callback_fired'> | EventOf<'agent_started'> | EventOf<'agent_finished'>

/** Every framework callback. before/after_agent callbacks are recorded as agent_started/finished. */
export function callbackEvents(events: AgentEvent[]): CallbackEvent[] {
  return events.filter(
    (e): e is CallbackEvent => e.type === 'callback_fired' || e.type === 'agent_started' || e.type === 'agent_finished'
  )
}

export function callbackHook(event: CallbackEvent): string {
  if (event.type === 'callback_fired') return event.payload.hook
  const crew = event.payload.framework === 'crewai'
  if (event.type === 'agent_started') return crew ? 'before_kickoff' : 'before_agent_callback'
  return crew ? 'after_kickoff' : 'after_agent_callback'
}

export function schemaChecks(events: AgentEvent[]): EventOf<'schema_validated'>[] {
  return ofType(events, 'schema_validated')
}

/** Live lease countdown: seconds left, or null when the task holds no lease. */
export function leaseSecondsLeft(leaseExpiresAt: string | null, now: number): number | null {
  if (!leaseExpiresAt) return null
  return Math.max(0, Math.round((Date.parse(leaseExpiresAt) - now) / 1000))
}

// ---------- A2A exchanges ----------

export interface A2AStep {
  seq: number
  ts: string
  side: 'client' | 'server'
  direction: 'sent' | 'received'
  state: string | null
  summary: string | null
}

export interface A2AExchange {
  exchangeId: string
  /** The remote crew (agent card name), e.g. coder_crew. */
  crew: string
  a2aTaskId: string | null
  taskId: string | null
  startedAt: string
  durationMs: number | null
  /** Last known A2A task state: submitted | working | completed | failed, or sent. */
  state: string
  /** True when both sides recorded the same trace id: one trace across the A2A boundary. */
  traceShared: boolean
  traceId: string | null
  steps: A2AStep[]
}

/** Joins the client (orchestrator) and server (crew) sides of each A2A exchange. */
export function deriveA2AExchanges(events: AgentEvent[]): A2AExchange[] {
  const byId = new Map<string, A2AExchange>()
  const traces = new Map<string, Set<string>>()
  for (const e of ofType(events, 'a2a_message')) {
    const p = e.payload
    let exchange = byId.get(p.exchange_id)
    if (!exchange) {
      exchange = {
        exchangeId: p.exchange_id,
        crew: p.side === 'client' ? p.peer : p.agent,
        a2aTaskId: null,
        taskId: e.task_id,
        startedAt: e.ts,
        durationMs: null,
        state: 'sent',
        traceShared: false,
        traceId: null,
        steps: []
      }
      byId.set(p.exchange_id, exchange)
      traces.set(p.exchange_id, new Set())
    }
    exchange.steps.push({ seq: e.seq, ts: e.ts, side: p.side, direction: p.direction, state: p.task_state, summary: p.summary })
    exchange.a2aTaskId = p.a2a_task_id ?? exchange.a2aTaskId
    if (p.task_state) exchange.state = p.task_state
    if (p.side === 'client' && p.direction === 'received' && p.duration_ms !== null) exchange.durationMs = p.duration_ms
    if (p.trace_id) {
      exchange.traceId = exchange.traceId ?? p.trace_id
      traces.get(p.exchange_id)!.add(`${p.side}:${p.trace_id}`)
    }
  }
  for (const exchange of byId.values()) {
    const ids = [...traces.get(exchange.exchangeId)!]
    const sides = new Set(ids.map((s) => s.split(':')[0]))
    exchange.traceShared = sides.size === 2 && new Set(ids.map((s) => s.split(':')[1])).size === 1
  }
  return [...byId.values()]
}
