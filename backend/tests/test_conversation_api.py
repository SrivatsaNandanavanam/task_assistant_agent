"""GET /api/conversations/{thread_id}/messages (read-only chat history)."""

import logging
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.main import create_app
from app.models.conversation import Conversation, Message
from app.repositories.conversation_repository import ConversationRepository
from app.services.conversation_service import ConversationService
from app.services.task_service import utcnow

PRIVATE = "my very private note"
STEPS = [
    {"key": "understand", "label": "Understand request", "status": "done", "detail": "Create a task"},
    {"key": "return", "label": "Return result", "status": "done", "detail": None},
]
MAX_PAGE = get_settings().max_conversation_page


@pytest.fixture
def client(factory):
    return TestClient(create_app())  # no lifespan: uses the in-memory database from the `factory` fixture


@pytest.fixture
def chat(session):
    """Writes conversations through the same service the agent uses."""
    return ConversationService(ConversationRepository(session))


def url(thread_id: str) -> str:
    return f"/api/conversations/{thread_id}/messages"


def counts(factory):
    s = factory()
    try:
        return s.scalar(select(func.count()).select_from(Conversation)), s.scalar(select(func.count()).select_from(Message))
    finally:
        s.close()


# ---- happy path -----------------------------------------------------------------------------
def test_returns_messages_with_the_supported_fields(client, chat):
    chat.record_user_message("c1", "Create a task called demo")
    chat.record_assistant_message("c1", "Created task #1 — demo.", "success", STEPS, last_task_id=1)

    res = client.get(url("c1"))
    assert res.status_code == 200
    user, assistant = res.json()

    assert set(user) == set(assistant) == {"id", "role", "content", "status", "steps", "created_at"}
    assert "conversation_id" not in user  # already in the URL; not repeated
    assert (user["role"], user["content"], user["status"], user["steps"]) == ("user", "Create a task called demo", None, None)
    assert (assistant["role"], assistant["status"], assistant["steps"]) == ("assistant", "success", STEPS)
    assert isinstance(user["id"], int) and user["id"] != assistant["id"]
    assert datetime.fromisoformat(user["created_at"]).tzinfo is not None  # timezone-aware timestamps


def test_response_is_marked_private_and_not_cacheable(client, chat):
    chat.record_user_message("c1", "hello")
    assert client.get(url("c1")).headers["cache-control"] == "no-store"


def test_all_assistant_statuses_round_trip(client, chat):
    statuses = ["success", "clarify", "unsupported", "cancelled", "error", "awaiting_approval"]
    for s in statuses:
        chat.record_assistant_message("c1", f"reply {s}", s)
    assert [m["status"] for m in client.get(url("c1")).json()] == statuses


# ---- ordering ------------------------------------------------------------------------------------
def test_messages_are_chronological_oldest_first(client, chat):
    for i in range(6):
        (chat.record_user_message if i % 2 == 0 else lambda c, t: chat.record_assistant_message(c, t, "success"))(
            "c1", f"message {i}")
    body = client.get(url("c1")).json()
    assert [m["content"] for m in body] == [f"message {i}" for i in range(6)]
    assert [m["id"] for m in body] == sorted(m["id"] for m in body)
    stamps = [datetime.fromisoformat(m["created_at"]) for m in body]
    assert stamps == sorted(stamps)


def test_ordering_is_deterministic_when_timestamps_are_identical(client, factory, chat):
    """created_at can tie (same clock tick); insertion order (id) is the stable tiebreaker."""
    chat.record_user_message("c1", "seed")  # creates the conversation
    same = utcnow()
    s = factory()
    for i in range(5):
        s.add(Message(conversation_id="c1", role="user", content=f"tie {i}", created_at=same))
    s.commit()
    s.close()
    first = [m["content"] for m in client.get(url("c1")).json()]
    assert first == ["seed"] + [f"tie {i}" for i in range(5)]
    assert [m["content"] for m in client.get(url("c1")).json()] == first  # same answer every time


# ---- unknown / empty ---------------------------------------------------------------------------
def test_unknown_conversation_returns_empty_list_and_creates_nothing(client, factory):
    res = client.get(url("never-used"))
    assert res.status_code == 200 and res.json() == []
    assert counts(factory) == (0, 0)  # a GET never writes


def test_empty_conversation_returns_empty_list(client, factory, session):
    repo = ConversationRepository(session)
    repo.ensure("empty-one", utcnow())
    repo.commit()
    assert counts(factory) == (1, 0)
    res = client.get(url("empty-one"))
    assert res.status_code == 200 and res.json() == []
    assert res.json() == client.get(url("never-used")).json()  # no way to tell "exists" from "unknown"


