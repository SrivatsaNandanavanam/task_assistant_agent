"""The six allowlisted task tools: thin, typed wrappers over TaskService.

`delete_task` intentionally has no `confirmed` parameter (extra fields are forbidden) and is
not reachable through `execute_tool`. It requires an ApprovalToken that only the graph's
approval branch can issue.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.task import Task
from app.services.task_service import TaskService

Priority = Literal["low", "medium", "high"]
Status = Literal["pending", "completed"]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateTaskArgs(_Args):
    title: str
    description: str | None = None
    priority: Priority | None = None
    due_at: datetime | None = None


class ListTasksArgs(_Args):
    status: Status | None = None
    priority: Priority | None = None
    overdue: bool | None = None
    limit: int | None = None


class SearchTasksArgs(_Args):
    query: str
    status: Status | None = None
    priority: Priority | None = None
    overdue: bool | None = None
    limit: int | None = None


class UpdateTaskArgs(_Args):
    task_id: int
    title: str | None = None
    description: str | None = None
    priority: Priority | None = None
    due_at: datetime | None = None


class CompleteTaskArgs(_Args):
    task_id: int


class DeleteTaskArgs(_Args):
    task_id: int


TOOL_SCHEMAS: dict[str, type[_Args]] = {
    "create_task": CreateTaskArgs,
    "list_tasks": ListTasksArgs,
    "search_tasks": SearchTasksArgs,
    "update_task": UpdateTaskArgs,
    "complete_task": CompleteTaskArgs,
    "delete_task": DeleteTaskArgs,
}

TOOL_BY_INTENT = {
    "create": "create_task",
    "list": "list_tasks",
    "search": "search_tasks",
    "update": "update_task",
    "complete": "complete_task",
    "delete": "delete_task",
}

# Tools the generic executor may run. delete_task is deliberately absent.
SAFE_TOOLS = frozenset(TOOL_SCHEMAS) - {"delete_task"}


@dataclass
class ToolResult:
    tool: str
    tasks: list[Task] = field(default_factory=list)
    already_completed: bool = False


class ToolNotAllowed(Exception):
    pass


def create_task(service: TaskService, a: CreateTaskArgs) -> ToolResult:
    return ToolResult("create_task", [service.create_task(a.title, a.description, a.priority, a.due_at)])


def list_tasks(service: TaskService, a: ListTasksArgs) -> ToolResult:
    return ToolResult("list_tasks", service.list_tasks(a.status, a.priority, a.overdue, a.limit))


def search_tasks(service: TaskService, a: SearchTasksArgs) -> ToolResult:
    return ToolResult("search_tasks", service.search_tasks(a.query, a.status, a.priority, a.overdue, a.limit))


def update_task(service: TaskService, a: UpdateTaskArgs) -> ToolResult:
    task = service.update_task(a.task_id, a.title, a.description, a.priority, a.due_at)
    return ToolResult("update_task", [task])


def complete_task(service: TaskService, a: CompleteTaskArgs) -> ToolResult:
    task, already = service.complete_task(a.task_id)
    return ToolResult("complete_task", [task], already_completed=already)


_HANDLERS = {
    "create_task": create_task,
    "list_tasks": list_tasks,
    "search_tasks": search_tasks,
    "update_task": update_task,
    "complete_task": complete_task,
}


def execute_tool(name: str, args: dict, service: TaskService) -> ToolResult:
    """Run an allowlisted, non-destructive tool. Unknown names and delete_task are refused."""
    if name not in SAFE_TOOLS:
        raise ToolNotAllowed(name)
    return _HANDLERS[name](service, TOOL_SCHEMAS[name].model_validate(args))


class ApprovalToken:
    """Proof that the graph's approval branch approved deleting exactly one task."""

    _issuing = False

    def __init__(self, thread_id: str, task_id: int):
        if not ApprovalToken._issuing:
            raise ToolNotAllowed("delete_task requires graph approval")
        self.thread_id = thread_id
        self.task_id = task_id

    @classmethod
    def issue(cls, thread_id: str, task_id: int) -> "ApprovalToken":
        cls._issuing = True
        try:
            return cls(thread_id, task_id)
        finally:
            cls._issuing = False


def delete_task(service: TaskService, args: DeleteTaskArgs, approval: ApprovalToken) -> ToolResult:
    if not isinstance(approval, ApprovalToken) or approval.task_id != args.task_id:
        raise ToolNotAllowed("delete_task requires approval for this exact task")
    return ToolResult("delete_task", [service.delete_task(args.task_id)])
