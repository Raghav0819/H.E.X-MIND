"""End-to-end run workflow: real git worktree, MCP server subprocess, CrewAI agent loops,
Blackboard, and Docker sandbox checks. Only the language model is scripted."""

import asyncio
import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import CheckResult, FileChange, LLMCall, Review, Run, Task
from app.providers.base import Completion, LLMRequest, ProviderError
from app.sandbox.runner import docker_available
from app.workspace import git
from tests.conftest import ScriptedAdapter, router_json, use_adapter

pytestmark = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")

TODOS_JS = """function addTodo(todos, title) {
  if (!title.trim()) throw new Error('title required')
  return [...todos, { id: todos.length + 1, title: title.trim(), done: false }]
}

function toggleTodo(todos, id) {
  return todos.map((t) => (t.id === id ? { ...t, done: !t.done } : t))
}

module.exports = { addTodo, toggleTodo }
"""
TODOS_TEST = """const test = require('node:test')
const assert = require('node:assert/strict')
const { addTodo, toggleTodo } = require('./todos')

test('addTodo appends a trimmed, open todo', () => {
  assert.deepEqual(addTodo([], ' milk '), [{ id: 1, title: 'milk', done: false }])
})

test('toggleTodo flips done for the matching id', () => {
  assert.equal(toggleTodo(addTodo([], 'a'), 1)[0].done, true)
})
"""
FILTER_JS = """function filterTodos(todos, filter) {
  if (filter === 'active') return todos.filter((t) => !t.done)
  if (filter === 'done') return todos.filter((t) => t.done)
  return todos
}

module.exports = { filterTodos }
"""
FILTER_TEST = """const test = require('node:test')
const assert = require('node:assert/strict')
const { filterTodos } = require('./filter')

const todos = [{ id: 1, done: false }, { id: 2, done: true }]

test('filterTodos returns active and done subsets', () => {
  assert.deepEqual(filterTodos(todos, 'active'), [todos[0]])
  assert.deepEqual(filterTodos(todos, 'done'), [todos[1]])
  assert.deepEqual(filterTodos(todos, 'all'), todos)
})
"""

PLAN = {
    "tasks": [
        {
            "title": "Todo model",
            "description": "Pure functions to add and toggle todos.",
            "acceptance_criteria": ["addTodo trims titles", "toggleTodo flips done"],
            "target_files": ["src/todos.js", "src/todos.test.js"],
            "depends_on": [],
            "complexity": "low",
        },
        {
            "title": "Filter helper",
            "description": "Filter todos by all/active/done.",
            "acceptance_criteria": ["filterTodos supports all, active and done"],
            "target_files": ["src/filter.js", "src/filter.test.js"],
            "depends_on": [0],
            "complexity": "low",
        },
    ]
}

# The Reviewer asks for documented filters; the second round must actually change the file.
FILTER_JS_V2 = "/** Filters: 'all', 'active' (not done) or 'done'. */\n" + FILTER_JS

FILES = {
    "Todo model": [("src/todos.js", TODOS_JS), ("src/todos.test.js", TODOS_TEST)],
    "Filter helper": [("src/filter.js", FILTER_JS), ("src/filter.test.js", FILTER_TEST)],
}


def _action(tool: str, args: dict) -> str:
    return f"Thought: I will use {tool}.\nAction: {tool}\nAction Input: {json.dumps(args)}"


def _final(answer: str) -> str:
    return f"Thought: I now know the final answer\nFinal Answer: {answer}"