# ---- thread id validation -----------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "bad%20id",                 # space
    "a.b",                      # dot
    "x" * 101,                  # too long
    "id;DROP%20TABLE%20messages",
    "%25",                      # a literal '%'
    "%C3%A9",                   # non-ASCII
    "abc%0A",                   # trailing newline (regex `$` would accept it; fullmatch must not)
    "abc%00",                   # NUL
    "a%2Fb",                    # encoded slash
])
def test_invalid_thread_ids_are_rejected_before_any_query(client, factory, chat, bad):
    chat.record_user_message("abc", PRIVATE)
    res = client.get(f"/api/conversations/{bad}/messages")
    assert res.status_code in (404, 422)
    assert PRIVATE not in res.text
    assert counts(factory) == (1, 1)


def test_invalid_id_shapes_get_422_with_the_pattern_in_the_error(client):
    res = client.get(url("bad%20id"))
    assert res.status_code == 422
    assert "pattern" in res.text.lower()  # points at the id rule; no SQL or internals


def test_valid_id_shapes_are_accepted(client, chat):
    for cid in ("t1", "abc", "3f2b8c1e-9d4a-4c1b-8a55-0f7e2d6a9b10", "x" * 100, "under_score-dash"):
        assert client.get(url(cid)).status_code == 200


def test_validation_uses_the_same_pattern_as_the_persistence_layer(client, chat):
    """Anything the service refuses to store must be refused by the API too, and vice versa."""
    from app.services.conversation_service import ConversationValidationError

    for cid in ("bad id", "abc\n", "a.b", "x" * 101, "é"):
        with pytest.raises(ConversationValidationError):
            chat.record_user_message(cid, "hi")
    for cid in ("abc", "a_b", "a-b", "x" * 100):
        chat.record_user_message(cid, "hi")
        assert client.get(url(cid)).status_code == 200


def test_route_is_read_only(client, chat):
    chat.record_user_message("c1", "keep me")
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)(url("c1")).status_code == 405
    assert [m["content"] for m in client.get(url("c1")).json()] == ["keep me"]


# ---- page size ----------------------------------------------------------------------------------
def test_default_page_returns_the_latest_messages_oldest_first(client, chat):
    for i in range(1, 61):
        chat.record_user_message("c1", f"m{i}")
    body = client.get(url("c1")).json()
    assert len(body) == 50  # default page
    assert body[0]["content"] == "m11" and body[-1]["content"] == "m60"


def test_limit_selects_the_most_recent_n(client, chat):
    for i in range(1, 6):
        chat.record_user_message("c1", f"m{i}")
    assert [m["content"] for m in client.get(url("c1"), params={"limit": 2}).json()] == ["m4", "m5"]
    assert [m["content"] for m in client.get(url("c1"), params={"limit": 1}).json()] == ["m5"]


def test_maximum_page_size_is_enforced(client, chat):
    for i in range(MAX_PAGE + 5):
        chat.record_user_message("c1", f"m{i}")
    at_max = client.get(url("c1"), params={"limit": MAX_PAGE})
    assert at_max.status_code == 200 and len(at_max.json()) == MAX_PAGE
    assert at_max.json()[-1]["content"] == f"m{MAX_PAGE + 4}"  # the newest are kept
    assert at_max.json()[0]["content"] == "m5"

    for too_big in (MAX_PAGE + 1, 10_000, 10**12):
        assert client.get(url("c1"), params={"limit": too_big}).status_code == 422  # never unbounded


@pytest.mark.parametrize("bad_limit", ["0", "-1", "abc", "1.5", ""])
def test_invalid_limits_are_rejected(client, chat, bad_limit):
    chat.record_user_message("c1", "hi")
    assert client.get(url("c1"), params={"limit": bad_limit}).status_code == 422


def test_no_request_can_return_more_than_the_maximum_page(client, chat):
    for i in range(MAX_PAGE + 20):
        chat.record_user_message("c1", f"m{i}")
    for params in ({}, {"limit": MAX_PAGE}, {"limit": 1}):
        assert len(client.get(url("c1"), params=params).json()) <= MAX_PAGE


# ---- isolation ---------------------------------------------------------------------------------
def test_conversations_are_isolated(client, chat):
    chat.record_user_message("alice-thread", "alice secret")
    chat.record_assistant_message("alice-thread", "reply to alice", "success")
    chat.record_user_message("bob-thread", "bob secret")

    alice = client.get(url("alice-thread")).text
    bob = client.get(url("bob-thread")).text
    assert "alice secret" in alice and "bob secret" not in alice
    assert "bob secret" in bob and "alice secret" not in bob and "reply to alice" not in bob


