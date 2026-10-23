import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import SessionDep
from app.api.schemas import EventOut, RunCreate, RunOut
from app.db.models import AgentEvent, Project, Run
from app.events.log import EventType, append_event, list_events

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
