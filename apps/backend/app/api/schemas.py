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
    title: str
    status: str
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
