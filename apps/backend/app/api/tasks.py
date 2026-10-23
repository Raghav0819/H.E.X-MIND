import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import SessionDep
from app.api.schemas import TaskClaim, TaskCreate, TaskOut, TaskReview
from app.blackboard import store
from app.db.models import Review, Run, Task
from app.events.log import EventType, append_event

router = APIRouter(prefix="/tasks", tags=["blackboard"])


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreate, session: SessionDep) -> Task:
    if await session.get(Run, body.run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    try:
        return await store.add_task(
            session,
            body.run_id,
            title=body.title,
            description=body.description,
            acceptance_criteria=body.acceptance_criteria,
            target_files=body.target_files,
            depends_on=body.depends_on,
            priority=body.priority,
            complexity=body.complexity,
        )
    except store.DuplicateTask as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.get("", response_model=list[TaskOut])
async def list_tasks(run_id: uuid.UUID, session: SessionDep) -> list[Task]:
    result = await session.scalars(
        select(Task).where(Task.run_id == run_id).order_by(Task.created_at)
    )
    return list(result)


@router.post("/{task_id}/claim", response_model=TaskOut)
async def claim_task(task_id: uuid.UUID, body: TaskClaim, session: SessionDep) -> Task:
    task = await store.claim_task(session, task_id, body.worker)
    if task is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "task is not pending or does not exist")
    return task


@router.post("/{task_id}/review", response_model=TaskOut)
async def review_task(task_id: uuid.UUID, body: TaskReview, session: SessionDep) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if task.status != "review":
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}, not in review")
    findings = [f.model_dump() for f in body.findings]
    session.add(
        Review(run_id=task.run_id, task_id=task.id, verdict=body.verdict, findings=findings)
    )
    await append_event(
        session,
        task.run_id,
        EventType.REVIEW_COMPLETED,
        agent_id="reviewer",
        task_id=task.id,
        payload={"verdict": body.verdict, "findings": len(findings)},
    )
    if body.verdict == "approved":
        task = await store.transition(session, task_id, "completed")
    elif body.verdict == "blocked":
        task = await store.transition(session, task_id, "blocked")
    else:
        text = "\n".join(f"- {f['file'] or ''}:{f['line'] or ''} {f['message']}" for f in findings)
        task = await store.request_changes(session, task_id, text)
    await session.refresh(task)
    return task
