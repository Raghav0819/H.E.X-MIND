"""Planner, Coder and Reviewer (plan §6), defined with CrewAI and run as single-agent,
single-task crews from LangGraph nodes. Outputs are JSON validated with Pydantic; the agents'
claims are never trusted for facts we can measure (changed files come from git, check results
from the sandbox)."""

import json
import re
from typing import Literal, TypeVar

from crewai import Agent, Crew, Process, Task
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError

from app.agents.llm import HexLLM

T = TypeVar("T", bound=BaseModel)


# ---------- structured outputs ----------


class PlannedTask(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=3)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=8)
    target_files: list[str] = Field(default_factory=list, max_length=12)
    depends_on: list[int] = Field(default_factory=list, description="0-based indices of tasks")
    complexity: Literal["low", "medium", "high"] = "medium"


class Plan(BaseModel):
    tasks: list[PlannedTask] = Field(min_length=1, max_length=6)


class ReviewFinding(BaseModel):
    file: str | None = None
    line: int | None = None
    severity: Literal["info", "minor", "major", "critical"] = "minor"
    message: str


class ReviewResult(BaseModel):
    verdict: Literal["approved", "changes_requested", "blocked"]
    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str = ""


class OutputError(ValueError):
    pass


def parse_json_output(raw: str, model: type[T]) -> T:
    """Validate the first JSON object in an agent's final answer (fences and prose tolerated)."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    if not candidate:
        raise OutputError("no JSON object found in the answer")
    try:
        return model.model_validate(json.loads(candidate))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise OutputError(str(exc)[:500]) from exc


# ---------- agents ----------


def planner(llm: HexLLM, tools: list[BaseTool], max_iter: int) -> Agent:
    return Agent(
        role="Planner",
        goal="Break a software request into a few small, independent, testable tasks.",
        backstory=(
            "You are a senior engineer planning work for other agents. You inspect the current "
            "project files before planning, avoid duplicate or overlapping tasks, and never write "
            "code yourself."
        ),
        llm=llm, tools=tools, max_iter=max_iter, allow_delegation=False, verbose=False,
    )  # fmt: skip


def coder(llm: HexLLM, tools: list[BaseTool], max_iter: int) -> Agent:
    return Agent(
        role="Coder",
        goal="Implement one task with small, correct changes and passing tests.",
        backstory=(
            "You are a careful engineer. You read the current files before editing, follow the "
            "project's coding standards, make targeted edits, write tests for your change, and "
            "run the `test` check before finishing. You never claim results you did not observe."
        ),
        llm=llm, tools=tools, max_iter=max_iter, allow_delegation=False, verbose=False,
    )  # fmt: skip


def reviewer(llm: HexLLM, tools: list[BaseTool], max_iter: int) -> Agent:
    return Agent(
        role="Reviewer",
        goal="Decide whether a change meets its acceptance criteria without regressions.",
        backstory=(
            "You are a strict but fair code reviewer. You check correctness, edge cases, tests "
            "and coding standards, and cite files and lines. You only request changes for real "
            "problems."
        ),
        llm=llm, tools=tools, max_iter=max_iter, allow_delegation=False, verbose=False,
    )  # fmt: skip


async def run_agent(agent: Agent, description: str, expected_output: str) -> str:
    task = Task(description=description, expected_output=expected_output, agent=agent)
    crew = Crew(
        agents=[agent], tasks=[task], process=Process.sequential, memory=False, verbose=False
    )
    result = await crew.kickoff_async()
    return result.raw


# ---------- prompts ----------

PLAN_SCHEMA = json.dumps(Plan.model_json_schema()["$defs"]["PlannedTask"]["properties"])
REVIEW_SCHEMA = '{"verdict": "approved|changes_requested|blocked", "findings": [{"file": "...", "line": 1, "severity": "minor|major|critical", "message": "..."}], "summary": "..."}'  # noqa: E501


def planner_prompt(request: str, standards: list[str]) -> str:
    return f"""Plan the implementation of this request for the project in the workspace:

{request}

First inspect the project with the tools (list_files, read_file). Then produce 1 to 6 tasks.
Each task must be small enough for one engineer, list the files it will create or change in
target_files, and have concrete acceptance criteria that tests can check. Use depends_on
(0-based task indices) only when a task needs another's code. Tasks that change the same file
must depend on each other.

Relevant coding standards:
{_bullets(standards)}

Your final answer must be only a JSON object: {{"tasks": [ ... ]}} where each task has these
fields: {PLAN_SCHEMA}"""


def coder_prompt(
    *, title: str, description: str, criteria: list[str], target_files: list[str],
    standards: list[str], lessons: list[str], feedback: str | None,
) -> str:  # fmt: skip
    feedback_block = (
        f"\nPrevious attempt was not accepted. Fix this first:\n{feedback}\n" if feedback else ""
    )
    return f"""Implement this task in the workspace.

Task: {title}
{description}

Acceptance criteria:
{_bullets(criteria)}

Files you are expected to touch: {", ".join(target_files) or "decide from the project"}
{feedback_block}
Coding standards to follow:
{_bullets(standards)}

Lessons from earlier tasks:
{_bullets(lessons) if lessons else "- none"}

Steps: read the relevant files, make the changes with write_file or replace_in_file, add or update
tests (*.test.js using node:test), then run the `test` check with run_check and fix failures.
Files only change when you call write_file or replace_in_file: code written in your answer is
discarded, and a task with no file changes is rejected.
Your final answer: a short summary of what you changed and the final check result."""


def reviewer_prompt(
    *, title: str, criteria: list[str], diff: str, check_summary: str, standards: list[str]
) -> str:
    return f"""Review this change for the task "{title}".

Acceptance criteria:
{_bullets(criteria)}

Latest check result:
{check_summary}

Diff against the starting point:
```diff
{diff}
```

Coding standards:
{_bullets(standards)}

You may read files or run the `test` check. Approve only if every criterion is met and the
checks pass. Your final answer must be only a JSON object: {REVIEW_SCHEMA}"""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"
