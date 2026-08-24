"""Data contracts for future tool requests and tool results.

The models describe data only. Permission checks, validation, timeouts, retries,
and approval decisions belong to the future Harness layer rather than this
schema module.
"""

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """A normalized request to invoke one named tool."""

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = Field(default="agent", min_length=1)


class ToolResult(BaseModel):
    """A normalized result returned after a tool execution attempt."""

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    success: bool
    data: Any | None = None
    error: str | None = None
    requires_approval: bool = False
    duration_ms: float | None = Field(default=None, ge=0)