class AgentScript:
    """Plays the Router, Planner, Coder and Reviewer. The Reviewer requests changes once for
    the filter task to exercise the review loop."""

    def __init__(self) -> None:
        self.steps: defaultdict[str, int] = defaultdict(int)

    def __call__(self, request: LLMRequest) -> Completion:
        prompt = "\n".join(m.content for m in request.messages)
        if request.purpose == "router":
            return Completion(
                content=router_json(
                    request_type="new_workflow",
                    complexity="medium",
                    execution_strategy="plan_execute_review",
                    requires_planning=True,
                    requires_review=True,
                )
            )
        if request.purpose == "planner":
            return Completion(content=_final(json.dumps(PLAN)))
        if request.purpose == "coder":
            title = re.search(r"(?m)^Task: (.+)$", prompt).group(1).strip()  # type: ignore[union-attr]
            round_key = f"coder:{title}:{prompt.count('Previous attempt was not accepted')}"
            step = self.steps[round_key]
            self.steps[round_key] += 1
            files = FILES[title]
            if title == "Filter helper" and "Previous attempt was not accepted" in prompt:
                files = [("src/filter.js", FILTER_JS_V2)]
            if step < len(files):
                path, content = files[step]
                return Completion(content=_action("write_file", {"path": path, "content": content}))
            return Completion(content=_final(f"Implemented {title}; tests pass."))
        if request.purpose == "reviewer":
            title = re.search(r'for the task "(.+?)"', prompt).group(1)  # type: ignore[union-attr]
            self.steps[f"review:{title}"] += 1
            if title == "Filter helper" and self.steps[f"review:{title}"] == 1:
                verdict = {
                    "verdict": "changes_requested",
                    "findings": [
                        {"file": "src/filter.js", "line": 1, "message": "document filters"}
                    ],
                    "summary": "minor",
                }
            else:
                verdict = {"verdict": "approved", "findings": [], "summary": "looks good"}
            return Completion(content=_final(json.dumps(verdict)))
        return Completion(content="An answer.")


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    root = tmp_path / "todo-app"
    root.mkdir()
    (root / "README.md").write_bytes(b"# Todo app\n")
    git.init_repo(root)
    return root


async def _start_run(client: httpx.AsyncClient, root: Path, message: str) -> dict:
    project = (await client.post("/api/projects", json={"workspace_path": str(root)})).json()
    conversation = (
        await client.post(f"/api/projects/{project['id']}/conversations", json={})
    ).json()
    response = await client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": message, "mode": "edit"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_agents_build_reviewed_changes_in_an_isolated_worktree(
    app: FastAPI, client: httpx.AsyncClient, empty_repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(AgentScript()))

    exchange = await _start_run(client, empty_repo, "Build a todo module with filtering")
    await app.state.services.background.wait_all()
    run_id = uuid.UUID(exchange["run_id"])

    async with app.state.sessionmaker() as session:
        run = await session.get(Run, run_id)
        tasks = {
            t.title: t for t in await session.scalars(select(Task).where(Task.run_id == run_id))
        }
        changes = {c.path: c for c in await session.scalars(select(FileChange))}
        checks = list(await session.scalars(select(CheckResult)))
        reviews = list(await session.scalars(select(Review).order_by(Review.created_at)))
        purposes = Counter(await session.scalars(select(LLMCall.purpose)))

    assert run is not None
    events = (await client.get(f"/api/runs/{run_id}/events")).json()
    assert run.status == "awaiting_approval", [e for e in events if e["type"] == "run_failed"]

    # Plan -> two tasks, both completed; the filter task needed a second round.
    assert {t: tasks[t].status for t in tasks} == {
        "Todo model": "completed",
        "Filter helper": "completed",
    }
    assert [r.verdict for r in reviews] == ["approved", "changes_requested", "approved"]

    # Real files, written by tools in the worktree, with real passing checks.
    assert {p: c.change_type for p, c in changes.items()} == {
        "src/todos.js": "added",
        "src/todos.test.js": "added",
        "src/filter.js": "added",
        "src/filter.test.js": "added",
    }
    assert all(c.base_hash is None for c in changes.values())  # new files
    assert len(checks) == 3 and all(c.exit_code == 0 for c in checks), [
        c.output_tail for c in checks
    ]
    assert "pass 3" in checks[-1].output_tail  # all three tests ran in the sandbox

    # The user's workspace is untouched; the worktree holds the change.
    assert sorted(p.name for p in empty_repo.iterdir() if p.name != ".git") == ["README.md"]
    worktree = Path(run.worktree_path or "")
    assert (worktree / "src" / "filter.js").read_text() == FILTER_JS_V2

    # Every agent model call went through the provider router and was logged.
    assert purposes["planner"] == 1 and purposes["reviewer"] == 3 and purposes["coder"] == 8

    types = [e["type"] for e in events]
    for expected in (
        "task_created", "task_claimed", "task_started", "tool_called", "check_started",
        "check_completed", "review_started", "review_completed", "task_completed", "diff_ready",
    ):  # fmt: skip
        assert expected in types, expected
    assert types.count("task_created") == 2
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    diff_ready = next(e for e in events if e["type"] == "diff_ready")
    assert sorted(diff_ready["payload"]["files"]) == sorted(changes)
    writes = [
        e for e in events if e["type"] == "tool_called" and e["payload"]["tool"] == "write_file"
    ]
    assert writes and all(e["payload"]["ok"] for e in writes)

    # The diff endpoint serves base vs. worktree contents for review.
    diff = (await client.get(f"/api/runs/{run_id}/diff")).json()
    assert diff["base_commit"] == run.base_commit
    by_path = {f["path"]: f for f in diff["files"]}
    assert by_path["src/filter.js"]["original"] is None
    assert by_path["src/filter.js"]["modified"] == FILTER_JS_V2
    assert "+function filterTodos" in by_path["src/filter.js"]["diff"]


