"""Structured state for one active customer-support case."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    """High-level lifecycle values for an active support case."""

    NEW = "new"
    ACTIVE = "active"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class AgentState(BaseModel):
    """Serializable state shared by routing, Agents, Memory, and Context."""

    user_id: str = Field(default="anonymous", min_length=1)
    conversation_id: str = Field(min_length=1)
    status: AgentStatus = AgentStatus.NEW
    intent: str | None = None
    intent_group: str | None = None
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    urgency: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    active_agent: str | None = None
    supporting_agents: list[str] = Field(default_factory=list)
    routing_reason: str | None = None
    needs_rag: bool = False
    needs_human: bool = False
    pending_approval: bool = False
    version: int = Field(default=1, ge=1)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
