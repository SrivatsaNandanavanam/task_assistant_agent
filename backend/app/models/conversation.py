from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, UTCDateTime

# BigInteger on PostgreSQL; plain INTEGER on SQLite (required for its rowid autoincrement).
_BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Conversation(Base):
    """One chat thread. `id` is the frontend's thread_id."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    # Most recently referenced task, for follow-ups like "make it high priority".
    # Deliberately not a foreign key: the task may be deleted later.
    last_task_id: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    # Assistant turns only: success / clarify / unsupported / cancelled / error / awaiting_approval.
    status: Mapped[str | None] = mapped_column(String(32), default=None)
    # Safe workflow steps shown in the "Activity" disclosure (never prompts or reasoning).
    steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON(none_as_null=True), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
