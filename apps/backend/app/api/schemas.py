import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    workspace_path: str = Field(min_length=1)


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    workspace_path: str
    git_enabled: bool
    created_at: datetime
    updated_at: datetime


class TreeEntryOut(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int | None


class FileOut(BaseModel):
    path: str
    content: str | None
    hash: str
    size: int
    binary: bool
    too_large: bool


class FileWrite(BaseModel):
    path: str = Field(min_length=1)
    content: str
    base_hash: str | None


class FileWritten(BaseModel):
    path: str
    hash: str


class RunCreate(BaseModel):
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    conversation_id: uuid.UUID | None = None


class RunOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    conversation_id: uuid.UUID | None
    parent_run_id: uuid.UUID | None
    triggering_message_id: uuid.UUID | None
    title: str
    status: str
    complexity: str | None
    strategy: str | None
    last_event_seq: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EventOut(ORMModel):
    schema_version: Literal[1] = 1
    event_id: uuid.UUID = Field(validation_alias="id")
    run_id: uuid.UUID
    seq: int
    ts: datetime
    type: str
    agent_id: str | None
    task_id: uuid.UUID | None
    payload: dict[str, Any]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ConversationOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    summary: str | None
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    mode: Literal["ask", "edit", "auto"] = "auto"


class MessageOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    mode: str | None
    content: str
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime


class MessageExchangeOut(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
    run_id: uuid.UUID | None


class TaskCreate(BaseModel):
    run_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    acceptance_criteria: list[str] = []
    target_files: list[str] = []
    depends_on: list[uuid.UUID] = []
    priority: int = 0
    complexity: Literal["low", "medium", "high"] | None = None


class TaskOut(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    title: str
    description: str
    acceptance_criteria: list[str]
    target_files: list[str]
    status: str
    complexity: str | None
    priority: int
    claimed_by: str | None
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime


class TaskClaim(BaseModel):
    worker: str = Field(min_length=1, max_length=64)


class Finding(BaseModel):
    file: str | None = None
    line: int | None = None
    severity: Literal["info", "minor", "major", "critical"] = "minor"
    message: str


class TaskReview(BaseModel):
    verdict: Literal["approved", "changes_requested", "blocked"]
    findings: list[Finding] = []


class FileDiffOut(BaseModel):
    path: str
    change_type: Literal["added", "modified", "deleted"]
    status: str
    original: str | None
    modified: str | None
    diff: str


class RunDiffOut(BaseModel):
    run_id: uuid.UUID
    base_commit: str | None
    files: list[FileDiffOut]
