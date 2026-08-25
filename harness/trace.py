"""In-memory execution tracing for the Harness boundary."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TraceEventType(str, Enum):
    """Events emitted while one Harness run is being processed."""

    RUNTIME_STARTED = "runtime_started"
    DECISION_RECEIVED = "decision_received"
    POLICY_EVALUATED = "policy_evaluated"
    TOOL_EXECUTION_FINISHED = "tool_execution_finished"
    RUNTIME_COMPLETED = "runtime_completed"
    RUNTIME_STOPPED = "runtime_stopped"
    RUNTIME_FAILED = "runtime_failed"


class TraceEvent(BaseModel):
    """One structured event from a single in-memory execution trace."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))  # Unique event ID
    event_type: TraceEventType                               # Event category
    timestamp: datetime = Field(                             # Event creation time
        default_factory=lambda: datetime.now(timezone.utc)
    )
    call_id: str | None = None                               # Related Tool call
    tool_name: str | None = None                             # Related Tool name
    data: dict[str, Any] = Field(default_factory=dict)        # Event-specific details


class TraceRecorder:
    """Collect trace events for one runtime instance."""

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []  # Events held during this runtime

    def record(
        self,
        event_type: TraceEventType,
        *,
        call_id: str | None = None,
        tool_name: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Create, store, and return one trace event."""

        event = TraceEvent(  # Build one structured event for later inspection
            event_type=event_type,
            call_id=call_id,
            tool_name=tool_name,
            data=data or {},
        )
        self._events.append(event)
        return event

    def events(self) -> list[TraceEvent]:
        """Return a copy of the current event list."""

        return list(self._events)

    def clear(self) -> None:
        """Remove all in-memory events."""

        self._events.clear()
