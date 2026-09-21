"""Read-only access to a conversation's saved messages.

SECURITY LIMITATION (must be resolved before production exposure): there is no authentication and
no conversation ownership. The `thread_id` (a random UUID created by the browser) is the *only*
credential: anyone who knows it can read that conversation, and anyone who can reach this API can
try ids. Row-level security is currently disabled on the Supabase tables, so this API layer is the
only access control. Before exposing this beyond a trusted environment, add authentication, tie each
conversation to its owner, and enable RLS. Mitigations in place: access is by exact id only (there is
no list/search endpoint), unknown and empty conversations look identical, responses are `no-store`,
and page size is bounded.
"""

import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from app.core.config import get_settings
from app.core.logging import log_event
from app.db.session import get_session_factory
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation import ConversationMessageOut
from app.services.conversation_service import (
    CONVERSATION_ID_PATTERN,
    ConversationPersistenceError,
    ConversationService,
    ConversationValidationError,
    log_conversation_failure,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
logger = logging.getLogger("api.conversations")

MAX_PAGE = get_settings().max_conversation_page


def get_conversation_service() -> Iterator[ConversationService]:
    session = get_session_factory()()
    try:
        yield ConversationService(ConversationRepository(session))
    finally:
        session.close()


@router.get(
    "/{thread_id}/messages",
    response_model=list[ConversationMessageOut],
    summary="List saved messages of one conversation",
    description=(
        "Returns the most recent messages of the conversation, oldest first (ordered by insertion, "
        "which is chronological). Unknown and empty conversations both return an empty list. "
        "**No authentication or ownership check yet: the thread_id is the only credential.**"
    ),
)
def list_messages(
    response: Response,
    thread_id: str = Path(pattern=CONVERSATION_ID_PATTERN, description="The conversation (thread) id."),
    limit: int | None = Query(
        None, ge=1, le=MAX_PAGE, description=f"Number of most recent messages (default 50, max {MAX_PAGE})."
    ),
    service: ConversationService = Depends(get_conversation_service),
):
    try:
        messages = service.list_messages(thread_id, limit)
    except ConversationValidationError:
        raise HTTPException(422, "Invalid conversation id or limit.") from None
    except ConversationPersistenceError as exc:
        log_conversation_failure(logger, exc, operation="get_conversation_messages",
                                 thread_id=thread_id, status="failure")
        raise HTTPException(503, "Conversation history is temporarily unavailable.") from None
    except Exception as exc:  # last-resort guard: never leak internals
        log_conversation_failure(logger, exc, operation="get_conversation_messages",
                                 thread_id=thread_id, status="failure")
        raise HTTPException(500, "Something went wrong.") from None

    log_event(logger, operation="get_conversation_messages", thread_id=thread_id,
              result_count=len(messages), status="success")  # counts only, never message text
    response.headers["Cache-Control"] = "no-store"  # private chat data must not be cached
    return messages
