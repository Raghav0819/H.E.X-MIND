import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.api.deps import SessionDep
from app.api.schemas import EventOut, FileDiffOut, RunCreate, RunDiffOut, RunOut
from app.db.models import AgentEvent, FileChange, Project, Run
from app.events.log import EventType, append_event, list_events
from app.workspace import git

router = APIRouter(prefix="/runs", tags=["runs"])


async def _get_run(session: SessionDep, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(body: RunCreate, session: SessionDep) -> Run:
    """Create a queued run. Orchestration (router, agents) attaches to runs from M2/M3."""
    if await session.get(Project, body.project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    run = Run(project_id=body.project_id, conversation_id=body.conversation_id, title=body.title)
    session.add(run)
    await session.flush()
    await append_event(session, run.id, EventType.RUN_CREATED, payload={"title": run.title})
    await session.refresh(run)
    return run


@router.get("", response_model=list[RunOut])
async def list_runs(
    session: SessionDep,
    project_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[Run]:
    query = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if project_id:
        query = query.where(Run.project_id == project_id)
    if conversation_id:
        query = query.where(Run.conversation_id == conversation_id)
    return list(await session.scalars(query))


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, session: SessionDep) -> Run:
    return await _get_run(session, run_id)


@router.get("/{run_id}/events", response_model=list[EventOut])
async def get_events(
    run_id: uuid.UUID,
    session: SessionDep,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> list[AgentEvent]:
    await _get_run(session, run_id)
    return await list_events(session, run_id, after_seq=after_seq, limit=limit)


@router.get("/{run_id}/diff", response_model=RunDiffOut)
async def get_diff(run_id: uuid.UUID, session: SessionDep) -> RunDiffOut:
    """Proposed changes: each file's content at the run's snapshot and in the run's worktree."""
    run = await _get_run(session, run_id)
    project = await session.get(Project, run.project_id)
    assert project is not None
    changes = list(
        await session.scalars(
            select(FileChange).where(FileChange.run_id == run_id).order_by(FileChange.path)
        )
    )
    worktree = Path(run.worktree_path) if run.worktree_path else None

    def read_modified(path: str) -> str | None:
        if worktree is None:
            return None
        target = worktree / path
        return target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None

    files = []
    for change in changes:
        original = (
            await run_in_threadpool(
                git.show_file, Path(project.workspace_path), run.base_commit, change.path
            )
            if run.base_commit
            else None
        )
        modified = await run_in_threadpool(read_modified, change.path)
        files.append(
            FileDiffOut(
                path=change.path,
                change_type=change.change_type,  # type: ignore[arg-type]
                status=change.status,
                original=original,
                modified=modified,
                diff=change.diff,
            )
        )
    return RunDiffOut(run_id=run.id, base_commit=run.base_commit, files=files)
