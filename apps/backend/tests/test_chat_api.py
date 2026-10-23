from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select

from app.db.models import Conversation, LLMCall, RouterDecision
from tests.conftest import fake_run_executor, router_json, scripted, use_adapter


async def _conversation(client: httpx.AsyncClient, workspace: Path) -> tuple[str, str]:
    project = (await client.post("/api/projects", json={"workspace_path": str(workspace)})).json()
    response = await client.post(f"/api/projects/{project['id']}/conversations", json={})
    assert response.status_code == 201
    return project["id"], response.json()["id"]


async def _send(client: httpx.AsyncClient, conversation_id: str, content: str, mode: str) -> dict:
    response = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": content, "mode": mode}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_ask_answers_with_project_context(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    adapter = scripted(chat="`x` is exported from src/app.ts.")
    use_adapter(app, adapter)
    _, conversation_id = await _conversation(client, workspace)

    exchange = await _send(client, conversation_id, "What does app.ts export?", "ask")

    assistant = exchange["assistant_message"]
    assert assistant["content"] == "`x` is exported from src/app.ts."
    meta = assistant["metadata"]
    assert meta["kind"] == "answer"
    assert meta["route"]["route"] == "answer" and meta["route"]["fallback_used"] is False
    assert meta["context"]["files"][0] == {
        "path": "src/app.ts",
        "reason": "mentioned",
        "truncated": False,
    }
    assert meta["llm"]["provider"] == "scripted" and meta["llm"]["output_tokens"] == 20
    assert exchange["run_id"] is None

    # The answer prompt carried the file read from disk.
    chat_request = [r for r in adapter.requests if r.purpose == "chat"][0]
    assert "export const x = 1" in chat_request.messages[-1].content

    # Router decision and both LLM calls are logged.
    async with app.state.sessionmaker() as session:
        decision = await session.scalar(select(RouterDecision))
        assert decision is not None and decision.valid and not decision.fallback_used
        purposes = sorted(await session.scalars(select(LLMCall.purpose)))
        assert purposes == ["chat", "router"]

    # The conversation title comes from the first message.
    conversation = (await client.get(f"/api/conversations/{conversation_id}")).json()
    assert conversation["title"] == "What does app.ts export?"


async def test_follow_up_is_linked_and_sees_history(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    adapter = scripted()
    use_adapter(app, adapter)
    _, conversation_id = await _conversation(client, workspace)

    await _send(client, conversation_id, "What is the project about?", "ask")
    await _send(client, conversation_id, "And what did you just say?", "ask")

    messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "What is the project about?"),
        ("assistant", "An answer."),
        ("user", "And what did you just say?"),
        ("assistant", "An answer."),
    ]
    follow_up_prompt = [r for r in adapter.requests if r.purpose == "chat"][-1].messages[-1].content
    assert "user: What is the project about?" in follow_up_prompt
    assert "assistant: An answer." in follow_up_prompt


