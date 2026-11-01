"""Shared Google ADK plumbing: running an agent tree, emitting state from custom agents, and the
structured-output guard.

The schema guard is an ADK `after_model_callback` for agents with an `output_schema`. ADK
validates such outputs and aborts the whole run on invalid JSON; the guard runs first and
makes sure ADK only ever sees valid output:
  1. valid (fenced JSON is unwrapped)              -> status "valid"
  2. invalid -> one repair call via ProviderRouter -> status "repaired"
  3. still invalid -> a schema-valid fallback      -> status "fallback"
The status and errors are written to session state for the caller and the UI.
"""

import json
import re
from collections.abc import Callable
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.events import Event, EventActions
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.agents.adk_llm import HexAdkLlm
from app.providers.base import ChatMessage

APP_NAME = "hexmind"
USER_ID = "hexmind"

_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


async def run_adk(
    agent: BaseAgent, *, message: str, state: dict[str, Any] | None = None
) -> tuple[dict[str, Any], list[Event]]:
    """Run an agent tree in a fresh in-memory ADK session. Our database stays the source of
    truth; ADK sessions are per invocation. Returns the final session state and the events."""
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=sessions)
    session = await sessions.create_session(app_name=APP_NAME, user_id=USER_ID, state=state or {})
    events: list[Event] = []
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
    ):
        events.append(event)
    final = await sessions.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session.id)
    return (dict(final.state) if final else {}), events


def state_event(agent: BaseAgent, ctx: Any, **delta: Any) -> Event:
    """An event that records state changes from a custom (non-LLM) agent."""
    return Event(
        author=agent.name, invocation_id=ctx.invocation_id, actions=EventActions(state_delta=delta)
    )


def escalate_event(agent: BaseAgent, ctx: Any, **delta: Any) -> Event:
    """Ends the enclosing LoopAgent (ADK loops do not stop on their own)."""
    return Event(
        author=agent.name,
        invocation_id=ctx.invocation_id,
        actions=EventActions(escalate=True, state_delta=delta),
    )


def extract_json(text: str) -> str:
    text = text.strip()
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else text


def _response_text(response: LlmResponse) -> str:
    parts = response.content.parts if response.content and response.content.parts else []
    return "".join(p.text for p in parts if p.text and not p.thought)


def _text_response(response: LlmResponse, text: str) -> LlmResponse:
    return response.model_copy(
        update={"content": types.Content(role="model", parts=[types.Part(text=text)])}
    )


def schema_guard(
    schema: type[BaseModel],
    llm: HexAdkLlm,
    *,
    key: str,
    fallback: Callable[[list[str]], BaseModel],
) -> Callable[[CallbackContext, LlmResponse], Any]:
    """after_model_callback enforcing `schema` with one repair attempt and a valid fallback.
    Writes `{key}_schema_status` ("valid" | "repaired" | "fallback") and `{key}_schema_errors`."""

    async def guard(
        callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        if llm_response.content and any(p.function_call for p in llm_response.content.parts or []):
            return None  # a tool call, not the final answer
        text = _response_text(llm_response)
        errors: list[str] = []
        try:
            candidate = extract_json(text)
            schema.model_validate_json(candidate)
            callback_context.state[f"{key}_schema_status"] = "valid"
            callback_context.state[f"{key}_schema_errors"] = []
            return _text_response(llm_response, candidate)
        except ValidationError as exc:
            errors.append(_summarize(exc))

        request = llm.last_request
        if request is not None:
            repair = request.model_copy(
                update={
                    "messages": [
                        *request.messages,
                        ChatMessage(role="assistant", content=text),
                        ChatMessage(
                            role="user",
                            content=f"That answer was invalid: {errors[0]}. "
                            "Reply again with a single valid JSON object only.",
                        ),
                    ]
                }
            )
            result = await llm.router.complete(repair, llm.ctx)
            if result.ok and result.content:
                try:
                    candidate = extract_json(result.content)
                    schema.model_validate_json(candidate)
                    callback_context.state[f"{key}_schema_status"] = "repaired"
                    callback_context.state[f"{key}_schema_errors"] = errors
                    return _text_response(llm_response, candidate)
                except ValidationError as exc:
                    errors.append(_summarize(exc))
            else:
                errors.append(f"repair call failed: {result.error}")

        callback_context.state[f"{key}_schema_status"] = "fallback"
        callback_context.state[f"{key}_schema_errors"] = errors
        return _text_response(llm_response, fallback(errors).model_dump_json())

    return guard


def _summarize(exc: ValidationError) -> str:
    return json.dumps(
        [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()[:5]]
    )


def model_error_fallback(key: str, fallback_json: str):
    """on_model_error_callback for schema agents: a provider failure becomes the schema
    fallback (recorded as such), not a crash of the whole run."""

    def on_error(
        callback_context: CallbackContext, llm_request: Any, error: Exception
    ) -> LlmResponse:
        callback_context.state[f"{key}_schema_status"] = "fallback"
        callback_context.state[f"{key}_schema_errors"] = [f"provider error: {error}"]
        return LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=fallback_json)])
        )

    return on_error


def user_message_from_state(key: str):
    """before_model_callback: the model sees exactly one user message, taken from session state.
    ADK's include_contents="none" still forwards the current turn's other-agent outputs (e.g.
    the Router's JSON) as a quoted transcript; this replaces that with the prompt we intend."""

    def before(callback_context: CallbackContext, llm_request: Any) -> None:
        text = str(callback_context.state.get(key, ""))
        llm_request.contents = [types.Content(role="user", parts=[types.Part(text=text)])]
        return None

    return before