def test_lookalike_ids_never_match_each_other(client, chat):
    """Exact-match lookup: '_' is a literal character, not a LIKE wildcard, and ids are not prefix-matched."""
    for cid in ("a_b", "axb", "a-b", "a_bc", "a"):
        chat.record_user_message(cid, f"only-{cid}")
    for cid in ("a_b", "axb", "a-b", "a_bc", "a"):
        assert [m["content"] for m in client.get(url(cid)).json()] == [f"only-{cid}"]


def test_there_is_no_endpoint_to_list_conversations(client, chat):
    chat.record_user_message("c1", PRIVATE)
    for path in ("/api/conversations", "/api/conversations/", "/api/conversations/messages"):
        res = client.get(path)
        assert res.status_code in (404, 405) and PRIVATE not in res.text


# ---- failures and safe errors ---------------------------------------------------------------------
def test_database_read_failure_returns_safe_503_and_logs_no_sql_or_text(client, chat, monkeypatch, caplog):
    chat.record_user_message("c1", PRIVATE)

    def boom(self, *a, **kw):
        raise OperationalError(
            "SELECT messages.content FROM messages WHERE conversation_id = :cid",
            {"cid": "c1", "content": PRIVATE},
            Exception("connection to db.secret-host.example refused"),
        )

    monkeypatch.setattr(ConversationRepository, "list_messages", boom)
    with caplog.at_level(logging.DEBUG):
        res = client.get(url("c1"))

    assert res.status_code == 503
    assert res.json() == {"detail": "Conversation history is temporarily unavailable."}
    for leaked in ("SELECT", "messages", "secret-host", PRIVATE, "Traceback", "OperationalError", "refused"):
        assert leaked not in res.text

    logged = caplog.text
    assert "operation=get_conversation_messages" in logged and "status=failure" in logged
    assert "cause_type=OperationalError" in logged  # a developer can still see what kind of failure it was
    for leaked in ("SELECT", "FROM messages", PRIVATE, "Traceback", ":cid"):
        assert leaked not in logged


def test_unexpected_error_returns_generic_500_and_logs_no_traceback_or_text(client, chat, monkeypatch, caplog):
    chat.record_user_message("c1", PRIVATE)

    def boom(self, *a, **kw):
        raise RuntimeError(f"unexpected failure while reading {PRIVATE}")

    monkeypatch.setattr(ConversationRepository, "list_messages", boom)
    with caplog.at_level(logging.DEBUG):
        res = client.get(url("c1"))

    assert res.status_code == 500 and res.json() == {"detail": "Something went wrong."}
    assert PRIVATE not in res.text and "RuntimeError" not in res.text and "Traceback" not in res.text
    assert "error_type=RuntimeError" in caplog.text and "origin=" in caplog.text  # where, not what
    assert PRIVATE not in caplog.text and "Traceback" not in caplog.text


def test_service_still_usable_after_a_failed_read(client, chat, monkeypatch):
    chat.record_user_message("c1", "hello")
    with monkeypatch.context() as m:
        m.setattr(ConversationRepository, "list_messages",
                  lambda self, *a, **kw: (_ for _ in ()).throw(OperationalError("SELECT", {}, Exception("x"))))
        assert client.get(url("c1")).status_code == 503
    assert client.get(url("c1")).status_code == 200  # recovers on the next request


def test_successful_reads_log_counts_never_message_text(client, chat, caplog):
    chat.record_user_message("c1", PRIVATE)
    chat.record_assistant_message("c1", f"reply containing {PRIVATE}", "success")
    with caplog.at_level(logging.DEBUG):
        assert client.get(url("c1")).status_code == 200
    assert "operation=get_conversation_messages" in caplog.text and "result_count=2" in caplog.text
    assert PRIVATE not in caplog.text


def test_sql_like_content_is_returned_as_plain_text(client, chat, factory):
    payload = "x'); DROP TABLE messages; --"
    chat.record_user_message("c1", payload)
    assert client.get(url("c1")).json()[0]["content"] == payload
    assert counts(factory) == (1, 1)


# ---- contract / compatibility ----------------------------------------------------------------------
def test_openapi_documents_the_route_pattern_bounds_and_security_limitation(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/api/conversations/{thread_id}/messages"]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert params["thread_id"]["schema"]["pattern"] == "^[A-Za-z0-9_-]{1,100}$"
    assert params["limit"]["schema"]["anyOf"][0]["maximum"] == MAX_PAGE
    assert "No authentication or ownership check yet" in op["description"]


def test_existing_endpoints_are_unaffected(client):
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/tasks", json={"title": "still works"}).status_code == 201
    assert client.get("/api/tasks/metrics").json()["total"] == 1
    assert client.post("/api/agent/resume", json={"thread_id": "zzz", "approved": True}).status_code == 409
