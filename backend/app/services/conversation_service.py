import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.models.conversation import Message
from app.repositories.conversation_repository import ConversationRepository
from app.services.task_service import utcnow

# Same characters the frontend's crypto.randomUUID() produces, plus the short ids used in tests.
CONVERSATION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,100}$"
_CONVERSATION_ID_RE = re.compile(CONVERSATION_ID_PATTERN)

ASSISTANT_STATUSES = frozenset(
    {"success", "clarify", "unsupported", "cancelled", "error", "awaiting_approval"}
)


class ConversationError(Exception):
    """Base class for conversation-storage errors. Messages are safe to log, never contain secrets."""


class ConversationValidationError(ConversationError):
    pass


class ConversationPersistenceError(ConversationError):
    """The database could not store or load conversation data (details are on __cause__)."""


class _Keep:
    """Marker meaning "leave last_task_id as it is" (as opposed to None, which clears it)."""

    def __repr__(self) -> str:
        return "KEEP"


KEEP = _Keep()


@dataclass(frozen=True)
class ConversationContext:
    """What the model is given before each turn: the last task referenced and recent messages."""

    last_task_id: int | None
    history: list[str]  # "User: ..." / "Assistant: ..." lines, oldest first


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _one_line(text: object, limit: int = 300) -> str:
    return " ".join(str(text).split())[:limit]


def log_conversation_failure(logger: logging.Logger, exc: Exception, **fields) -> None:
    """Developer-side log line for a conversation-storage failure; never leaks chat text, SQL or secrets.

    SQLAlchemy errors embed the SQL statement *and its bound parameters* (the message text), and any
    traceback or message of an unexpected error could quote user data. So this logs only:
    - database errors: the type of the cause and the database driver's own message (no SQL, no params);
    - our own ConversationErrors: their fixed, generic message;
    - anything else: the exception type and where it was raised (file:line:function), no message.
    API keys are additionally masked by the log formatter.
    """
    fields = {**fields, "error_type": type(exc).__name__}
    cause = exc.__cause__ or (exc if isinstance(exc, SQLAlchemyError) else None)
    if cause is not None:
        fields["cause_type"] = type(cause).__name__
        fields["cause"] = _one_line(getattr(cause, "orig", None) or type(cause).__name__)
    elif isinstance(exc, ConversationError):
        fields["error"] = _one_line(exc)
    else:
        tb = exc.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        if tb is not None:
            fields["origin"] = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}:{tb.tb_frame.f_code.co_name}"
    logger.error(" ".join(f"{k}={v}" for k, v in fields.items() if v is not None))


class ConversationService:
    """Chat-log storage. Best-effort by design: callers decide how to handle ConversationError."""

    def __init__(self, repo: ConversationRepository):
        self.repo = repo
        self.settings = get_settings()

    # ---- validation helpers -------------------------------------------------
    @staticmethod
    def _check_id(conversation_id: str) -> str:
        # fullmatch: with `$`, re.match would also accept a trailing newline ("abc\n").
        if not isinstance(conversation_id, str) or not _CONVERSATION_ID_RE.fullmatch(conversation_id):
            raise ConversationValidationError("Invalid conversation id.")
        return conversation_id

    @staticmethod
    def _check_content(content: str) -> str:
        content = (content or "").strip()
        if not content:
            raise ConversationValidationError("Message content is required.")
        return content

    def _limit(self, limit: int | None, default: int = 50) -> int:
        if limit is None:
            return default
        if limit < 1:
            raise ConversationValidationError("Limit must be at least 1.")
        return min(limit, self.settings.max_conversation_page)

    def _run(self, fn):
        """Run a DB operation; convert database errors, leaving the session clean."""
        try:
            return fn()
        except SQLAlchemyError as exc:
            self.repo.rollback()
            raise ConversationPersistenceError("Conversation data could not be stored or loaded.") from exc

    # ---- writes -------------------------------------------------------------
    def record_user_message(self, conversation_id: str, content: str) -> Message:
        conversation_id = self._check_id(conversation_id)
        content = _clip(self._check_content(content), self.settings.max_message_length)

        def write() -> Message:
            now = utcnow()
            conversation = self.repo.ensure(conversation_id, now)
            message = self.repo.add_message(conversation, "user", content, None, None, now)
            self.repo.commit()
            return message

        return self._run(write)

    def record_assistant_message(
        self,
        conversation_id: str,
        content: str,
        status: str,
        steps: list[dict[str, Any]] | None = None,
        last_task_id: int | None | _Keep = KEEP,
    ) -> Message:
        """Store an assistant reply. last_task_id: an id sets it, None clears it, KEEP leaves it as is."""
        conversation_id = self._check_id(conversation_id)
        if status not in ASSISTANT_STATUSES:
            raise ConversationValidationError("Invalid assistant status.")
        content = _clip(self._check_content(content), self.settings.max_stored_reply_length)

        def write() -> Message:
            now = utcnow()
            conversation = self.repo.ensure(conversation_id, now)
            message = self.repo.add_message(conversation, "assistant", content, status, steps, now)
            if last_task_id is not KEEP:
                conversation.last_task_id = last_task_id
            self.repo.commit()
            return message

        return self._run(write)

    # ---- reads --------------------------------------------------------------
    def list_messages(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        """Most recent messages, oldest first. Unknown conversations yield an empty list."""
        conversation_id = self._check_id(conversation_id)
        return self._run(lambda: self.repo.list_messages(conversation_id, self._limit(limit)))

    def get_last_task_id(self, conversation_id: str) -> int | None:
        conversation_id = self._check_id(conversation_id)

        def read() -> int | None:
            conversation = self.repo.get(conversation_id)
            return conversation.last_task_id if conversation else None

        return self._run(read)

    def load_context(self, conversation_id: str, limit: int | None = None) -> ConversationContext:
        """Saved context for the next turn, read in one transaction. Unknown conversation: empty context.

        Entries are flattened to a single line and clipped. Stored assistant text can quote untrusted
        task titles, so flattening also stops a stored newline from forging a fake "User:" line.
        """
        conversation_id = self._check_id(conversation_id)
        limit = self._limit(limit, self.settings.context_message_limit)

        def read() -> ConversationContext:
            conversation = self.repo.get(conversation_id)
            if conversation is None:
                return ConversationContext(None, [])
            history = []
            for m in self.repo.list_messages(conversation_id, limit):
                label = "User" if m.role == "user" else "Assistant"
                text = _clip(" ".join(m.content.split()), self.settings.context_entry_max_chars)
                history.append(f"{label}: {text}")
            return ConversationContext(conversation.last_task_id, history)

        return self._run(read)