async def test_edit_starts_linked_runs(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    app.state.services.run_executor = fake_run_executor
    use_adapter(
        app,
        scripted(
            router=router_json(
                request_type="code_edit",
                complexity="medium",
                execution_strategy="plan_execute_review",
                requires_planning=True,
                requires_review=True,
            )
        ),
    )
    _, conversation_id = await _conversation(client, workspace)

    first = await _send(client, conversation_id, "Add a dark theme", "edit")
    await app.state.services.background.wait_all()
    second = await _send(client, conversation_id, "Now make the header blue", "edit")
    await app.state.services.background.wait_all()

    assert first["assistant_message"]["metadata"]["kind"] == "run_started"
    assert "your files are not changed" in first["assistant_message"]["content"]

    run1 = (await client.get(f"/api/runs/{first['run_id']}")).json()
    run2 = (await client.get(f"/api/runs/{second['run_id']}")).json()
    assert (run1["complexity"], run1["strategy"]) == ("medium", "plan_execute_review")
    assert run2["parent_run_id"] == run1["id"]
    assert run2["triggering_message_id"] == second["user_message"]["id"]

    events = (await client.get(f"/api/runs/{run1['id']}/events")).json()
    assert [e["type"] for e in events][:2] == ["run_created", "router_decided"]
    assert events[-1]["payload"]["summary"] == "planning=True review=True"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    async with app.state.sessionmaker() as session:
        decision = await session.scalar(
            select(RouterDecision).where(RouterDecision.run_id == run1["id"])
        )
        assert decision is not None

    listed = (await client.get("/api/runs", params={"conversation_id": conversation_id})).json()
    assert [r["id"] for r in listed] == [run2["id"], run1["id"]]


async def test_low_complexity_run_skips_plan_and_review(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    app.state.services.run_executor = fake_run_executor
    use_adapter(app, scripted(router=router_json(request_type="code_edit", complexity="low")))
    _, conversation_id = await _conversation(client, workspace)

    exchange = await _send(client, conversation_id, "Rename x to y", "edit")
    await app.state.services.background.wait_all()

    events = (await client.get(f"/api/runs/{exchange['run_id']}/events")).json()
    assert events[-1]["payload"]["summary"] == "planning=False review=False"


async def test_edit_requires_git(app: FastAPI, client: httpx.AsyncClient, tmp_path: Path) -> None:
    app.state.services.run_executor = fake_run_executor
    use_adapter(app, scripted(router=router_json(request_type="code_edit", complexity="low")))
    plain = tmp_path / "plain"
    plain.mkdir()
    _, conversation_id = await _conversation(client, plain)

    exchange = await _send(client, conversation_id, "Rename x to y", "edit")

    assert exchange["run_id"] is None
    assert exchange["assistant_message"]["metadata"]["kind"] == "error"
    assert "not a Git repository" in exchange["assistant_message"]["content"]
    assert (await client.get("/api/runs")).json() == []

    project_id = (await client.get("/api/projects")).json()[0]["id"]
    init = await client.post(f"/api/projects/{project_id}/git/init")
    assert init.status_code == 200 and init.json()["git_enabled"] is True
    assert (await client.post(f"/api/projects/{project_id}/git/init")).status_code == 409

    exchange = await _send(client, conversation_id, "Rename x to y", "edit")
    assert exchange["run_id"] is not None


async def test_ask_mode_blocks_runs_even_for_edit_requests(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    adapter = scripted(router=router_json(request_type="code_edit", complexity="high"))
    use_adapter(app, adapter)
    _, conversation_id = await _conversation(client, workspace)

    exchange = await _send(client, conversation_id, "Rewrite the app", "ask")

    assert exchange["run_id"] is None
    meta = exchange["assistant_message"]["metadata"]
    assert meta["kind"] == "answer" and meta["route"]["policy_note"]
    system_prompt = [r for r in adapter.requests if r.purpose == "chat"][0].messages[0].content
    assert "Edit mode" in system_prompt
    assert (await client.get("/api/runs")).json() == []


async def test_clarification_and_fallback(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    use_adapter(app, scripted(router=["garbage", "still garbage"]))
    _, conversation_id = await _conversation(client, workspace)

    exchange = await _send(client, conversation_id, "do the thing", "auto")

    meta = exchange["assistant_message"]["metadata"]
    assert meta["kind"] == "clarification"
    assert meta["route"]["fallback_used"] is True
    async with app.state.sessionmaker() as session:
        decision = await session.scalar(select(RouterDecision))
        assert decision is not None and not decision.valid and decision.fallback_used
        assert decision.decision["attempts"] == 2


async def test_failed_answer_is_reported_not_invented(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    from app.providers.base import Completion, ProviderError
    from tests.conftest import ScriptedAdapter

    def handler(request):
        if request.purpose == "router":
            return Completion(content=router_json())
        raise ProviderError("model crashed", retryable=False)

    use_adapter(app, ScriptedAdapter(handler))
    _, conversation_id = await _conversation(client, workspace)

    exchange = await _send(client, conversation_id, "explain", "ask")

    assistant = exchange["assistant_message"]
    assert assistant["metadata"]["kind"] == "error"
    assert "model crashed" in assistant["content"]


async def test_summary_folds_old_messages(
    app: FastAPI, client: httpx.AsyncClient, workspace: Path
) -> None:
    use_adapter(app, scripted(summary="They discussed the todo app."))
    _, conversation_id = await _conversation(client, workspace)

    for i in range(7):  # 14 messages: 8 recent + 6 to summarize
        await _send(client, conversation_id, f"question {i}", "ask")
        await app.state.services.background.wait_all()

    async with app.state.sessionmaker() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        assert conversation.summary == "They discussed the todo app."
        assert conversation.summary_message_count == 4
        summary_calls = await session.scalar(
            select(func.count()).where(LLMCall.purpose == "summary")
        )
        assert summary_calls == 1


async def test_conversation_endpoints_404(client: httpx.AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/conversations/{missing}")).status_code == 404
    assert (await client.get(f"/api/conversations/{missing}/messages")).status_code == 404
    send = await client.post(
        f"/api/conversations/{missing}/messages", json={"content": "x", "mode": "ask"}
    )
    assert send.status_code == 404
    create = await client.post(f"/api/projects/{missing}/conversations", json={})
    assert create.status_code == 404
