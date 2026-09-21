"""Thin facade the API uses: send a message, or resume a paused (delete) thread."""

import uuid

from langgraph.types import Command

from app.agent.state import AgentState
from app.schemas.agent import AgentResponse, PendingApproval, ReceiptStep


class NoPendingApproval(Exception):
    pass


_TURN_RESET = {
    "plan": None, "tool": None, "args": None, "target_id": None, "approval": None,
    "approved": None, "result": None, "steps": [], "reply": None, "status": None,
}


class AgentRunner:
    def __init__(self, graph):
        self.graph = graph

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def send(self, thread_id: str, message: str, timezone: str) -> AgentResponse:
        inputs: AgentState = {
            **_TURN_RESET,
            "thread_id": thread_id,
            "request_id": uuid.uuid4().hex[:12],
            "message": message,
            "timezone": timezone,
        }
        # Never start a new turn on a thread that is waiting for approval.
        if self._pending(thread_id) is not None:
            self.graph.invoke(Command(resume=False), self._config(thread_id))
        result = self.graph.invoke(inputs, self._config(thread_id))
        return self._response(thread_id, result)

    def resume(self, thread_id: str, approved: bool) -> AgentResponse:
        if self._pending(thread_id) is None:
            raise NoPendingApproval(thread_id)
        result = self.graph.invoke(Command(resume=approved is True), self._config(thread_id))
        return self._response(thread_id, result)

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
