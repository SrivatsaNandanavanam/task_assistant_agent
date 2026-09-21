"""AgentRunner + conversation storage: what is saved, what context is loaded, and failure behaviour."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.agent.graph import build_graph
from app.agent.runner import CRASH_REPLY, AgentRunner, NoPendingApproval
from app.main import create_app
from app.models.conversation import Conversation, Message
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.agent import ActionPlan
from app.services.conversation_service import (
    ConversationPersistenceError,
    ConversationService,
)
from tests.test_agent_routing import ScriptedPlanner


class CapturingPlanner(ScriptedPlanner):
    """Scripted planner that also records the context the model would be given each turn."""

    def __init__(self):
        super().__init__()
        self.contexts: list[dict] = []

    def __call__(self, message, ctx):
        self.contexts.append(ctx)
        return super().__call__(message, ctx)


@pytest.fixture
def planner():
    return CapturingPlanner()


def make_runner(factory, planner, persist=True):
    """A runner with its own graph (own in-memory graph state), like a freshly started server."""
    return AgentRunner(
        build_graph(planner=planner, session_factory=factory),
        conversation_session_factory=factory if persist else None,
    )


@pytest.fixture
def runner(factory, planner):
    return make_runner(factory, planner)


def say(runner, planner, text, thread="c1", **plan):
    plan.setdefault("interpretation", "test")
    planner.queue.append(ActionPlan(**plan))
    return runner.send(thread, text, "UTC")


def rows(factory, cid="c1"):
    """(role, status, content) as stored, read through an independent session."""
    s = factory()
    try:
        msgs = s.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.id))
        return [(m.role, m.status, m.content) for m in msgs]
    finally:
        s.close()


def stored_last_task_id(factory, cid="c1"):
    s = factory()
    try:
        conv = s.get(Conversation, cid)
        return conv.last_task_id if conv else None
    finally:
        s.close()


def fail_writes(monkeypatch, cause="connection refused", params=None):
    def boom(self, *a, **kw):
        raise OperationalError("INSERT INTO messages ...", params or {}, Exception(cause))

    monkeypatch.setattr(ConversationRepository, "add_message", boom)


# ---- what gets saved ---------------------------------------------------------------------
def test_user_message_saved_before_graph_runs_and_assistant_after(factory, service):
    seen_by_model = []

    def probe(message, ctx):
        seen_by_model.append(rows(factory))  # what is in the database when the model is called
        return ActionPlan(intent="create", title="Write report", interpretation="t")

    runner = make_runner(factory, probe)
    r = runner.send("c1", "Create a task called Write report", "UTC")

    assert seen_by_model == [[("user", None, "Create a task called Write report")]]
    assert [(role, status) for role, status, _ in rows(factory)] == [("user", None), ("assistant", "success")]
    assert rows(factory)[1][2] == r.reply and "Created task #1" in r.reply
    assert stored_last_task_id(factory) == 1

    s = factory()
    try:  # workflow steps are stored for the Activity disclosure
        steps = s.scalars(select(Message).where(Message.role == "assistant")).one().steps
    finally:
        s.close()
    assert [st["key"] for st in steps][:2] == ["understand", "decide"]


def test_clarification_turn_is_saved_and_retained_as_context(runner, planner, factory, service):
    service.create_task("API integration tests")
    service.create_task("API documentation")

    r = say(runner, planner, "Complete the API task.", intent="complete", target_reference="API task")
    assert r.status == "clarify"
    assert [(role, status) for role, status, _ in rows(factory)] == [("user", None), ("assistant", "clarify")]
    assert stored_last_task_id(factory) is None

    say(runner, planner, "the documentation one", intent="complete", target_reference="API documentation")
    history = planner.contexts[1]["history"]  # what the model saw on the second turn
    assert history[0] == "User: Complete the API task."
    assert history[1].startswith("Assistant: I found multiple matching tasks: #1 — API integration tests #2")
    assert service.get_task(2).status.value == "completed" and service.get_task(1).status.value == "pending"


def test_error_turns_are_saved(factory, service):
    # 1) task not found
    p = CapturingPlanner()
    runner = make_runner(factory, p)
    r = say(runner, p, "complete the deployment checklist", intent="complete", target_reference="deployment checklist")
    assert r.status == "error"
    assert rows(factory)[-1][1] == "error" and "deployment checklist" in rows(factory)[-1][2]

    # 2) the model is unavailable: safe message stored, tasks untouched
    def down(message, ctx):
        raise RuntimeError("provider down")

    runner = make_runner(factory, down)
    r = runner.send("c2", "create a task", "UTC")
    assert rows(factory, "c2") == [
        ("user", None, "create a task"),
        ("assistant", "error", "I couldn't interpret that request right now.\nYour tasks were not changed."),
    ]
    assert service.metrics()["total"] == 0
    assert r.status == "error"


def test_unsupported_cancelled_and_deleted_turns_are_saved(runner, planner, factory, service):
    service.create_task("Old resume task")
    say(runner, planner, "Email my manager", intent="unsupported")
    assert rows(factory)[-1][:2] == ("assistant", "unsupported")

    r = say(runner, planner, "Delete the old resume task", intent="delete", target_reference="old resume")
    assert r.status == "awaiting_approval"
    assert rows(factory)[-1][:2] == ("assistant", "awaiting_approval")

    runner.resume("c1", False)  # the dialog click is not a chat message: only the reply is stored
    assert rows(factory)[-1] == ("assistant", "cancelled", "Deletion cancelled.")
    assert [role for role, *_ in rows(factory)].count("user") == 2

    say(runner, planner, "Delete the old resume task", intent="delete", target_reference="old resume")
    runner.resume("c1", True)
    assert rows(factory)[-1][1] == "success" and "Deleted task #1" in rows(factory)[-1][2]
    assert stored_last_task_id(factory) is None  # deleting the task clears the reference
    assert service.metrics()["total"] == 0


# ---- context loading ------------------------------------------------------------------------
def test_saved_context_is_loaded_before_every_turn(runner, planner, factory):
    say(runner, planner, "Create a task called Write report", intent="create", title="Write report")
    say(runner, planner, "Show my tasks", intent="list")

    first, second = planner.contexts
    assert first["history"] == [] and first["last_task_id"] is None
    assert second["last_task_id"] == 1
    assert second["history"] == [
        "User: Create a task called Write report",
        "Assistant: Created task #1 — Write report.",
    ]


def test_context_is_bounded_to_the_most_recent_messages(runner, planner, factory):
    for i in range(6):
        say(runner, planner, f"list {i}", intent="list")
    last = planner.contexts[-1]["history"]
    assert len(last) == 6 and last[-2] == "User: list 4"  # 6 newest saved messages, oldest first


# ---- restart survival -------------------------------------------------------------------------
def test_conversation_context_survives_a_backend_restart(factory, planner, service):
    before = make_runner(factory, planner)
    say(before, planner, "Create a task called Write report", intent="create", title="Write report")

    after = make_runner(factory, planner)  # "restart": new graph, empty in-memory state, same database
    r = say(after, planner, "Make it high priority", intent="update", priority="high")

    assert r.status == "success" and "Updated task #1" in r.reply  # "it" still means task 1
    assert service.get_task(1).priority.value == "high"
    assert planner.contexts[-1]["history"][0] == "User: Create a task called Write report"


def test_without_persistence_a_restart_loses_the_context(factory, planner, service):
    """Control for the test above: this is the behaviour persistence fixes."""
    before = make_runner(factory, planner, persist=False)
    say(before, planner, "Create a task called Write report", intent="create", title="Write report")
    after = make_runner(factory, planner, persist=False)
    r = say(after, planner, "Make it high priority", intent="update", priority="high")
    assert r.status == "clarify" and service.get_task(1).priority.value == "medium"


# ---- pending approvals are never restored --------------------------------------------------------
def test_pending_delete_is_not_restored_after_restart(factory, planner, service):
    service.create_task("Fix production deployment")
    before = make_runner(factory, planner)
    r = say(before, planner, "Delete the deployment task", intent="delete", target_reference="deployment")
    assert r.status == "awaiting_approval"

    after = make_runner(factory, planner)
    with pytest.raises(NoPendingApproval):
        after.resume("c1", True)  # approval cannot be replayed against a restarted server
    assert service.get_task(1)
    assert rows(factory)[-1][1] == "awaiting_approval"  # nothing new stored

    # nor can it be smuggled in through chat: "yes, delete it" just asks which task
    r = say(after, planner, "yes, delete it", intent="delete", target_reference="it")
    assert r.status == "clarify" and service.get_task(1)


def test_resume_after_restart_returns_http_409(factory, planner, service):
    service.create_task("Fix production deployment")
    say(make_runner(factory, planner), planner, "Delete the deployment task",
        intent="delete", target_reference="deployment")

    app = create_app()
    app.state.agent_runner = make_runner(factory, planner)  # the restarted server
    client = TestClient(app)
    res = client.post("/api/agent/resume", json={"thread_id": "c1", "approved": True})
    assert res.status_code == 409
    assert client.get("/api/tasks/1").status_code == 200


# ---- best-effort: storage failures never break tasks ------------------------------------------------
def test_write_failures_do_not_break_task_operations_and_log_safely(runner, planner, factory, service,
                                                                    monkeypatch, caplog):
    fail_writes(monkeypatch, cause="connection refused", params={"content": "my private note"})
    with caplog.at_level(logging.ERROR, logger="agent.persistence"):
        r = say(runner, planner, "Create a task called Write report", intent="create", title="Write report")

    assert r.status == "success" and "Created task #1" in r.reply  # the task operation is unaffected
    assert service.get_task(1).title == "Write report"
    monkeypatch.undo()
    assert rows(factory) == []  # nothing (and no half-written data) was stored

    logged = caplog.text
    assert "operation=save_user_message" in logged and "operation=save_assistant_message" in logged
    assert "cause_type=OperationalError" in logged and "cause=connection refused" in logged
    assert "my private note" not in logged and "INSERT INTO" not in logged and "Traceback" not in logged


def test_load_failure_falls_back_to_in_memory_context(runner, planner, service, monkeypatch, caplog):
    def boom(self, *a, **kw):
        raise ConversationPersistenceError("Conversation data could not be stored or loaded.")

    monkeypatch.setattr(ConversationService, "load_context", boom)
    with caplog.at_level(logging.ERROR, logger="agent.persistence"):
        say(runner, planner, "Create a task called Write report", intent="create", title="Write report")
        r = say(runner, planner, "Make it high priority", intent="update", priority="high")

    assert r.status == "success" and service.get_task(1).priority.value == "high"  # "it" still works
    assert "operation=load_context" in caplog.text


def test_stale_saved_context_is_never_used_after_a_failed_save(runner, planner, factory, service, monkeypatch):
    """If the last save failed, the database is behind memory; "it" must not resolve to the old task."""
    service.create_task("First")
    service.create_task("Second")
    say(runner, planner, "Update task 1", intent="update", target_task_id=1, priority="low")
    assert stored_last_task_id(factory) == 1

    real = ConversationService.record_assistant_message

    def flaky(self, *a, **kw):
        raise ConversationPersistenceError("Conversation data could not be stored or loaded.")

    monkeypatch.setattr(ConversationService, "record_assistant_message", flaky)
    say(runner, planner, "Update task 2", intent="update", target_task_id=2, priority="low")
    monkeypatch.setattr(ConversationService, "record_assistant_message", real)
    assert stored_last_task_id(factory) == 1 and "c1" in runner._unsynced  # database is now stale

    r = say(runner, planner, "Make it high priority", intent="update", priority="high")
    assert r.status == "success" and "Updated task #2" in r.reply  # in-memory state (task 2) won
    assert service.get_task(2).priority.value == "high" and service.get_task(1).priority.value == "low"
    assert "c1" not in runner._unsynced and stored_last_task_id(factory) == 2  # resynchronised


def test_invalid_thread_id_is_not_stored_but_tasks_still_work(runner, planner, factory, service, caplog):
    with caplog.at_level(logging.ERROR, logger="agent.persistence"):
        r = say(runner, planner, "Create a task called X", thread="bad id!", intent="create", title="X")
    assert r.status == "success" and service.get_task(1).title == "X"
    s = factory()
    try:
        assert s.scalar(select(Conversation)) is None
    finally:
        s.close()
    assert "Invalid conversation id." in caplog.text


def test_graph_crash_is_recorded_generically_and_still_raised(runner, planner, factory, monkeypatch):
    say(runner, planner, "Create a task called X", intent="create", title="X")
    assert stored_last_task_id(factory) == 1

    def crash(*a, **kw):
        raise RuntimeError("unexpected internal failure")

    monkeypatch.setattr(runner.graph, "invoke", crash)
    with pytest.raises(RuntimeError):
        runner.send("c1", "anything", "UTC")
    assert rows(factory)[-2:] == [("user", None, "anything"), ("assistant", "error", CRASH_REPLY)]
    assert stored_last_task_id(factory) == 1  # a crash does not disturb the saved reference


def test_no_persistence_configured_touches_no_conversation_tables(factory, planner, service):
    runner = make_runner(factory, planner, persist=False)
    say(runner, planner, "Create a task called X", intent="create", title="X")
    s = factory()
    try:
        assert s.scalar(select(Message)) is None and s.scalar(select(Conversation)) is None
    finally:
        s.close()