async def test_provider_failure_fails_the_run_and_cleans_up(
    app: FastAPI, client: httpx.AsyncClient, empty_repo: Path
) -> None:
    def handler(request: LLMRequest) -> Completion:
        if request.purpose == "router":
            return Completion(content=router_json(request_type="code_edit", complexity="low"))
        raise ProviderError("model unavailable", retryable=False)

    use_adapter(app, ScriptedAdapter(handler))

    exchange = await _start_run(client, empty_repo, "Add a todo model")
    await app.state.services.background.wait_all()

    async with app.state.sessionmaker() as session:
        run = await session.get(Run, uuid.UUID(exchange["run_id"]))
        task = await session.scalar(select(Task))
    assert run is not None and run.status == "failed"
    assert task is not None and task.status == "failed"
    events = (await client.get(f"/api/runs/{run.id}/events")).json()
    assert events[-1]["type"] == "run_failed"
    assert "No task was completed" in events[-1]["payload"]["error"]
    assert not Path(run.worktree_path or "").exists()  # nothing to review, worktree removed


class LazyCoderScript:
    """A low-complexity run (no review) whose Coder first only *claims* success, then writes
    code without tests, then adds the tests."""

    def __init__(self) -> None:
        self.steps: defaultdict[int, int] = defaultdict(int)

    def __call__(self, request: LLMRequest) -> Completion:
        if request.purpose == "router":
            return Completion(content=router_json(request_type="code_edit", complexity="low"))
        prompt = "\n".join(m.content for m in request.messages)
        # Each round's feedback replaces the previous one, so it identifies the round.
        attempt = (
            2 if "ran NO tests" in prompt else 1 if "did not change any files" in prompt else 0
        )
        step = self.steps[attempt]
        self.steps[attempt] += 1
        if attempt == 0:  # claims success without touching a file
            return Completion(content=_final("Implemented the todo model; all tests pass."))
        if attempt == 1:  # code but no tests
            if step == 0:
                return Completion(
                    content=_action("write_file", {"path": "src/todos.js", "content": TODOS_JS})
                )
            return Completion(content=_final("Added src/todos.js."))
        if step == 0:
            return Completion(
                content=_action("write_file", {"path": "src/todos.test.js", "content": TODOS_TEST})
            )
        return Completion(content=_final("Added tests; they pass."))


async def test_claims_without_changes_or_tests_are_not_accepted(
    app: FastAPI, client: httpx.AsyncClient, empty_repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(LazyCoderScript()))

    exchange = await _start_run(client, empty_repo, "Add a todo model")
    await app.state.services.background.wait_all()

    async with app.state.sessionmaker() as session:
        run = await session.get(Run, uuid.UUID(exchange["run_id"]))
        task = await session.scalar(select(Task))
        checks = list(await session.scalars(select(CheckResult).order_by(CheckResult.created_at)))
    assert run is not None and run.status == "awaiting_approval"
    assert task is not None and task.status == "completed"
    # Round 1 changed nothing, so no check ran; round 2's check exited 0 with zero tests and was
    # not accepted; round 3's check ran the tests.
    assert [c.exit_code for c in checks] == [0, 0]
    assert "# tests 0" in checks[0].output_tail
    assert "# pass 2" in checks[1].output_tail


