"""PostgreSQL schema (plan §8). PostgreSQL is the authoritative store for all lifecycle state.

Status-like columns are plain strings validated in application code, so adding a state
does not require an enum migration.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB, list[str]: JSONB}


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[Any]:
    return mapped_column(ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


# ---------- Projects and conversations ----------


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    workspace_path: Mapped[str] = mapped_column(Text, unique=True)
    git_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = _fk("conversations.id")
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    mode: Mapped[str | None] = mapped_column(String(8))  # ask | edit | auto
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)
    created_at: Mapped[datetime] = _created_at()


# ---------- Runs, routing and tasks ----------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    conversation_id: Mapped[uuid.UUID | None] = _fk("conversations.id", nullable=True)
    parent_run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    triggering_message_id: Mapped[uuid.UUID | None] = _fk(
        "messages.id", nullable=True, ondelete="SET NULL"
    )
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    complexity: Mapped[str | None] = mapped_column(String(8))
    strategy: Mapped[str | None] = mapped_column(String(32))
    base_commit: Mapped[str | None] = mapped_column(String(64))
    pre_apply_commit: Mapped[str | None] = mapped_column(String(64))
    worktree_path: Mapped[str | None] = mapped_column(Text)
    # Per-run event counter; incremented in the same transaction as each event insert.
    last_event_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RouterDecision(Base):
    __tablename__ = "router_decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    message_id: Mapped[uuid.UUID] = _fk("messages.id")
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    decision: Mapped[dict[str, Any]] = mapped_column()
    valid: Mapped[bool] = mapped_column(Boolean)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created_at()


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_run_status", "run_id", "status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list[str]] = mapped_column(default=list)
    target_files: Mapped[list[str]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    complexity: Mapped[str | None] = mapped_column(String(8))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    role: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


# ---------- Changes, checks and reviews ----------


class FileChange(Base):
    __tablename__ = "file_changes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    path: Mapped[str] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(16))  # added | modified | deleted
    base_hash: Mapped[str | None] = mapped_column(String(64))
    diff: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    created_at: Mapped[datetime] = _created_at()


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(64))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    output_tail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created_at()


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    verdict: Mapped[str] = mapped_column(String(32))
    findings: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = _created_at()


# ---------- Telemetry ----------


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_agent_events_run_seq"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(48))
    agent_id: Mapped[str | None] = mapped_column(String(64))
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ts: Mapped[datetime] = _created_at()


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    purpose: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    est_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    fallback_from: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


# ---------- Evaluation ----------


class EvalTask(Base):
    __tablename__ = "eval_tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    acceptance_tests: Mapped[list[Any]] = mapped_column(default=list)
    expected_complexity: Mapped[str] = mapped_column(String(8))


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    eval_task_id: Mapped[uuid.UUID] = _fk("eval_tasks.id")
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", nullable=True, ondelete="SET NULL")
    provider: Mapped[str] = mapped_column(String(32))
    completed: Mapped[bool] = mapped_column(Boolean)
    tests_passed: Mapped[int | None] = mapped_column(Integer)
    tests_total: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column()
    judge_rationale: Mapped[str | None] = mapped_column(Text)
    human_score: Mapped[float | None] = mapped_column()
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    retries: Mapped[int] = mapped_column(Integer, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created_at()


class RoutingLabel(Base):
    __tablename__ = "routing_labels"

    id: Mapped[uuid.UUID] = _uuid_pk()
    prompt: Mapped[str] = mapped_column(Text)
    label_complexity: Mapped[str] = mapped_column(String(8))
    label_type: Mapped[str] = mapped_column(String(16))
    labeler: Mapped[str] = mapped_column(String(64))
    split: Mapped[str] = mapped_column(String(8))  # train | test
