"""Temporary context structures used to prepare one model request.

Context is assembled for one request and is not a long-term memory record.
Memory adapters provide summaries, episodic records, and profiles; the
ContextBuilder decides which of those materials enter the model request.
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
    memory_summary: str | None = None
    episodic_memories: list[dict[str, Any]] = Field(default_factory=list)
    user_profile: dict[str, Any] = Field(default_factory=dict)
    state: AgentState | None = None
    system_instructions: list[str] = Field(default_factory=list)
    knowledge_results: list[dict[str, Any]] = Field(default_factory=list)
    skill_instructions: list[str] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
