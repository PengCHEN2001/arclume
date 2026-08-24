"""Public HTTP request and response models.

These models define the boundary between external clients and the application.
They intentionally contain only transport-level data. Agent state, prompt
context, and tool execution data live in their own schema modules.
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Payload accepted by the public chat endpoint."""

    message: str = Field(min_length=1, description="The user's message")
    user_id: str = Field(
        default="anonymous",
        min_length=1,
        description="Stable identifier for the end user",
    )
    conversation_id: str | None = Field(
        default=None,
        description="Optional identifier for a continuing conversation",
    )


class ChatResponse(BaseModel):
    """Stable response shape returned by the public chat endpoint."""

    message: str
    model: str
    conversation_id: str | None = None
