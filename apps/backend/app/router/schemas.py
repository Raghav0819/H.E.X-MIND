from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RequestType = Literal["question", "code_edit", "new_workflow", "clarification"]
Complexity = Literal["low", "medium", "high"]
Mode = Literal["ask", "edit", "auto"]
Strategy = Literal["direct", "plan_execute_review", "decompose"]


class RouterDecision(BaseModel):
    """What the Router model proposes. Validated strictly; policy decides what happens."""

    model_config = ConfigDict(extra="forbid")

    request_type: RequestType
    complexity: Complexity
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)
    execution_strategy: Strategy
    requires_planning: bool
    requires_review: bool
    clarification_question: str | None = Field(default=None, max_length=500)


class RoutePlan(BaseModel):
    """The deterministic policy outcome (what the system will actually do)."""

    route: Literal["answer", "clarify", "run"]
    request_type: RequestType
    complexity: Complexity
    confidence: float | None
    strategy: Strategy | None = None
    requires_planning: bool = False
    requires_review: bool = False
    clarification_question: str | None = None
    reason: str
    # True when the model output was unusable and the deterministic fallback was applied.
    fallback_used: bool = False
    # Why policy changed the model's proposal, if it did.
    policy_note: str | None = None
