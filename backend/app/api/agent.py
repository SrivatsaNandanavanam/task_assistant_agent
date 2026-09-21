import logging

from fastapi import APIRouter, HTTPException, Request

from app.agent.graph import build_graph
from app.agent.runner import AgentRunner, NoPendingApproval
from app.core.config import get_settings
from app.core.logging import log_event, log_failure
from app.db.session import get_session_factory
from app.schemas.agent import AgentResponse, MessageRequest, ResumeRequest

router = APIRouter(prefix="/api/agent", tags=["agent"])
logger = logging.getLogger("api.agent")


def get_runner(request: Request) -> AgentRunner:
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        runner = request.app.state.agent_runner = AgentRunner(
            build_graph(),
            conversation_session_factory=lambda: get_session_factory()(),  # same database as the tasks
        )
    return runner


@router.post("/messages", response_model=AgentResponse)
def send_message(body: MessageRequest, request: Request):
    settings = get_settings()
    if len(body.message) > settings.max_message_length:
        raise HTTPException(422, f"Messages can be at most {settings.max_message_length} characters.")
    log_event(logger, operation="request_received", thread_id=body.thread_id)
    try:
        return get_runner(request).send(body.thread_id, body.message.strip(), body.timezone)
    except Exception as exc:  # last-resort guard: never leak internals
        log_failure(logger, exc, operation="agent_invocation", status="failure")
        raise HTTPException(500, "Something went wrong. Your tasks were not changed.") from None


@router.post("/resume", response_model=AgentResponse)
def resume(body: ResumeRequest, request: Request):
    try:
        return get_runner(request).resume(body.thread_id, body.approved)
    except NoPendingApproval:
        raise HTTPException(409, "There is no pending confirmation for this conversation.") from None
    except Exception as exc:
        log_failure(logger, exc, operation="agent_resume", status="failure")
        raise HTTPException(500, "Something went wrong. Your tasks were not changed.") from None
