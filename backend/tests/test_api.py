import pytest
from fastapi.testclient import TestClient

from app.agent.graph import build_graph
from app.agent.runner import AgentRunner
from app.main import create_app
from tests.test_agent_routing import ScriptedPlanner


@pytest.fixture
def api(factory):
    app = create_app()  # TestClient without lifespan keeps the in-memory DB from the fixture
    planner = ScriptedPlanner()
    app.state.agent_runner = AgentRunner(build_graph(planner=planner, session_factory=factory))
    return TestClient(app), planner


def test_task_crud_and_metrics(api):
    client, _ = api
    r = client.post("/api/tasks", json={"title": "Write tests", "priority": "high"})
    assert r.status_code == 201
    tid = r.json()["id"]
    assert client.get("/api/tasks/metrics").json() == {"total": 1, "open": 1, "completed": 0, "overdue": 0}
    assert client.patch(f"/api/tasks/{tid}", json={"priority": "low"}).json()["priority"] == "low"
    assert client.post(f"/api/tasks/{tid}/complete").json()["status"] == "completed"
    assert client.get("/api/tasks", params={"q": "write"}).json()[0]["id"] == tid
    assert client.delete(f"/api/tasks/{tid}").status_code == 204
    assert client.get(f"/api/tasks/{tid}").status_code == 404


def test_validation_errors_are_safe(api):
    client, _ = api
    assert client.post("/api/tasks", json={"title": "  "}).status_code == 422
    assert client.patch("/api/tasks/1", json={}).status_code in (404, 422)


def test_seed_never_overwrites(api):
    client, _ = api
    assert client.post("/api/tasks/seed").json()["created"] == 8
    assert client.post("/api/tasks/seed").json()["created"] == 0


def test_agent_delete_flow_over_http(api):
    client, planner = api
    client.post("/api/tasks", json={"title": "Old resume task"})
    from app.schemas.agent import ActionPlan
    planner.queue.append(ActionPlan(intent="delete", target_reference="old resume", interpretation="x"))
    body = {"thread_id": "abc", "message": "Delete the old resume task", "timezone": "UTC"}
    r = client.post("/api/agent/messages", json=body).json()
    assert r["status"] == "awaiting_approval" and r["pending_approval"]["task"]["id"] == 1
    assert client.get("/api/tasks/1").status_code == 200
    r = client.post("/api/agent/resume", json={"thread_id": "abc", "approved": True}).json()
    assert r["status"] == "success"
    assert client.get("/api/tasks/1").status_code == 404
    # nothing pending any more -> resume is rejected, cannot be replayed
    assert client.post("/api/agent/resume", json={"thread_id": "abc", "approved": True}).status_code == 409


def test_resume_unknown_thread_rejected(api):
    client, _ = api
    assert client.post("/api/agent/resume", json={"thread_id": "zzz", "approved": True}).status_code == 409


# ---- reopen endpoint ----------------------------------------------------------------
def test_reopen_endpoint_round_trip(api):
    client, _ = api
    tid = client.post("/api/tasks", json={"title": "Toggle me", "priority": "high"}).json()["id"]
    assert client.post(f"/api/tasks/{tid}/complete").json()["status"] == "completed"
    r = client.post(f"/api/tasks/{tid}/reopen")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending" and body["completed_at"] is None
    assert body["title"] == "Toggle me" and body["priority"] == "high"
    assert client.get(f"/api/tasks/{tid}").json()["status"] == "pending"  # really persisted
    assert client.get("/api/tasks/metrics").json() == {"total": 1, "open": 1, "completed": 0, "overdue": 0}
    assert client.post(f"/api/tasks/{tid}/complete").json()["status"] == "completed"  # and back again


def test_reopen_invalid_id_is_404(api):
    client, _ = api
    r = client.post("/api/tasks/999/reopen")
    assert r.status_code == 404 and "999" in r.json()["detail"]


def test_reopen_db_failure_returns_safe_500(api, monkeypatch):
    from sqlalchemy.exc import OperationalError

    client, _ = api
    tid = client.post("/api/tasks", json={"title": "x"}).json()["id"]
    client.post(f"/api/tasks/{tid}/complete")

    def fail(self, task):
        raise OperationalError("UPDATE", {}, Exception("disk I/O error at /secret/path"))

    monkeypatch.setattr("app.repositories.task_repository.TaskRepository.save", fail)
    r = client.post(f"/api/tasks/{tid}/reopen")
    assert r.status_code == 500 and r.json()["detail"] == "I couldn't save that change."
    assert "secret" not in r.text
    monkeypatch.undo()
    assert client.get(f"/api/tasks/{tid}").json()["status"] == "completed"
