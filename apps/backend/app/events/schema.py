"""Event schema v1 (plan §4.1): one payload model per event type.

This is the backend/frontend contract for the live event stream. `append_event` validates every
payload against it, and `export_schema` generates the JSON Schema the renderer's TypeScript
types are built from.

Versions: v1 froze at the end of M3. v2 (P1) adds the monitoring events fed by ADK and CrewAI
callbacks through the TelemetryHub (agent_started, agent_finished, callback_fired,
schema_validated) and reserves guardrail_triggered, a2a_message and prompt_variant_selected for
P2/P4. Any change needs agreement from all owners and bumps SCHEMA_VERSION.

Payloads carry `stub: true` when the work they describe was not really performed (M2 worker
stubs). The UI must label such events instead of presenting them as agent progress.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = 2

Complexity = Literal["low", "medium", "high"]
Framework = Literal["adk", "crewai"]


class EventType(StrEnum):
    RUN_CREATED = "run_created"
    RUN_STATUS_CHANGED = "run_status_changed"
    ROUTER_DECIDED = "router_decided"
    TASK_CREATED = "task_created"
    TASK_CLAIMED = "task_claimed"
    TASK_STARTED = "task_started"
    TOOL_CALLED = "tool_called"
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"
    PROVIDER_FALLBACK = "provider_fallback"
    CHECK_STARTED = "check_started"
    CHECK_COMPLETED = "check_completed"
    REVIEW_STARTED = "review_started"
    REVIEW_COMPLETED = "review_completed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_BLOCKED = "task_blocked"
    DIFF_READY = "diff_ready"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    # v2: monitoring via callbacks (TelemetryHub)
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    CALLBACK_FIRED = "callback_fired"
    SCHEMA_VALIDATED = "schema_validated"
    GUARDRAIL_TRIGGERED = "guardrail_triggered"
    A2A_MESSAGE = "a2a_message"
    PROMPT_VARIANT_SELECTED = "prompt_variant_selected"


class Payload(BaseModel):
    # Defaults are always serialized, so the generated types mark those fields as present.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class RunCreated(Payload):
    title: str
    parent_run_id: str | None = None
    triggering_message_id: str | None = None


class RunStatusChanged(Payload):
    status: str
    previous: str | None = None
    stub: bool = False


class RouterDecided(Payload):
    request_type: str
    complexity: Complexity
    confidence: float | None
    route: Literal["answer", "clarify", "run"]
    strategy: str | None
    fallback_used: bool


class TaskCreated(Payload):
    title: str
    complexity: Complexity | None = None
    depends_on: list[str] = []
    target_files: list[str] = []


class TaskClaimed(Payload):
    worker: str


class TaskStarted(Payload):
    worker: str


class ToolCalled(Payload):
    tool: str
    ok: bool = True
    summary: str | None = None


class LLMCallStarted(Payload):
    provider: str
    model: str
    purpose: str


class LLMCallCompleted(Payload):
    provider: str
    model: str
    purpose: str
    ok: bool
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    attempts: int
    error: str | None


class ProviderFallback(Payload):
    from_provider: str
    to_provider: str
    reason: str


class CheckStarted(Payload):
    name: str


class CheckCompleted(Payload):
    name: str
    exit_code: int | None
    duration_ms: int | None


class ReviewStarted(Payload):
    reviewer: str


class ReviewCompleted(Payload):
    verdict: Literal["approved", "changes_requested", "blocked"]
    findings: int = 0


class TaskCompleted(Payload):
    summary: str | None = None


class TaskFailed(Payload):
    error: str


class TaskBlocked(Payload):
    reason: str


class DiffReady(Payload):
    files: list[str]


class RunCompleted(Payload):
    summary: str | None = None
    stub: bool = False


class RunFailed(Payload):
    error: str


class RunCancelled(Payload):
    reason: str | None = None


class AgentStarted(Payload):
    agent: str
    framework: Framework
    kind: str  # llm | sequential | loop | parallel | custom | crew
    parent: str | None = None


class AgentFinished(Payload):
    agent: str
    framework: Framework
    ok: bool = True
    duration_ms: int | None = None


class CallbackFired(Payload):
    """One framework callback, e.g. ADK before_model_callback or CrewAI step_callback."""

    framework: Framework
    hook: str
    agent: str
    detail: str | None = None


class SchemaValidated(Payload):
    agent: str
    schema_name: str
    status: Literal["valid", "repaired", "fallback"]
    errors: list[str] = []


class GuardrailTriggered(Payload):
    guardrail: str
    action: Literal["blocked", "repaired", "warned"]
    reason: str


class A2AMessage(Payload):
    direction: Literal["sent", "received"]
    peer: str
    task_state: str | None = None
    summary: str | None = None


class PromptVariantSelected(Payload):
    role: str
    variant: str


PAYLOADS: dict[EventType, type[Payload]] = {
    EventType.RUN_CREATED: RunCreated,
    EventType.RUN_STATUS_CHANGED: RunStatusChanged,
    EventType.ROUTER_DECIDED: RouterDecided,
    EventType.TASK_CREATED: TaskCreated,
    EventType.TASK_CLAIMED: TaskClaimed,
    EventType.TASK_STARTED: TaskStarted,
    EventType.TOOL_CALLED: ToolCalled,
    EventType.LLM_CALL_STARTED: LLMCallStarted,
    EventType.LLM_CALL_COMPLETED: LLMCallCompleted,
    EventType.PROVIDER_FALLBACK: ProviderFallback,
    EventType.CHECK_STARTED: CheckStarted,
    EventType.CHECK_COMPLETED: CheckCompleted,
    EventType.REVIEW_STARTED: ReviewStarted,
    EventType.REVIEW_COMPLETED: ReviewCompleted,
    EventType.TASK_COMPLETED: TaskCompleted,
    EventType.TASK_FAILED: TaskFailed,
    EventType.TASK_BLOCKED: TaskBlocked,
    EventType.DIFF_READY: DiffReady,
    EventType.RUN_COMPLETED: RunCompleted,
    EventType.RUN_FAILED: RunFailed,
    EventType.RUN_CANCELLED: RunCancelled,
    EventType.AGENT_STARTED: AgentStarted,
    EventType.AGENT_FINISHED: AgentFinished,
    EventType.CALLBACK_FIRED: CallbackFired,
    EventType.SCHEMA_VALIDATED: SchemaValidated,
    EventType.GUARDRAIL_TRIGGERED: GuardrailTriggered,
    EventType.A2A_MESSAGE: A2AMessage,
    EventType.PROMPT_VARIANT_SELECTED: PromptVariantSelected,
}
