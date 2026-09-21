from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models.task import Task, TaskPriority, TaskStatus


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _terms(query: str) -> list[str]:
    """Lower-cased search words with light stemming ("testing"/"tests" -> "test")."""
    out = []
    for word in re.findall(r"\w+", query.lower()):
        if len(word) > 4 and word.endswith("ing"):
            word = word[:-3]
        elif len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        if len(word) >= 2 and word not in out:
            out.append(word)
    return out


class TaskRepository:
    """Data access only. All queries are parameterised SQLAlchemy constructs."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **fields) -> Task:
        task = Task(**fields)
        self.session.add(task)
        self.session.commit()
        return task

    def get_by_id(self, task_id: int) -> Task | None:
        return self.session.get(Task, task_id)

    def _filtered(
        self,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        overdue: bool | None,
        now: datetime | None,
    ):
        stmt = select(Task)
        if status:
            stmt = stmt.where(Task.status == status)
        if priority:
            stmt = stmt.where(Task.priority == priority)
        if overdue and now:
            stmt = stmt.where(Task.status == TaskStatus.PENDING, Task.due_at.is_not(None), Task.due_at < now)
        return stmt

    def list(
        self,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        overdue: bool | None = None,
        now: datetime | None = None,
        limit: int = 50,
    ) -> list[Task]:
        stmt = self._filtered(status, priority, overdue, now)
        # Stable order: pending first, then earliest due (undated last), then newest id.
        stmt = stmt.order_by(
            case((Task.status == TaskStatus.PENDING, 0), else_=1),
            Task.due_at.is_(None),
            Task.due_at,
            Task.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(stmt))

    def search(
        self,
        query: str,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        overdue: bool | None = None,
        now: datetime | None = None,
        limit: int = 20,
        match_any_term: bool = False,
    ) -> list[Task]:
        """Title/description search.

        Default: the whole phrase must appear (strict; used to resolve mutation targets).
        match_any_term=True: match any word, ranked by how many words match (used by the
        search tool, so "API testing" finds "API integration tests").
        """
        terms = _terms(query) if match_any_term else []
        if not terms:
            terms = [query.strip()]  # whole phrase
            phrase = True
        else:
            phrase = False

        def hit(term: str):
            pattern = f"%{_escape_like(term)}%"
            return or_(
                Task.title.ilike(pattern, escape="\\"),
                Task.description.ilike(pattern, escape="\\"),
            )

        stmt = self._filtered(status, priority, overdue, now).where(or_(*(hit(t) for t in terms)))
        if phrase:
            order = (Task.id,)
        else:
            score = sum((case((hit(t), 1), else_=0) for t in terms), start=literal(0))
            order = (score.desc(), Task.id)
        return list(self.session.scalars(stmt.order_by(*order).limit(limit)))

    def find_by_title(self, title: str, exact: bool, limit: int = 20) -> list[Task]:
        if exact:
            stmt = select(Task).where(func.lower(Task.title) == title.strip().lower())
        else:
            pattern = f"%{_escape_like(title.strip())}%"
            stmt = select(Task).where(Task.title.ilike(pattern, escape="\\"))
        return list(self.session.scalars(stmt.order_by(Task.id).limit(limit)))

    def save(self, task: Task) -> Task:
        self.session.add(task)
        self.session.commit()
        return task

    def delete(self, task: Task) -> None:
        self.session.delete(task)
        self.session.commit()

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(Task)) or 0

    def metrics(self, now: datetime) -> dict[str, int]:
        def count(*conds) -> int:
            return self.session.scalar(select(func.count()).select_from(Task).where(*conds)) or 0

        return {
            "total": count(),
            "open": count(Task.status == TaskStatus.PENDING),
            "completed": count(Task.status == TaskStatus.COMPLETED),
            "overdue": count(Task.status == TaskStatus.PENDING, Task.due_at.is_not(None), Task.due_at < now),
        }