async def test_coder_that_never_writes_fails_the_run(
    app: FastAPI, client: httpx.AsyncClient, empty_repo: Path
) -> None:
    def handler(request: LLMRequest) -> Completion:
        if request.purpose == "router":
            return Completion(content=router_json(request_type="code_edit", complexity="low"))
        return Completion(content=_final("Done. Everything works."))

    use_adapter(app, ScriptedAdapter(handler))

    exchange = await _start_run(client, empty_repo, "Add a todo model")
    await app.state.services.background.wait_all()

    async with app.state.sessionmaker() as session:
        run = await session.get(Run, uuid.UUID(exchange["run_id"]))
        task = await session.scalar(select(Task))
        checks = list(await session.scalars(select(CheckResult)))
    assert run is not None and run.status == "failed"
    assert task is not None and task.status == "failed"
    assert checks == []  # nothing changed, so nothing was checked
    events = (await client.get(f"/api/runs/{run.id}/events")).json()
    failure = next(e for e in events if e["type"] == "task_failed")
    assert failure["payload"]["error"] == "no file changes after 3 attempts"


@pytest.mark.parametrize(
    ("output", "no_tests"),
    [
        ("TAP version 13\n1..0\n# tests 0\n# pass 0\n", True),
        ("ℹ tests 0\nℹ suites 0\nℹ pass 0\n", True),
        ("Ran 0 tests in 0.000s\n\nOK\n", True),
        ("TAP version 13\n# tests 3\n# pass 3\n", False),
        ("ℹ tests 10\nℹ pass 10\n", False),
    ],
)
def test_zero_test_runs_are_not_accepted(output: str, no_tests: bool) -> None:
    from app.graph.run import _accepted, _ran_no_tests
    from app.sandbox.runner import CheckOutcome

    check = CheckOutcome("test", 0, 10, output)
    assert _ran_no_tests(check) is no_tests
    assert _accepted(check) is (not no_tests)


class SlowAdapter(ScriptedAdapter):
    """Coder calls take longer than the task lease, like a local model on modest hardware."""

    async def complete(self, request: LLMRequest) -> Completion:
        if request.purpose == "coder":
            await asyncio.sleep(1.2)
        return await super().complete(request)


async def test_slow_agents_keep_their_lease(
    app: FastAPI, client: httpx.AsyncClient, empty_repo: Path
) -> None:
    app.state.services.settings.task_lease_s = 1  # every coder call outlasts the lease
    use_adapter(app, SlowAdapter(AgentScript()))

    exchange = await _start_run(client, empty_repo, "Build a todo module with filtering")
    await app.state.services.background.wait_all()

    events = (await client.get(f"/api/runs/{exchange['run_id']}/events")).json()
    claims = Counter(e["task_id"] for e in events if e["type"] == "task_claimed")
    assert len(claims) == 2 and set(claims.values()) == {1}  # never reclaimed mid-work
    async with app.state.sessionmaker() as session:
        run = await session.get(Run, uuid.UUID(exchange["run_id"]))
    assert run is not None and run.status == "awaiting_approval"


async def test_worker_stops_when_its_lease_is_taken(app: FastAPI, empty_repo: Path) -> None:
    from sqlalchemy import update

    from app.blackboard import store
    from app.db.models import Project
    from app.graph.run import RunWorkflow

    async with app.state.sessionmaker.begin() as session:
        project = Project(name="p", workspace_path=str(empty_repo))
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, title="r")
        session.add(run)
        await session.flush()
        run_id = run.id
        task = await store.add_task(session, run_id, title="t", description="d")
        await store.claim_task(session, task.id, "w1")
        # Another worker has taken over (as if w1's lease had expired and been reclaimed).
        await session.execute(update(Task).where(Task.id == task.id).values(claimed_by="w2"))

    workflow = RunWorkflow(app.state.services, run_id)
    work = asyncio.create_task(asyncio.sleep(30))
    lost = await workflow._heartbeat(task.id, "w1", timedelta(seconds=0.2), work)
    assert lost is True
    with pytest.raises(asyncio.CancelledError):
        await work
