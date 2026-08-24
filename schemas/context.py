"""Temporary context structures used to prepare one model request.

Context is assembled for a request and is not a long-term memory record. The
future ContextBuilder will decide which fields to populate and in what order.
This module only defines the shared shape that the builder and Agent runtime can
agree on.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from schemas.state import AgentState
from schemas.tool import ToolResult


class ContextMessage(BaseModel):
    """One normalized message included in the temporary conversation context."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1)


class Context(BaseModel):
    """Structured material that can later be rendered into model messages."""

    user_message: str = Field(min_length=1)
    conversation_history: list[ContextMessage] = Field(default_factory=list)
    state: AgentState | None = None
    system_instructions: list[str] = Field(default_factory=list)
    knowledge_results: list[dict[str, Any]] = Field(default_factory=list)
    skill_instructions: list[str] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
