"""ContextManager (plan §3.4): builds the bounded, redacted context sent with chat and router
prompts from four separate sources: conversation, project, execution and code.

The workspace is the source of truth: files are read from disk on every build, never recalled
from conversation history.
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import workspace_scan as scan
from app.context.redact import redact
from app.db.models import Conversation, FileChange, Message, Project, Run

# Share of the token budget per source (plan §3.4).
BUDGET_SHARES = {"conversation": 0.20, "project": 0.10, "execution": 0.15, "code": 0.55}
RECENT_MESSAGES = 8
# Messages are summarized in batches, so up to this many older ones may not be summarized yet.
SUMMARY_BATCH = 4
PROJECT_INSTRUCTIONS_FILE = "HEXMIND.md"


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token); used for budgeting, not billing."""
    return len(text) // 4 + 1


def _clip(text: str, max_tokens: int) -> tuple[str, bool]:
    max_chars = max(0, max_tokens * 4)
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n… [truncated]", True


@dataclass
class ContextFile:
    path: str
    reason: Literal["mentioned", "prior_run", "search"]
    content: str
    truncated: bool = False


@dataclass
class ContextBundle:
    project_name: str
    stack: list[str]
    instructions: str | None
    tree: str
    summary: str | None
    recent_messages: list[tuple[str, str]]
    prior_runs: list[str]
    files: list[ContextFile]
    omitted_files: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts = [f"## Project: {self.project_name}"]
        if self.stack:
            parts.append(f"Stack: {', '.join(self.stack)}")
        if self.instructions:
            parts.append(
                f"### Project instructions ({PROJECT_INSTRUCTIONS_FILE})\n{self.instructions}"
            )
        parts.append(f"### File tree\n{self.tree or '(empty workspace)'}")
        if self.summary:
            parts.append(f"### Earlier conversation (summary)\n{self.summary}")
        if self.recent_messages:
            turns = "\n".join(f"{role}: {content}" for role, content in self.recent_messages)
            parts.append(f"### Recent conversation\n{turns}")
        if self.prior_runs:
            parts.append("### Previous runs in this conversation\n" + "\n".join(self.prior_runs))
        for file in self.files:
            note = " (truncated)" if file.truncated else ""
            parts.append(f"### File: {file.path}{note}\n```\n{file.content}\n```")
        if self.omitted_files:
            parts.append("Relevant but omitted (budget): " + ", ".join(self.omitted_files))
        return "\n\n".join(parts)

    def sources(self) -> dict:
        """Compact description of what was included, stored with the assistant message."""
        return {
            "files": [
                {"path": f.path, "reason": f.reason, "truncated": f.truncated} for f in self.files
            ],
            "omitted_files": self.omitted_files,
            "messages": len(self.recent_messages),
            "summary": self.summary is not None,
            "prior_runs": len(self.prior_runs),
        }


class ContextManager:
    def __init__(self, budget_tokens: int) -> None:
        self.budget = {k: int(budget_tokens * share) for k, share in BUDGET_SHARES.items()}

    async def build(
        self,
        session: AsyncSession,
        *,
        project: Project,
        conversation: Conversation,
        message: str,
        exclude_message_id: uuid.UUID | None = None,
    ) -> ContextBundle:
        summary, recent = await self._conversation(session, conversation, exclude_message_id)
        prior_runs, prior_files = await self._execution(session, conversation.id)
        workspace = await run_in_threadpool(
            self._workspace, Path(project.workspace_path), message, prior_files
        )
        return ContextBundle(
            project_name=project.name,
            summary=summary,
            recent_messages=recent,
            prior_runs=prior_runs,
            **workspace,
        )

    # ---------- conversation ----------

    async def _conversation(
        self,
        session: AsyncSession,
        conversation: Conversation,
        exclude_message_id: uuid.UUID | None,
    ) -> tuple[str | None, list[tuple[str, str]]]:
        query = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(RECENT_MESSAGES + SUMMARY_BATCH + 1)
        )
        messages = [m for m in await session.scalars(query) if m.id != exclude_message_id]
        budget = self.budget["conversation"]
        summary = None
        if conversation.summary:
            summary, _ = _clip(redact(conversation.summary), budget // 3)
            budget -= estimate_tokens(summary)

        recent: list[tuple[str, str]] = []
        for m in messages[: RECENT_MESSAGES + SUMMARY_BATCH]:  # newest first; keep newest that fit
            content = redact(m.content)
            cost = estimate_tokens(content)
            if cost > budget:
                break
            recent.append((m.role, content))
            budget -= cost
        recent.reverse()
        return summary, recent

    # ---------- execution ----------

    async def _execution(
        self, session: AsyncSession, conversation_id: uuid.UUID
    ) -> tuple[list[str], list[str]]:
        runs = list(
            await session.scalars(
                select(Run)
                .where(Run.conversation_id == conversation_id)
                .order_by(Run.created_at.desc())
                .limit(5)
            )
        )
        if not runs:
            return [], []
        changed = list(
            await session.scalars(
                select(FileChange.path)
                .where(FileChange.run_id.in_([r.id for r in runs]))
                .distinct()
            )
        )
        lines: list[str] = []
        budget = self.budget["execution"]
        for run in runs:
            line = f"- {run.title} [{run.status}{', ' + run.complexity if run.complexity else ''}]"
            if estimate_tokens(line) > budget:
                break
            lines.append(line)
            budget -= estimate_tokens(line)
        return lines, changed

    # ---------- project + code (blocking filesystem work) ----------

    def _workspace(self, root: Path, message: str, prior_files: list[str]) -> dict:
        files = scan.list_files(root)

        instructions = None
        if any(f.path == PROJECT_INSTRUCTIONS_FILE for f in files):
            text = scan.read_text(root, PROJECT_INSTRUCTIONS_FILE)
            if text:
                instructions, _ = _clip(redact(text), self.budget["project"] // 2)
        project_budget = self.budget["project"] - (
            estimate_tokens(instructions) if instructions else 0
        )
        tree, _ = _clip(scan.render_tree(files), max(project_budget, 50))

        # Code: explicitly mentioned files first, then files changed by earlier runs, then search.
        known = {f.path for f in files}
        candidates: list[tuple[str, Literal["mentioned", "prior_run", "search"]]] = []
        for path in scan.mentioned_files(message, files):
            candidates.append((path, "mentioned"))
        for path in prior_files:
            if path in known and all(path != c for c, _ in candidates):
                candidates.append((path, "prior_run"))
        for path in scan.search_files(root, files, scan.keywords(message)):
            if all(path != c for c, _ in candidates):
                candidates.append((path, "search"))

        budget = self.budget["code"]
        included: list[ContextFile] = []
        omitted: list[str] = []
        for path, reason in candidates:
            text = scan.read_text(root, path)
            if text is None:
                continue
            text = redact(text)
            if budget <= 50:
                omitted.append(path)
                continue
            clipped, truncated = _clip(text, budget)
            included.append(ContextFile(path, reason, clipped, truncated))
            budget -= estimate_tokens(clipped)

        return {
            "stack": scan.detect_stack(root, files),
            "instructions": instructions,
            "tree": tree,
            "files": included,
            "omitted_files": omitted,
        }
