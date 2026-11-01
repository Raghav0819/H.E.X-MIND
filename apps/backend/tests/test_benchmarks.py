from collections import Counter
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import EvalTask
from app.evaluation import benchmarks
from app.sandbox.runner import docker_available


def test_task_set_shape() -> None:
    tasks = benchmarks.load_tasks()
    assert len(tasks) >= 12  # plan: >= 12 tasks, 14 x 3 providers = 42 runs in M7
    assert Counter(t.expected_complexity for t in tasks) == {"low": 5, "medium": 5, "high": 4}
    for task in tasks:
        assert task.acceptance_test.is_file(), task.slug
        assert any(task.reference_dir.rglob("*.js")), task.slug


def test_prepare_workspace_is_a_clean_repo(tmp_path: Path) -> None:
    from app.workspace import git

    root = benchmarks.prepare_workspace(tmp_path / "ws")
    assert git.is_repo(root)
    assert (root / "src" / "todos.js").is_file()
    # Hidden material never reaches the agent's workspace.
    assert not (root / benchmarks.ACCEPTANCE_DIR).exists()
    assert not list(root.rglob("*acceptance*"))


@pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
def test_every_acceptance_test_discriminates() -> None:
    """Each hidden test must fail on the seed and pass on the reference solution."""
    assert benchmarks.validate() == []


@pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
def test_grading_does_not_touch_the_project(tmp_path: Path) -> None:
    task = benchmarks.load_tasks()[0]
    root = benchmarks.prepare_workspace(tmp_path / "ws", reference=task)
    before = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts
    )
    assert benchmarks.passed(benchmarks.grade(root, task))
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts)
    assert after == before


async def test_sync_eval_tasks_upserts(app: FastAPI) -> None:
    async with app.state.sessionmaker.begin() as session:
        count = await benchmarks.sync_eval_tasks(session)
    async with app.state.sessionmaker.begin() as session:
        await benchmarks.sync_eval_tasks(session)  # idempotent
    async with app.state.sessionmaker() as session:
        rows = list(await session.scalars(select(EvalTask)))
    assert len(rows) == count == len(benchmarks.load_tasks())
    delete = next(r for r in rows if r.slug == "delete-todo")
    assert delete.expected_complexity == "low"
    assert delete.acceptance_tests == ["acceptance/delete-todo.test.js"]
