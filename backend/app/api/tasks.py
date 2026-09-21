from collections.abc import Iterator
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.session import get_session_factory
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskMetrics, TaskOut, TaskPatch
from app.services.task_service import (
    PersistenceError,
    TaskNotFound,
    TaskService,
    TaskValidationError,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_at: datetime | None = None


def get_service() -> Iterator[TaskService]:
    session = get_session_factory()()
    try:
        yield TaskService(TaskRepository(session))
    finally:
        session.close()


def _guard(fn):
    """Map domain errors to safe HTTP errors (the same service the agent tools use)."""
    try:
        return fn()
    except TaskNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except TaskValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    except PersistenceError:
        raise HTTPException(500, "I couldn't save that change.") from None


@router.get("", response_model=list[TaskOut])
def list_tasks(
    q: str | None = Query(None, max_length=200),
    status: Literal["pending", "completed"] | None = None,
    priority: Literal["low", "medium", "high"] | None = None,
    overdue: bool | None = None,
    limit: int = Query(100, ge=1, le=100),
    service: TaskService = Depends(get_service),
):
    if q and q.strip():
        return _guard(lambda: service.search_tasks(q, status, priority, overdue, limit))
    return _guard(lambda: service.list_tasks(status, priority, overdue, limit))


@router.get("/metrics", response_model=TaskMetrics)
def metrics(service: TaskService = Depends(get_service)):
    return service.metrics()


@router.post("/seed")
def seed(service: TaskService = Depends(get_service)):
    """Loads demo tasks into an empty database only; never overwrites existing data."""
    return {"created": _guard(service.seed_demo_data)}


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, service: TaskService = Depends(get_service)):
    return _guard(lambda: service.create_task(body.title, body.description, body.priority, body.due_at))


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, service: TaskService = Depends(get_service)):
    return _guard(lambda: service.get_task(task_id))


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskPatch, service: TaskService = Depends(get_service)):
    fields = body.model_dump(exclude_unset=True)
    return _guard(lambda: service.update_task(task_id, **fields))


@router.post("/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: int, service: TaskService = Depends(get_service)):
    return _guard(lambda: service.complete_task(task_id)[0])


@router.post("/{task_id}/reopen", response_model=TaskOut)
def reopen_task(task_id: int, service: TaskService = Depends(get_service)):
    return _guard(lambda: service.reopen_task(task_id)[0])


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, service: TaskService = Depends(get_service)):
    """Manual delete from the task workspace (the UI asks for confirmation first)."""
    _guard(lambda: service.delete_task(task_id))
