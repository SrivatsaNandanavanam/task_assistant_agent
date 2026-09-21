from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.agent import ReceiptStep


class ConversationMessageOut(BaseModel):
    """One stored chat message. The conversation id is the URL path, so it is not repeated here."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["user", "assistant"]
    content: str
    # Assistant messages only; null for user messages.
    status: Literal["success", "clarify", "unsupported", "cancelled", "error", "awaiting_approval"] | None
    steps: list[ReceiptStep] | None
    created_at: datetime
