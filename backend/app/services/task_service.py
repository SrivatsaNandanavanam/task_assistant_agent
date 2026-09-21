from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.models.task import Task, TaskPriority, TaskStatus
from app.repositories.task_repository import TaskRepository


class DomainError(Exception):
    """Predictable, user-safe error."""


class TaskNotFound(DomainError):
    pass


class TaskValidationError(DomainError):
    pass


class PersistenceError(DomainError):
    """Database failure; details are logged, never shown."""


class AmbiguousTask(DomainError):
    def __init__(self, matches: list[Task]):
        self.matches = matches
        super().__init__("multiple matching tasks")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _priority(value: str | TaskPriority | None) -> TaskPriority:
    try:
        return TaskPriority(value)
    except ValueError:
        raise TaskValidationError("Priority must be low, medium, or high.") from None


def _status(value: str | TaskStatus | None) -> TaskStatus | None:
    if value is None:
        return None
    try:
        return TaskStatus(value)
    except ValueError:
        raise TaskValidationError("Status must be pending or completed.") from None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        raise TaskValidationError("Due date must include a timezone.")
    return dt


@dataclass
class Resolution:
    task: Task | None
    matches: list[Task]


class TaskService:
    def __init__(self, repo: TaskRepository):
        self.repo = repo
        self.settings = get_settings()

    # ---- validation helpers -------------------------------------------------
    def _title(self, title: str | None) -> str:
        title = (title or "").strip()
        if not title:
            raise TaskValidationError("A task title is required.")
        if len(title) > self.settings.max_title_length:
            raise TaskValidationError(f"Title must be at most {self.settings.max_title_length} characters.")
        return title

    def _description(self, description: str | None) -> str | None:
        if description is None:
            return None
        description = description.strip() or None
        if description and len(description) > self.settings.max_description_length:
            raise TaskValidationError(
                f"Description must be at most {self.settings.max_description_length} characters."
            )
        return description

    def _limit(self, limit: int | None, default: int) -> int:
        if limit is None:
            return default
        if limit < 1:
            raise TaskValidationError("Limit must be at least 1.")
        return min(limit, self.settings.max_list_limit)

    def _commit(self, fn):
        try:
            return fn()
        except SQLAlchemyError as exc:
            self.repo.session.rollback()
            raise PersistenceError("I couldn't save that change.") from exc

    # ---- operations ---------------------------------------------------------
    def create_task(
        self,
        title: str | None,
        description: str | None = None,
        priority: str | None = None,
        due_at: datetime | None = None,
    ) -> Task:
        now = utcnow()
        fields = dict(
            title=self._title(title),
            description=self._description(description),
            priority=_priority(priority or TaskPriority.MEDIUM),
            status=TaskStatus.PENDING,
            due_at=_aware(due_at),
            created_at=now,
            updated_at=now,
        )
        return self._commit(lambda: self.repo.create(**fields))

    def get_task(self, task_id: int) -> Task:
        task = self.repo.get_by_id(task_id)
        if task is None:
            raise TaskNotFound(f"I couldn't find task #{task_id}.")
        return task

    def list_tasks(
        self,
        status: str | None = None,
        priority: str | None = None,
        overdue: bool | None = None,
        limit: int | None = None,
    ) -> list[Task]:
        return self.repo.list(
            status=_status(status),
            priority=_priority(priority) if priority else None,
            overdue=overdue,
            now=utcnow(),
            limit=self._limit(limit, 50),
        )

    def search_tasks(
        self,
        query: str | None,
        status: str | None = None,
        priority: str | None = None,
        overdue: bool | None = None,
        limit: int | None = None,
    ) -> list[Task]:
        if not (query or "").strip():
            raise TaskValidationError("A search query is required.")
        return self.repo.search(
            query,
            status=_status(status),
            priority=_priority(priority) if priority else None,
            overdue=overdue,
            now=utcnow(),
            limit=self._limit(limit, 20),
            match_any_term=True,
        )

    def update_task(
        self,
        task_id: int,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        due_at: datetime | None = None,
    ) -> Task:
        task = self.get_task(task_id)
        changed = False
        if title is not None:
            new = self._title(title)
            changed |= new != task.title
            task.title = new
        if description is not None:
            new = self._description(description)
            changed |= new != task.description
            task.description = new
        if priority is not None:
            new = _priority(priority)
            changed |= new != task.priority
            task.priority = new
        if due_at is not None:
            new = _aware(due_at)
            changed |= new != task.due_at
            task.due_at = new
        if title is None and description is None and priority is None and due_at is None:
            self.repo.session.rollback()
            raise TaskValidationError("Nothing to update: specify at least one change.")
        if not changed:
            self.repo.session.rollback()
            return task
        task.updated_at = utcnow()
        return self._commit(lambda: self.repo.save(task))

    def complete_task(self, task_id: int) -> tuple[Task, bool]:
        """Returns (task, already_completed). Idempotent."""
        task = self.get_task(task_id)
        if task.status == TaskStatus.COMPLETED:
            return task, True
        now = utcnow()
        task.status = TaskStatus.COMPLETED
        task.completed_at = now
        task.updated_at = now
        return self._commit(lambda: self.repo.save(task)), False

    def reopen_task(self, task_id: int) -> tuple[Task, bool]:
        """Completed -> pending. Returns (task, already_open). Idempotent; other fields are untouched."""
        task = self.get_task(task_id)
        if task.status == TaskStatus.PENDING:
            return task, True
        task.status = TaskStatus.PENDING
        task.completed_at = None
        task.updated_at = utcnow()
        return self._commit(lambda: self.repo.save(task)), False

    def delete_task(self, task_id: int) -> Task:
        """Deletes and verifies the row is gone. Returns the deleted snapshot."""
        task = self.get_task(task_id)
        snapshot = Task(
            id=task.id, title=task.title, description=task.description, status=task.status,
            priority=task.priority, due_at=task.due_at, created_at=task.created_at,
            updated_at=task.updated_at, completed_at=task.completed_at,
        )
        self._commit(lambda: self.repo.delete(task))
        self.repo.session.expire_all()
        if self.repo.get_by_id(task_id) is not None:
            raise PersistenceError("I couldn't save that change.")
        return snapshot

    def metrics(self) -> dict[str, int]:
        return self.repo.metrics(utcnow())

    # ---- reference resolution ----------------------------------------------
    def resolve_reference(self, reference: str) -> Resolution:
        """Exact title, then partial title, then title/description search."""
        reference = reference.strip()
        if not reference:
            return Resolution(None, [])
        for finder in (
            lambda: self.repo.find_by_title(reference, exact=True),
            lambda: self.repo.find_by_title(reference, exact=False),
            lambda: self.repo.search(reference, limit=20),
        ):
            matches = finder()
            if matches:
                return Resolution(matches[0] if len(matches) == 1 else None, matches)
        return Resolution(None, [])

    def seed_demo_data(self) -> int:
        """Seeds only an empty database. Returns number of tasks created."""
        if self.repo.count() > 0:
            return 0
        from datetime import timedelta

        now = utcnow()
        demo = [
            ("Prepare AI interview questions", "pending", "high", now + timedelta(days=1)),
            ("Finish resume updates", "pending", "medium", None),
            ("Review LangGraph notes", "completed", "low", None),
            ("Build task assistant demo", "pending", "high", now + timedelta(days=2)),
            ("Read agent safety notes", "pending", "medium", None),
            ("API integration tests", "pending", "high", now + timedelta(days=3)),
            ("API documentation", "pending", "medium", now - timedelta(days=1)),
            ("Fix production deployment", "pending", "high", None),
        ]
        for title, status, priority, due in demo:
            task = self.create_task(title, priority=priority, due_at=due)
            if status == "completed":
                self.complete_task(task.id)
        return len(demo)
