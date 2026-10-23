from fastapi import FastAPI

from app.providers.base import Completion, ProviderError
from app.router.classifier import classify
from tests.conftest import ScriptedAdapter, router_json, scripted, use_adapter


async def test_valid_output_is_parsed_with_schema_constrained_request(app: FastAPI) -> None:
    adapter = scripted(router=router_json(request_type="code_edit", complexity="high"))
    use_adapter(app, adapter)

    result = await classify(app.state.provider_router, message="m", mode="auto", context="ctx")

    assert result.decision is not None
    assert (result.decision.request_type, result.decision.complexity) == ("code_edit", "high")
    assert result.attempts == 1
    request = adapter.requests[0]
    assert request.purpose == "router" and request.temperature == 0
    assert request.json_schema is not None
    assert "request_type" in request.json_schema["properties"]
    assert "Selected mode: auto" in request.messages[-1].content


async def test_invalid_output_gets_one_repair_attempt(app: FastAPI) -> None:
    adapter = scripted(router=["not json", router_json(confidence=0.7)])
    use_adapter(app, adapter)

    result = await classify(app.state.provider_router, message="m", mode="edit", context="")

    assert result.decision is not None and result.decision.confidence == 0.7
    assert result.attempts == 2 and len(result.errors) == 1
    repair = adapter.requests[1].messages
    assert repair[-2].content == "not json"  # the model sees its invalid answer
    assert "invalid" in repair[-1].content


async def test_two_invalid_outputs_return_no_decision(app: FastAPI) -> None:
    adapter = scripted(
        router=[router_json(confidence=7), router_json(request_type="delete_everything")]
    )
    use_adapter(app, adapter)

    result = await classify(app.state.provider_router, message="m", mode="auto", context="")

    assert result.decision is None
    assert result.attempts == 2 and len(result.errors) == 2
    assert result.raw == [router_json(confidence=7), router_json(request_type="delete_everything")]


async def test_extra_fields_are_rejected(app: FastAPI) -> None:
    use_adapter(app, scripted(router=[router_json(approve_dangerous=True)] * 2))
    result = await classify(app.state.provider_router, message="m", mode="auto", context="")
    assert result.decision is None


async def test_provider_failure_is_not_repaired(app: FastAPI) -> None:
    def handler(_: object) -> Completion:
        raise ProviderError("bad request", retryable=False)

    adapter = ScriptedAdapter(handler)
    use_adapter(app, adapter)

    result = await classify(app.state.provider_router, message="m", mode="auto", context="")

    assert result.decision is None and result.attempts == 1
    assert "bad request" in result.errors[0]
