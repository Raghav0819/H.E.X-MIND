"""LLM Router (plan §3.1): classifies a message with structured output.

Model output is validated against RouterDecision. One repair attempt is made with the
validation error; if that also fails, the caller gets None and policy applies the fallback.
"""

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.providers.base import ChatMessage, LLMRequest
from app.providers.router import CallContext, ProviderRouter
from app.router.schemas import Mode, RouterDecision

SYSTEM_PROMPT = """You are the Router for H.E.X Mind, an IDE where AI agents plan, write and
review code. Classify the user's latest message. Respond with JSON only, matching the given schema.

request_type:
- "question": wants an explanation, answer or analysis; no files should change.
- "code_edit": wants changes to existing project files.
- "new_workflow": wants a new feature, app or larger build that creates new code.
- "clarification": the request is too ambiguous to act on safely; ask one focused question
  in clarification_question.

complexity:
- "low": one isolated, bounded change (one file or a few lines).
- "medium": related changes across several files or components.
- "high": architectural change, many dependencies, security-sensitive work or broad refactoring.

execution_strategy: "direct" for low, "plan_execute_review" for medium, "decompose" for high.
requires_planning / requires_review: true unless the change is trivial.
confidence: your probability (0-1) that request_type and complexity are correct.
reason: one short sentence.

Use the project context only to judge scope. The user's selected mode is a hint, not an order."""


@dataclass
class RouterResult:
    decision: RouterDecision | None
    attempts: int
    provider: str | None = None
    model: str | None = None
    errors: list[str] = field(default_factory=list)
    raw: list[str] = field(default_factory=list)


async def classify(
    providers: ProviderRouter,
    *,
    message: str,
    mode: Mode,
    context: str,
    ctx: CallContext | None = None,
) -> RouterResult:
    messages = [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(
            role="user",
            content=f"{context}\n\n---\nSelected mode: {mode}\nLatest message:\n{message}",
        ),
    ]
    result = RouterResult(decision=None, attempts=0)

    for _ in range(2):  # initial attempt + one repair
        result.attempts += 1
        response = await providers.complete(
            LLMRequest(
                purpose="router",
                messages=messages,
                json_schema=RouterDecision.model_json_schema(),
                max_tokens=400,
                temperature=0,
            ),
            ctx,
        )
        result.provider, result.model = response.provider, response.model
        if not response.ok or response.content is None:
            result.errors.append(f"provider error: {response.error}")
            return result  # the provider already retried; repairing won't help

        result.raw.append(response.content)
        try:
            result.decision = RouterDecision.model_validate_json(response.content)
            return result
        except ValidationError as exc:
            error = _summarize(exc)
            result.errors.append(error)
            messages = [
                *messages,
                ChatMessage(role="assistant", content=response.content),
                ChatMessage(
                    role="user",
                    content=f"That JSON was invalid: {error}. Reply again with valid JSON only.",
                ),
            ]
    return result


def _summarize(exc: ValidationError) -> str:
    return json.dumps(
        [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()[:5]]
    )
