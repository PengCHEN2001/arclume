"""Bounded in-memory tracing for the complete Agent execution path."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TraceEventType(str, Enum):
    """Events emitted while one request moves through the Agent system."""

    REQUEST_STARTED = "request_started"
    INTENT_RECOGNIZED = "intent_recognized"
    ROUTE_SELECTED = "route_selected"
    SKILLS_SELECTED = "skills_selected"
    RAG_COMPLETED = "rag_completed"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    RESPONSE_COMPOSED = "response_composed"
    MEMORY_UPDATED = "memory_updated"
    REQUEST_COMPLETED = "request_completed"
    REQUEST_FAILED = "request_failed"
    RUNTIME_STARTED = "runtime_started"
    DECISION_RECEIVED = "decision_received"
    POLICY_EVALUATED = "policy_evaluated"
    TOOL_EXECUTION_FINISHED = "tool_execution_finished"
    RUNTIME_COMPLETED = "runtime_completed"
    RUNTIME_STOPPED = "runtime_stopped"
    RUNTIME_FAILED = "runtime_failed"


class TraceEvent(BaseModel):
    """One structured event from a single request trace."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))  # Unique event ID
    event_type: TraceEventType                                  # Event category
    timestamp: datetime = Field(                                # Event creation time
        default_factory=lambda: datetime.now(timezone.utc)
    )
    request_id: str | None = None                              # Public request identifier
    conversation_id: str | None = None                         # Conversation identifier
    agent_name: str | None = None                              # Related Agent
    call_id: str | None = None                                 # Related Tool call
    tool_name: str | None = None                               # Related Tool name
    data: dict[str, Any] = Field(default_factory=dict)          # Event-specific details


class TraceRecorder:
    """Collect bounded events and retrieve them by request identifier."""

    def __init__(self, *, max_events: int = 10000) -> None:
        if max_events < 1:
            raise ValueError("Trace event limit must be at least one")
        self.max_events = max_events                    # Process-level memory bound
        self._events: list[TraceEvent] = []              # Events held in this process

    def record(
        self,
        event_type: TraceEventType,
        *,
        request_id: str | None = None,
        conversation_id: str | None = None,
        agent_name: str | None = None,
        call_id: str | None = None,
        tool_name: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Create, store, and return one trace event."""

        event = TraceEvent(  # Build one structured event for later inspection
            event_type=event_type,
            request_id=request_id,
            conversation_id=conversation_id,
            agent_name=agent_name,
            call_id=call_id,
            tool_name=tool_name,
            data=data or {},
        )
        self._events.append(event)
        if len(self._events) > self.max_events:
            del self._events[: len(self._events) - self.max_events]
        return event

    def events(self, request_id: str | None = None) -> list[TraceEvent]:
        """Return all events or only events belonging to one request."""

        if request_id is None:
            return list(self._events)
        return [event for event in self._events if event.request_id == request_id]

    def clear(self, request_id: str | None = None) -> None:
        """Remove all events or only one request's events."""

        if request_id is None:
            self._events.clear()
            return
        self._events = [event for event in self._events if event.request_id != request_id]
