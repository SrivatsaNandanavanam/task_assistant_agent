from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentIntent(str, Enum):
    CREATE = "create"
    LIST = "list"
    SEARCH = "search"
    UPDATE = "update"
    COMPLETE = "complete"
    DELETE = "delete"
    UNSUPPORTED = "unsupported"


class ActionPlan(BaseModel):
    """Typed output of the request-understanding step. Nothing has executed yet."""

    intent: AgentIntent

    target_task_id: int | None = None
    target_reference: str | None = None

    title: str | None = None
    description: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_at: datetime | None = None

    search_query: str | None = None
    status_filter: Literal["pending", "completed"] | None = None
    overdue: bool | None = None

    needs_clarification: bool = False
    clarification_question: str | None = None

    interpretation: str


# ---- API models -------------------------------------------------------------
class MessageRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1)
    timezone: str = "UTC"


class ResumeRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=100)
    approved: bool


class ReceiptStep(BaseModel):
    key: str
    label: str
    status: Literal["done", "pending", "waiting", "failed", "skipped"]
    detail: str | None = None


class PendingApproval(BaseModel):
    action: Literal["delete_task"]
    task: dict[str, Any]
    message: str


class AgentResponse(BaseModel):
    thread_id: str
    status: Literal["success", "clarify", "unsupported", "cancelled", "error", "awaiting_approval"]
    reply: str
    steps: list[ReceiptStep]
    pending_approval: PendingApproval | None = None
    last_task_id: int | None = None
