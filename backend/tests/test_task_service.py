from datetime import datetime, timedelta, timezone

import pytest

from app.services.task_service import TaskNotFound, TaskValidationError, utcnow


def test_create_title_only(service):
    t = service.create_task("Buy milk")
    assert t.id and t.status.value == "pending" and t.priority.value == "medium"
    assert t.due_at is None and t.completed_at is None


def test_create_full(service):
    due = datetime(2030, 1, 1, 20, tzinfo=timezone(timedelta(hours=-5)))
    t = service.create_task("Demo", "desc", "high", due)
    assert t.priority.value == "high" and t.description == "desc"
    assert t.due_at == due


def test_empty_title_rejected(service):
    with pytest.raises(TaskValidationError):
        service.create_task("   ")


def test_invalid_priority_rejected(service):
    with pytest.raises(TaskValidationError, match="low, medium, or high"):
        service.create_task("x", priority="urgent")


def test_naive_due_rejected(service):
    with pytest.raises(TaskValidationError):
        service.create_task("x", due_at=datetime(2030, 1, 1))


def test_list_filters(service):
    a = service.create_task("a", priority="high")
    service.create_task("b", priority="low")
    service.complete_task(a.id)
    assert len(service.list_tasks()) == 2
    assert [t.title for t in service.list_tasks(status="pending")] == ["b"]
    assert [t.title for t in service.list_tasks(status="completed")] == ["a"]
    assert [t.title for t in service.list_tasks(priority="high")] == ["a"]


def test_search_title_and_description(service):
    service.create_task("API tests")
    service.create_task("Other", description="covers the api docs")
    service.create_task("Unrelated")
    assert len(service.search_tasks("api")) == 2


def test_search_treats_sql_as_text(service):
    service.create_task("keep me")
    assert service.search_tasks("'; DROP TABLE tasks; --") == []
    assert service.search_tasks("%") == []
    assert len(service.list_tasks()) == 1


def test_update_one_field_only(service):
    t = service.create_task("x", description="d", priority="low")
    u = service.update_task(t.id, priority="high")
    assert u.priority.value == "high" and u.title == "x" and u.description == "d"
    assert u.updated_at >= t.created_at


def test_empty_update_rejected(service):
    t = service.create_task("x")
    with pytest.raises(TaskValidationError):
        service.update_task(t.id)


def test_update_missing_task(service):
    with pytest.raises(TaskNotFound):
        service.update_task(999, title="y")


def test_complete_and_idempotent(service):
    t = service.create_task("x")
    done, already = service.complete_task(t.id)
    assert done.status.value == "completed" and done.completed_at and not already
    _, already = service.complete_task(t.id)
    assert already


def test_delete(service):
    t = service.create_task("x")
    snap = service.delete_task(t.id)
    assert snap.id == t.id
    with pytest.raises(TaskNotFound):
        service.get_task(t.id)


def test_delete_missing(service):
    with pytest.raises(TaskNotFound):
        service.delete_task(42)


def test_metrics_and_overdue(service):
    past = utcnow() - timedelta(days=1)
    future = utcnow() + timedelta(days=1)
    overdue = service.create_task("late", due_at=past)
    service.create_task("ok", due_at=future)
    done = service.create_task("done", due_at=past)
    service.complete_task(done.id)
    assert service.metrics() == {"total": 3, "open": 2, "completed": 1, "overdue": 1}
    service.complete_task(overdue.id)
    assert service.metrics()["overdue"] == 0


def test_resolve_reference(service):
    service.create_task("API integration tests")
    service.create_task("API documentation")
    service.create_task("Fix deployment")
    assert service.resolve_reference("deployment").task.title == "Fix deployment"
    amb = service.resolve_reference("API")
    assert amb.task is None and len(amb.matches) == 2
    assert service.resolve_reference("nonexistent").matches == []
    assert service.resolve_reference("api documentation").task.title == "API documentation"


def test_seed_only_when_empty(service):
    assert service.seed_demo_data() == 8
    assert service.seed_demo_data() == 0
    assert service.metrics()["completed"] == 1


# ---- reopen ---------------------------------------------------------------------
def test_reopen_completed_task_preserves_fields(service):
    due = utcnow() + timedelta(days=2)
    t = service.create_task("Ship it", "details", "high", due)
    service.complete_task(t.id)
    reopened, already_open = service.reopen_task(t.id)
    assert not already_open
    assert reopened.status.value == "pending" and reopened.completed_at is None
    assert (reopened.title, reopened.description, reopened.priority.value, reopened.due_at) == (
        "Ship it", "details", "high", due)
    assert service.metrics()["open"] == 1 and service.metrics()["completed"] == 0


def test_open_complete_reopen_complete_cycle(service):
    t = service.create_task("Cycle")
    assert service.complete_task(t.id)[0].status.value == "completed"
    assert service.reopen_task(t.id)[0].status.value == "pending"
    again, already = service.complete_task(t.id)
    assert again.status.value == "completed" and again.completed_at is not None and not already


def test_reopen_open_task_is_idempotent(service):
    t = service.create_task("Already open")
    task, already_open = service.reopen_task(t.id)
    assert already_open and task.status.value == "pending"


def test_reopen_invalid_id(service):
    with pytest.raises(TaskNotFound):
        service.reopen_task(999)


def test_reopen_db_failure_leaves_task_completed(service, factory, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.repositories.task_repository import TaskRepository
    from app.services.task_service import PersistenceError

    t = service.create_task("Keep completed")
    service.complete_task(t.id)

    def fail(self, task):
        raise OperationalError("UPDATE", {}, Exception("disk I/O error"))

    monkeypatch.setattr(TaskRepository, "save", fail)
    with pytest.raises(PersistenceError):
        service.reopen_task(t.id)
    monkeypatch.undo()
    fresh = factory()  # independent session: what is really in the database
    try:
        stored = TaskRepository(fresh).get_by_id(t.id)
        assert stored.status.value == "completed" and stored.completed_at is not None
    finally:
        fresh.close()


# ---- multi-word search ------------------------------------------------------------
def test_search_matches_individual_words_ranked_by_relevance(service):
    service.create_task("API integration tests")
    service.create_task("API documentation")
    service.create_task("Unrelated chores")
    found = service.search_tasks("API testing")  # "testing" ~ "tests", "API" in both
    assert [t.title for t in found] == ["API integration tests", "API documentation"]
    assert service.search_tasks("zzz nothing") == []


def test_target_resolution_stays_strict_for_phrases(service):
    """A fuzzy word match must never pick a mutation target."""
    service.create_task("Fix production deployment")
    assert service.resolve_reference("deployment checklist").matches == []
    assert service.resolve_reference("production deployment").task.title == "Fix production deployment"
