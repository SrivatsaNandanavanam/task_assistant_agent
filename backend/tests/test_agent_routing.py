from datetime import datetime, timezone

import pytest

from app.agent.graph import build_graph
from app.agent.runner import AgentRunner, NoPendingApproval
from app.schemas.agent import ActionPlan


class ScriptedPlanner:
    """Stands in for the LLM: returns the next queued ActionPlan."""

    def __init__(self):
        self.queue: list[ActionPlan] = []
        self.calls = 0

    def push(self, **kw):
        kw.setdefault("interpretation", "test")
        self.queue.append(ActionPlan(**kw))

    def __call__(self, message, ctx):
        self.calls += 1
        return self.queue.pop(0)


@pytest.fixture
def planner():
    return ScriptedPlanner()


@pytest.fixture
def runner(factory, planner):
    return AgentRunner(build_graph(planner=planner, session_factory=factory))


def say(runner, planner, text, thread="t1", **plan):
    planner.push(**plan)
    return runner.send(thread, text, "America/Chicago")


def test_create_routes_to_create_tool(runner, planner, service):
    r = say(runner, planner, "Create a high-priority task to finish demo tomorrow at 8 PM",
            intent="create", title="Finish demo", priority="high",
            due_at=datetime(2030, 1, 2, 20, tzinfo=timezone.utc))
    assert r.status == "success" and "Created task #1" in r.reply
    assert r.last_task_id == 1
    assert [s.status for s in r.steps if s.key != "approval"] == ["done"] * 6
    assert next(s for s in r.steps if s.key == "tool").detail == "create_task"
    assert service.get_task(1).priority.value == "high"


def test_naive_due_date_interpreted_in_user_timezone(runner, planner, service):
    say(runner, planner, "make it", intent="create", title="x", due_at=datetime(2030, 1, 2, 20, 0))
    # 20:00 America/Chicago (CST, UTC-6) == 02:00 UTC next day
    assert service.get_task(1).due_at == datetime(2030, 1, 3, 2, 0, tzinfo=timezone.utc)


def test_list_and_search(runner, planner, service):
    service.create_task("API tests", priority="high")
    service.create_task("Groceries")
    r = say(runner, planner, "show open tasks", intent="list", status_filter="pending")
    assert "(2)" in r.reply
    r = say(runner, planner, "find api", intent="search", search_query="api")
    assert "API tests" in r.reply and "Groceries" not in r.reply
    r = say(runner, planner, "nothing", intent="search", search_query="zzz")
    assert r.reply == "No tasks found."


def test_update_then_follow_up_it(runner, planner, service):
    service.create_task("API integration tests")
    r = say(runner, planner, "Move the API integration tests task to Friday",
            intent="update", target_reference="API integration tests",
            due_at=datetime(2030, 1, 4, 17, tzinfo=timezone.utc))
    assert r.status == "success" and r.last_task_id == 1
    r = say(runner, planner, "Make it medium priority", intent="update", priority="medium")
    assert r.status == "success" and service.get_task(1).priority.value == "medium"


def test_it_without_context_asks(runner, planner, service):
    service.create_task("A")
    r = say(runner, planner, "make it high priority", intent="update", priority="high")
    assert r.status == "clarify"
    assert service.get_task(1).priority.value == "medium"


def test_complete_by_id_and_title(runner, planner, service):
    service.create_task("A")
    service.create_task("Write documentation")
    r = say(runner, planner, "Mark task 1 complete", intent="complete", target_task_id=1)
    assert r.status == "success" and service.get_task(1).status.value == "completed"
    r = say(runner, planner, "Complete the documentation task", intent="complete",
            target_reference="documentation task")
    assert r.status == "success" and service.get_task(2).status.value == "completed"


def test_invented_task_id_is_ignored(runner, planner, service):
    service.create_task("A")
    r = say(runner, planner, "complete my task", intent="complete", target_task_id=1)
    assert r.status == "clarify"
    assert service.get_task(1).status.value == "pending"


def test_not_found(runner, planner):
    r = say(runner, planner, "delete the deployment checklist", intent="complete",
            target_reference="deployment checklist")
    assert r.status == "error" and 'matching "deployment checklist"' in r.reply


def test_delete_pauses_for_approval_and_approve_deletes_only_target(runner, planner, service):
    service.create_task("Keep me")
    service.create_task("Fix production deployment")
    r = say(runner, planner, "Delete the deployment task", intent="delete", target_reference="deployment task")
    assert r.status == "awaiting_approval"
    assert r.pending_approval.task["id"] == 2
    assert next(s for s in r.steps if s.key == "approval").status == "waiting"
    assert service.get_task(2)  # nothing deleted yet
    r = runner.resume("t1", True)
    assert r.status == "success" and "Deleted task #2" in r.reply
    assert [t.id for t in service.list_tasks()] == [1]


def test_unsupported_executes_no_tool(runner, planner, service):
    r = say(runner, planner, "Email my manager", intent="unsupported")
    assert r.status == "unsupported" and "create, list, search, update, complete, and delete" in r.reply
    assert next(s for s in r.steps if s.key == "tool").detail == "No tool"
    assert service.metrics()["total"] == 0


def test_resume_without_pending_rejected(runner):
    with pytest.raises(NoPendingApproval):
        runner.resume("nope", True)
