from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message


class ConversationRepository:
    """Data access only. Writes flush but do not commit: the service owns the transaction."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, conversation_id: str) -> Conversation | None:
        return self.session.get(Conversation, conversation_id)

    def ensure(self, conversation_id: str, now: datetime) -> Conversation:
        """Return the conversation, creating it if needed (safe if two requests race to create it)."""
        conversation = self.get(conversation_id)
        if conversation is not None:
            return conversation
        conversation = Conversation(id=conversation_id, created_at=now, updated_at=now)
        self.session.add(conversation)
        try:
            self.session.flush()
        except IntegrityError:
            # A concurrent request created it first. Nothing else is pending yet, so a rollback is safe.
            self.session.rollback()
            conversation = self.get(conversation_id)
            if conversation is None:
                raise
        return conversation

    def add_message(
        self,
        conversation: Conversation,
        role: str,
        content: str,
        status: str | None,
        steps: list[dict[str, Any]] | None,
        now: datetime,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            status=status,
            steps=steps,
            created_at=now,
        )
        self.session.add(message)
        conversation.updated_at = now
        self.session.flush()
        return message

    def list_messages(self, conversation_id: str, limit: int) -> list[Message]:
        """The most recent `limit` messages, oldest first."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
        return list(reversed(list(self.session.scalars(stmt))))

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
