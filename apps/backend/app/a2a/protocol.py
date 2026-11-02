"""What the ADK orchestrator and the CrewAI crew service agree on (plan §1, criterion 6).

Each A2A request carries the prompt as its message text and a `hexmind` object in the
request-level metadata: which run, task and worktree the crew works on, and an `exchange_id`
that both sides put on their `a2a_message` events so the UI can join them. W3C trace context
(`traceparent`) travels next to it, so the crew's spans join the orchestrator's trace.
"""

import uuid
from typing import Any, Literal

from opentelemetry import propagate, trace
from pydantic import BaseModel

CrewRole = Literal["planner", "coder"]
ROLES: tuple[CrewRole, ...] = ("planner", "coder")
METADATA_KEY = "hexmind"


def card_path(role: CrewRole) -> str:
    return f"/{role}/.well-known/agent-card.json"


def agent_name(role: CrewRole) -> str:
    """The ADK RemoteA2aAgent name, also the A2A agent card name."""
    return f"{role}_crew"


class CrewRequest(BaseModel):
    exchange_id: uuid.UUID
    run_id: uuid.UUID
    task_id: uuid.UUID | None = None
    # The CrewAI agent id inside the crew (planner, coder_01, ...).
    agent_id: str
    worktree: str
    workspace: str
    complexity: str | None = None
    expected_output: str


def trace_carrier() -> dict[str, str]:
    """The current span's W3C trace context, for request metadata."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def request_metadata(request: CrewRequest) -> dict[str, Any]:
    return {METADATA_KEY: request.model_dump(mode="json"), **trace_carrier()}
