from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: Literal["pending", "completed"]
    priority: Literal["low", "medium", "high"]
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskMetrics(BaseModel):
    total: int
    open: int
    completed: int
    overdue: int


class TaskPatch(BaseModel):
    """Partial update; only explicitly-set fields are applied."""

    title: str | None = None
    description: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_at: datetime | None = None
