"""The Harness runtime boundary and its minimal, model-independent loop."""

import inspect
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from harness.executor import ToolExecutor
from harness.policy import PolicyAction, ToolPolicy
from harness.trace import TraceEvent, TraceEventType, TraceRecorder
from schemas.state import AgentState
from schemas.tool import ToolCall, ToolResult


Decision = str | ToolCall
DecisionProvider = Callable[
    [dict[str, Any]],
    Decision | Awaitable[Decision],
]


class RuntimeStatus(str, Enum):
    """Possible outcomes of the minimal Harness loop."""

    COMPLETED = "completed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    MAX_ITERATIONS = "max_iterations"
    FAILED = "failed"


class RuntimeOutcome(BaseModel):
    """Serializable result returned by a Harness run."""

    status: RuntimeStatus                                        # Final runtime state
    message: str | None = None                                   # Final Agent response
    tool_results: list[ToolResult] = Field(default_factory=list) # Tool results in this run
    iterations: int = 0                                          # Number of decision rounds
    error: str | None = None                                     # Stop or failure reason


class HarnessRuntime:
    """Connect policy, execution, tracing, and the future Agent decision loop."""

    def __init__(
        self,
        *,
        policy: ToolPolicy | None = None,
        executor: ToolExecutor | None = None,
        tracer: TraceRecorder | None = None,
        max_iterations: int = 5,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least one")

        self.policy = policy or ToolPolicy()       # Permission and risk decisions
        self.executor = executor or ToolExecutor() # Registered Tool execution
        self.tracer = tracer or TraceRecorder()    # In-memory execution events
        self.max_iterations = max_iterations       # Loop safety limit

    def record_trace(
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
        """Record a request-level event for callers outside the Harness loop."""

        return self.tracer.record(
            event_type,
            request_id=request_id,
            conversation_id=conversation_id,
            agent_name=agent_name,
            call_id=call_id,
            tool_name=tool_name,
            data=data,
        )

    def trace_events(self, request_id: str) -> list[TraceEvent]:
        """Return the retained events for one request."""

        return self.tracer.events(request_id)

    def tool_trace(self, request_id: str) -> dict[str, Any] | None:
        """Return one request trace in a tool-focused, API-friendly shape."""

        events = self.trace_events(request_id)
        if not events:
            return None
        tool_events = [
            event
            for event in events
            if event.tool_name
            and event.event_type
            in {
                TraceEventType.DECISION_RECEIVED,
                TraceEventType.POLICY_EVALUATED,
                TraceEventType.TOOL_EXECUTION_FINISHED,
            }
        ]
        return {
            "request_id": request_id,
            "events": [event.model_dump(mode="json") for event in events],
            "tool_events": [event.model_dump(mode="json") for event in tool_events],
        }

    def recent_tool_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent requests that emitted at least one Tool event."""

        safe_limit = max(1, min(int(limit), 100))
        request_ids: list[str] = []
        for event in reversed(self.tracer.events()):
            if not event.request_id or not event.tool_name:
                continue
            if event.request_id not in request_ids:
                request_ids.append(event.request_id)
            if len(request_ids) >= safe_limit:
                break
        return [
            trace
            for request_id in request_ids
            if (trace := self.tool_trace(request_id)) is not None
        ]

    async def handle_tool_call(
        self,
        call: ToolCall,
        *,
        state: AgentState | None = None,
        context: dict[str, Any] | None = None,
        allowed_tools: set[str] | None = None,
    ) -> ToolResult:
        """Check and execute one ToolCall through the Harness boundary.

        The flow is: record the request, ask Policy for a decision, stop on a
        denial or approval requirement, otherwise delegate execution and
        record the normalized result.
        """

        tool = self.executor.get(call.tool_name)  # Used by Policy evaluation
        trace_request_id, trace_conversation_id, trace_agent_name = self._trace_context(context)
        self.tracer.record(
            TraceEventType.DECISION_RECEIVED,
            request_id=trace_request_id,
            conversation_id=trace_conversation_id,
            agent_name=trace_agent_name,
            call_id=call.call_id,
            tool_name=call.tool_name,
            data={"argument_keys": sorted(call.arguments)},
        )

        decision = self.policy.evaluate(
            call,
            tool,
            state,
            allowed_tools=allowed_tools,
        )  # Allow, deny, or pause
        self.tracer.record(
            TraceEventType.POLICY_EVALUATED,
            request_id=trace_request_id,
            conversation_id=trace_conversation_id,
            agent_name=trace_agent_name,
            call_id=call.call_id,
            tool_name=call.tool_name,
            data={
                "action": decision.action.value,
                "reason": decision.reason,
                "risk_level": decision.risk_level.value if decision.risk_level else None,
            },
        )

        if decision.action is PolicyAction.DENY:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=decision.reason,
            )
            self.tracer.record(
                TraceEventType.TOOL_EXECUTION_FINISHED,
                request_id=trace_request_id,
                conversation_id=trace_conversation_id,
                agent_name=trace_agent_name,
                call_id=call.call_id,
                tool_name=call.tool_name,
                data={
                    "success": False,
                    "blocked": True,
                    "reason": decision.reason,
                    "error": decision.reason,
                    "duration_ms": None,
                    "cached": False,
                    "fallback_used": False,
                    "reranked": False,
                    "requires_approval": False,
                },
            )
            return result

        if decision.action is PolicyAction.REQUIRE_APPROVAL:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=decision.reason,
                requires_approval=True,
            )
            self.tracer.record(
                TraceEventType.TOOL_EXECUTION_FINISHED,
                request_id=trace_request_id,
                conversation_id=trace_conversation_id,
                agent_name=trace_agent_name,
                call_id=call.call_id,
                tool_name=call.tool_name,
                data={
                    "success": False,
                    "blocked": True,
                    "requires_approval": True,
                    "reason": decision.reason,
                    "error": decision.reason,
                    "duration_ms": None,
                    "cached": False,
                    "fallback_used": False,
                    "reranked": False,
                },
            )
            return result

        result = await self.executor.execute(call, context)  # Execute after approval
        self.tracer.record(
            TraceEventType.TOOL_EXECUTION_FINISHED,
            request_id=trace_request_id,
            conversation_id=trace_conversation_id,
            agent_name=trace_agent_name,
            call_id=call.call_id,
            tool_name=call.tool_name,
            data={
                "success": result.success,
                "error": result.error,
                "duration_ms": result.duration_ms,
                "cached": result.cached,
                "fallback_used": result.fallback_used,
                "reranked": result.reranked,
            },
        )
        return result

    def tool_stats(self) -> dict[str, dict[str, float | int | str]]:
        """Return Tool metrics when the configured executor provides them."""

        provider = getattr(self.executor, "stats_snapshot", None)
        if not callable(provider):
            return {}
        return provider()

    def tool_schemas(
        self,
        *,
        agent_name: str,
        allowed_tools: list[str] | set[str] | None = None,
        enabled_tools: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return OpenAI-compatible schemas for the Agent's allowed Tools."""

        scope = set(allowed_tools) if allowed_tools is not None else None
        enabled = set(enabled_tools) if enabled_tools is not None else None
        schemas: list[dict[str, Any]] = []
        for tool in self.executor.list_tools():
            if not tool.enabled:
                continue
            if scope is not None and tool.name not in scope:
                continue
            if enabled is not None and tool.name not in enabled:
                continue
            if tool.allowed_agents and agent_name not in tool.allowed_agents:
                continue
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema or {
                            "type": "object",
                            "properties": {},
                        },
                    },
                }
            )
        return schemas

    async def run(
        self,
        decision_provider: DecisionProvider,
        *,
        context: dict[str, Any] | None = None,
        state: AgentState | None = None,
    ) -> RuntimeOutcome:
        """Run the decision loop without requiring a real model call.

        The provider represents the future Agent or LLM decision step. Each
        round may return final text or a ToolCall. A ToolResult is written back
        into the working context so the next round can use it. The loop stops
        on final text, approval requirements, errors, or the iteration limit.
        """

        working_context = dict(context or {})  # Context shared between rounds
        tool_results: list[ToolResult] = []    # Results produced in this run
        request_id, conversation_id, agent_name = self._trace_context(working_context)
        self.tracer.record(
            TraceEventType.RUNTIME_STARTED,
            request_id=request_id,
            conversation_id=conversation_id,
            agent_name=agent_name,
        )

        for iteration in range(1, self.max_iterations + 1):
            # Ask the future Agent or model for the next action.
            try:
                decision = decision_provider(working_context)  # Text or ToolCall
                if inspect.isawaitable(decision):
                    decision = await decision

                if isinstance(decision, str):
                    self.tracer.record(
                        TraceEventType.RUNTIME_COMPLETED,
                        request_id=request_id,
                        conversation_id=conversation_id,
                        agent_name=agent_name,
                        data={"iterations": iteration},
                    )
                    return RuntimeOutcome(
                        status=RuntimeStatus.COMPLETED,
                        message=decision,
                        tool_results=tool_results,
                        iterations=iteration,
                    )

                if not isinstance(decision, ToolCall):
                    raise TypeError("Decision provider must return str or ToolCall")

                # Validate and execute the requested Tool through Harness.
                result = await self.handle_tool_call(
                    decision,
                    state=state,
                    context=working_context,
                )
                tool_results.append(result)  # Preserve the full run history
                working_context["tool_results"] = [
                    item.model_dump() for item in tool_results
                ]

                if result.requires_approval:
                    self.tracer.record(
                        TraceEventType.RUNTIME_STOPPED,
                        request_id=request_id,
                        conversation_id=conversation_id,
                        agent_name=agent_name,
                        call_id=decision.call_id,
                        tool_name=decision.tool_name,
                        data={"reason": "approval_required"},
                    )
                    return RuntimeOutcome(
                        status=RuntimeStatus.WAITING_FOR_APPROVAL,
                        tool_results=tool_results,
                        iterations=iteration,
                        error=result.error,
                    )

                working_context["last_tool_result"] = result.model_dump()  # Next-round input

            except Exception as exc:
                error = str(exc) or "Harness runtime failed"
                self.tracer.record(
                    TraceEventType.RUNTIME_FAILED,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    agent_name=agent_name,
                    data={"error": error, "iterations": iteration},
                )
                return RuntimeOutcome(
                    status=RuntimeStatus.FAILED,
                    tool_results=tool_results,
                    iterations=iteration,
                    error=error,
                )

        # Stop safely when the Agent keeps requesting actions without finishing.
        self.tracer.record(
            TraceEventType.RUNTIME_STOPPED,
            request_id=request_id,
            conversation_id=conversation_id,
            agent_name=agent_name,
            data={"reason": "max_iterations", "iterations": self.max_iterations},
        )
        return RuntimeOutcome(
            status=RuntimeStatus.MAX_ITERATIONS,
            tool_results=tool_results,
            iterations=self.max_iterations,
            error="Maximum Harness iterations reached",
        )

    @staticmethod
    def _trace_context(
        context: dict[str, Any] | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Read trace correlation fields from a Tool or runtime context."""

        values = context or {}
        return (
            str(values["request_id"]) if values.get("request_id") else None,
            str(values["conversation_id"]) if values.get("conversation_id") else None,
            str(values["agent_name"]) if values.get("agent_name") else None,
        )
