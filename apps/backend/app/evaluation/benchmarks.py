"""Benchmark task set (plan §9 M4, §11): fixed tasks with hidden acceptance tests.

    python -m app.evaluation.benchmarks validate   # every acceptance test fails on the seed
                                                   # and passes on the reference solution
    python -m app.evaluation.benchmarks sync       # upsert the tasks into eval_tasks

Grading copies a result to a scratch directory, adds the task's acceptance test there, and runs
it in the same sandbox as agent checks. The agent's worktree is never modified.
"""

import argparse
import asyncio
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalTask
from app.sandbox.runner import CheckOutcome, run_check

BENCH_DIR = Path(__file__).with_name("benchmarks")
SEED_DIR = BENCH_DIR / "seed"
ACCEPTANCE_DIR = "__acceptance__"
GRADE_IMAGE = "node:22-alpine"


@dataclass(frozen=True)
class BenchmarkTask:
    slug: str
    prompt: str
    expected_complexity: Literal["low", "medium", "high"]

    @property
    def acceptance_test(self) -> Path:
        return BENCH_DIR / "acceptance" / f"{self.slug}.test.js"

    @property
    def reference_dir(self) -> Path:
        return BENCH_DIR / "reference" / self.slug


def load_tasks() -> list[BenchmarkTask]:
    data = yaml.safe_load((BENCH_DIR / "tasks.yaml").read_text(encoding="utf-8"))
    tasks = [BenchmarkTask(**t) for t in data["tasks"]]
    slugs = [t.slug for t in tasks]
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate benchmark slugs")
    return tasks


def prepare_workspace(dest: Path, *, reference: BenchmarkTask | None = None) -> Path:
    """Copy the seed project (optionally with a reference solution overlaid) into `dest` and
    make it a git repository, ready for an agent run."""
    shutil.copytree(SEED_DIR, dest)
    if reference is not None:
        shutil.copytree(reference.reference_dir, dest, dirs_exist_ok=True)
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.name=H.E.X Mind", "-c", "user.email=hexmind@localhost", "commit", "-q",
         "-m", "Benchmark seed"],
    ):  # fmt: skip
        subprocess.run(["git", *args], cwd=dest, check=True, capture_output=True)
    return dest


def grade(project_dir: Path, task: BenchmarkTask, *, timeout_s: int = 120) -> CheckOutcome:
    """Run the hidden acceptance test against a copy of `project_dir`."""
    with tempfile.TemporaryDirectory(prefix="hexmind-grade-") as tmp:
        scratch = Path(tmp) / "project"
        shutil.copytree(project_dir, scratch, ignore=shutil.ignore_patterns(".git", "node_modules"))
        target = scratch / ACCEPTANCE_DIR
        target.mkdir()
        shutil.copy2(task.acceptance_test, target / task.acceptance_test.name)
        return run_check(
            name=f"acceptance:{task.slug}",
            command=f"node --test {ACCEPTANCE_DIR}/{task.acceptance_test.name}",
            image=GRADE_IMAGE,
            worktree=scratch,
            timeout_s=timeout_s,
        )


def passed(outcome: CheckOutcome) -> bool:
    return (
        outcome.passed
        and "# fail 0" in outcome.output_tail
        and "# tests 0" not in outcome.output_tail
    )


async def sync_eval_tasks(session: AsyncSession) -> int:
    """Upsert the task definitions into `eval_tasks` (keyed by slug)."""
    existing = {t.slug: t for t in await session.scalars(select(EvalTask))}
    for task in load_tasks():
        row = existing.get(task.slug) or EvalTask(slug=task.slug)
        row.prompt = task.prompt
        row.expected_complexity = task.expected_complexity
        row.acceptance_tests = [f"acceptance/{task.slug}.test.js"]
        if task.slug not in existing:
            session.add(row)
    await session.flush()
    return len(load_tasks())


def validate() -> list[str]:
    """Problems with the task set; empty means every acceptance test discriminates."""
    problems = []
    for task in load_tasks():
        with tempfile.TemporaryDirectory() as tmp:
            seed = prepare_workspace(Path(tmp) / "seed")
            solved = prepare_workspace(Path(tmp) / "solved", reference=task)
            on_seed = grade(seed, task)
            on_reference = grade(solved, task)
        if on_seed.exit_code is None or on_reference.exit_code is None:
            problems.append(f"{task.slug}: sandbox error {on_seed.error or on_reference.error}")
        elif passed(on_seed):
            problems.append(f"{task.slug}: acceptance test passes on the unmodified seed")
        elif not passed(on_reference):
            problems.append(f"{task.slug}: reference fails:\n{on_reference.output_tail[-800:]}")
    return problems


async def _sync() -> None:
    from app.config import get_settings
    from app.db.session import create_engine, create_sessionmaker

    engine = create_engine(get_settings().database_url)
    try:
        async with create_sessionmaker(engine).begin() as session:
            print(f"synced {await sync_eval_tasks(session)} tasks")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.benchmarks")
    parser.add_argument("command", choices=["validate", "sync"])
    args = parser.parse_args()
    if args.command == "validate":
        issues = validate()
        print("\n".join(issues) if issues else f"all {len(load_tasks())} tasks valid")
        raise SystemExit(1 if issues else 0)
    asyncio.run(_sync())
