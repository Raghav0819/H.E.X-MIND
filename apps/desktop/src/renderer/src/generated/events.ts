/* Generated from the backend event schema (apps/backend/app/events/schema.py). Do not edit; run: npm run gen:events */

/**
 * H.E.X Mind agent event, schema version 1.
 */
export type AgentEvent =
  | RunCreatedEvent
  | RunStatusChangedEvent
  | RouterDecidedEvent
  | TaskCreatedEvent
  | TaskClaimedEvent
  | TaskStartedEvent
  | ToolCalledEvent
  | LlmCallStartedEvent
  | LlmCallCompletedEvent
  | ProviderFallbackEvent
  | CheckStartedEvent
  | CheckCompletedEvent
  | ReviewStartedEvent
  | ReviewCompletedEvent
  | TaskCompletedEvent
  | TaskFailedEvent
  | TaskBlockedEvent
  | DiffReadyEvent
  | RunCompletedEvent
  | RunFailedEvent
  | RunCancelledEvent;

export interface RunCreatedEvent {
  agent_id: string | null;
  event_id: string;
  payload: RunCreated;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "run_created";
}
export interface RunCreated {
  parent_run_id: string | null;
  title: string;
  triggering_message_id: string | null;
}
export interface RunStatusChangedEvent {
  agent_id: string | null;
  event_id: string;
  payload: RunStatusChanged;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "run_status_changed";
}
export interface RunStatusChanged {
  previous: string | null;
  status: string;
  stub: boolean;
}
export interface RouterDecidedEvent {
  agent_id: string | null;
  event_id: string;
  payload: RouterDecided;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "router_decided";
}
export interface RouterDecided {
  complexity: "low" | "medium" | "high";
  confidence: number | null;
  fallback_used: boolean;
  request_type: string;
  route: "answer" | "clarify" | "run";
  strategy: string | null;
}
export interface TaskCreatedEvent {
  agent_id: string | null;
  event_id: string;
  payload: TaskCreated;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "task_created";
}
export interface TaskCreated {
  complexity: ("low" | "medium" | "high") | null;
  depends_on: string[];
  target_files: string[];
  title: string;
}
export interface TaskClaimedEvent {
  agent_id: string | null;
  event_id: string;
  payload: TaskClaimed;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "task_claimed";
}
export interface TaskClaimed {
  worker: string;
}
export interface TaskStartedEvent {
  agent_id: string | null;
  event_id: string;
  payload: TaskStarted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "task_started";
}
export interface TaskStarted {
  worker: string;
}
export interface ToolCalledEvent {
  agent_id: string | null;
  event_id: string;
  payload: ToolCalled;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "tool_called";
}
export interface ToolCalled {
  ok: boolean;
  summary: string | null;
  tool: string;
}
export interface LlmCallStartedEvent {
  agent_id: string | null;
  event_id: string;
  payload: LLMCallStarted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "llm_call_started";
}
export interface LLMCallStarted {
  model: string;
  provider: string;
  purpose: string;
}
export interface LlmCallCompletedEvent {
  agent_id: string | null;
  event_id: string;
  payload: LLMCallCompleted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "llm_call_completed";
}
export interface LLMCallCompleted {
  attempts: number;
  error: string | null;
  input_tokens: number | null;
  latency_ms: number;
  model: string;
  ok: boolean;
  output_tokens: number | null;
  provider: string;
  purpose: string;
}
export interface ProviderFallbackEvent {
  agent_id: string | null;
  event_id: string;
  payload: ProviderFallback;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "provider_fallback";
}
export interface ProviderFallback {
  from_provider: string;
  reason: string;
  to_provider: string;
}
export interface CheckStartedEvent {
  agent_id: string | null;
  event_id: string;
  payload: CheckStarted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "check_started";
}
export interface CheckStarted {
  name: string;
}
export interface CheckCompletedEvent {
  agent_id: string | null;
  event_id: string;
  payload: CheckCompleted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "check_completed";
}
export interface CheckCompleted {
  duration_ms: number | null;
  exit_code: number | null;
  name: string;
}
export interface ReviewStartedEvent {
  agent_id: string | null;
  event_id: string;
  payload: ReviewStarted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "review_started";
}
export interface ReviewStarted {
  reviewer: string;
}
export interface ReviewCompletedEvent {
  agent_id: string | null;
  event_id: string;
  payload: ReviewCompleted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "review_completed";
}
export interface ReviewCompleted {
  findings: number;
  verdict: "approved" | "changes_requested" | "blocked";
}
export interface TaskCompletedEvent {
  agent_id: string | null;
  event_id: string;
  payload: TaskCompleted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "task_completed";
}
export interface TaskCompleted {
  summary: string | null;
}
export interface TaskFailedEvent {
  agent_id: string | null;
  event_id: string;
  payload: TaskFailed;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "task_failed";
}
export interface TaskFailed {
  error: string;
}
export interface TaskBlockedEvent {
  agent_id: string | null;
  event_id: string;
  payload: TaskBlocked;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "task_blocked";
}
export interface TaskBlocked {
  reason: string;
}
export interface DiffReadyEvent {
  agent_id: string | null;
  event_id: string;
  payload: DiffReady;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "diff_ready";
}
export interface DiffReady {
  files: string[];
}
export interface RunCompletedEvent {
  agent_id: string | null;
  event_id: string;
  payload: RunCompleted;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "run_completed";
}
export interface RunCompleted {
  stub: boolean;
  summary: string | null;
}
export interface RunFailedEvent {
  agent_id: string | null;
  event_id: string;
  payload: RunFailed;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "run_failed";
}
export interface RunFailed {
  error: string;
}
export interface RunCancelledEvent {
  agent_id: string | null;
  event_id: string;
  payload: RunCancelled;
  run_id: string;
  schema_version: 1;
  seq: number;
  task_id: string | null;
  ts: string;
  type: "run_cancelled";
}
export interface RunCancelled {
  reason: string | null;
}
