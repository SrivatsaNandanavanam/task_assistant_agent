"""Thin facade the API uses: send a message, or resume a paused (delete) thread.

Conversation persistence is an optional, best-effort dependency: when a session factory is given,
each turn's messages are saved and the saved context is loaded before the graph runs. A storage
failure is logged and never affects task operations. Pending delete approvals are NOT persisted;
they live only in the in-memory graph state, so after a restart `resume` safely finds nothing pending.
"""

import logging
import uuid
from collections.abc import Callable

from langgraph.types import Command

from app.agent.state import AgentState
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.agent import AgentResponse, PendingApproval, ReceiptStep
from app.services.conversation_service import (
    KEEP,
    ConversationContext,
    ConversationService,
    log_conversation_failure,
)

logger = logging.getLogger("agent.persistence")

# Stored when the graph itself crashes (the API separately returns a generic 500 to the client).
CRASH_REPLY = "Something went wrong while processing that request."


class NoPendingApproval(Exception):
    pass


_TURN_RESET = {
    "plan": None, "tool": None, "args": None, "target_id": None, "approval": None,
    "approved": None, "result": None, "steps": [], "reply": None, "status": None,
}


class AgentRunner:
    def __init__(self, graph, conversation_session_factory: Callable | None = None):
        """conversation_session_factory: zero-argument callable returning a SQLAlchemy Session, or None."""
        self.graph = graph
        self._conversation_session_factory = conversation_session_factory
        # Threads whose latest save failed: in-memory graph state is fresher than the database for these,
        # so their saved context is not used (a stale last_task_id could otherwise resolve "it" wrongly).
        self._unsynced: set[str] = set()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    # ---- public API -----------------------------------------------------------------------------
    def send(self, thread_id: str, message: str, timezone: str) -> AgentResponse:
        saved = self._load_context(thread_id)
        self._persist("save_user_message", thread_id, lambda s: s.record_user_message(thread_id, message))

        inputs: AgentState = {
            **_TURN_RESET,
            "thread_id": thread_id,
            "request_id": uuid.uuid4().hex[:12],
            "message": message,
            "timezone": timezone,
        }
        if saved is not None:  # otherwise fall back to whatever the in-memory graph state holds
            inputs["history"] = saved.history
            inputs["last_task_id"] = saved.last_task_id

        # Never start a new turn on a thread that is waiting for approval.
        if self._pending(thread_id) is not None:
            self.graph.invoke(Command(resume=False), self._config(thread_id))
        try:
            result = self.graph.invoke(inputs, self._config(thread_id))
        except Exception:
            self._save_crash(thread_id)
            raise
        response = self._response(thread_id, result)
        self._save_assistant(thread_id, response)
        return response

    def resume(self, thread_id: str, approved: bool) -> AgentResponse:
        if self._pending(thread_id) is None:
            raise NoPendingApproval(thread_id)
        try:
            result = self.graph.invoke(Command(resume=approved is True), self._config(thread_id))
        except Exception:
            self._save_crash(thread_id)
            raise
        response = self._response(thread_id, result)
        self._save_assistant(thread_id, response)
        return response

    # ---- persistence (best-effort) --------------------------------------------------------------
    def _load_context(self, thread_id: str) -> ConversationContext | None:
        if self._conversation_session_factory is None or thread_id in self._unsynced:
            return None
        ok, context = self._persist("load_context", thread_id, lambda s: s.load_context(thread_id))
        return context if ok else None

    def _save_assistant(self, thread_id: str, response: AgentResponse) -> None:
        ok, _ = self._persist(
            "save_assistant_message",
            thread_id,
            lambda s: s.record_assistant_message(
                thread_id,
                response.reply,
                response.status,
                [step.model_dump() for step in response.steps],
                response.last_task_id,
            ),
        )
        self._track_sync(thread_id, ok)

    def _save_crash(self, thread_id: str) -> None:
        ok, _ = self._persist(
            "save_assistant_message",
            thread_id,
            lambda s: s.record_assistant_message(thread_id, CRASH_REPLY, "error", None, KEEP),
        )
        self._track_sync(thread_id, ok)

    def _track_sync(self, thread_id: str, saved: bool) -> None:
        if self._conversation_session_factory is None:
            return
        (self._unsynced.discard if saved else self._unsynced.add)(thread_id)

    def _persist(self, operation: str, thread_id: str, fn):
        """Run fn(ConversationService) in its own session. Returns (succeeded, value); never raises."""
        if self._conversation_session_factory is None:
            return False, None
        session = None
        try:
            session = self._conversation_session_factory()
            return True, fn(ConversationService(ConversationRepository(session)))
        except Exception as exc:  # best-effort by design: recorded below, never propagated
            log_conversation_failure(
                logger, exc, operation=operation, thread_id=thread_id, status="failure"
            )
            return False, None
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:  # closing must never break a turn
                    pass

    # ---- graph plumbing -------------------------------------------------------------------------
    def _pending(self, thread_id: str):
        snapshot = self.graph.get_state(self._config(thread_id))
        for task in snapshot.tasks:
            for intr in task.interrupts:
                return intr.value
        return None

    def _response(self, thread_id: str, result: dict) -> AgentResponse:
        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = interrupts[0].value
            return AgentResponse(
                thread_id=thread_id,
                status="awaiting_approval",
                reply=f'Delete task #{payload["task"]["id"]} — {payload["task"]["title"]}? '
                      "Please confirm or cancel.",
                steps=[ReceiptStep(**s) for s in result["steps"]],
                pending_approval=PendingApproval(**payload),
                last_task_id=result.get("last_task_id"),
            )
        return AgentResponse(
            thread_id=thread_id,
            status=result["status"],
            reply=result["reply"],
            steps=[ReceiptStep(**s) for s in result["steps"]],
            last_task_id=result.get("last_task_id"),
        )
