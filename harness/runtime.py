"""The Harness runtime boundary and its minimal, model-independent loop."""

import inspect
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from harness.executor import ToolExecutor
from harness.policy import PolicyAction, ToolPolicy
from harness.trace import TraceEventType, TraceRecorder
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
        self.tracer.record(
            TraceEventType.DECISION_RECEIVED,
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
            call_id=call.call_id,
            tool_name=call.tool_name,
            data={
                "action": decision.action.value,
                "reason": decision.reason,
                "risk_level": decision.risk_level.value if decision.risk_level else None,
            },
        )

        if decision.action is PolicyAction.DENY:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=decision.reason,
            )

        if decision.action is PolicyAction.REQUIRE_APPROVAL:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=decision.reason,
                requires_approval=True,
            )

        result = await self.executor.execute(call, context)  # Execute after approval
        self.tracer.record(
            TraceEventType.TOOL_EXECUTION_FINISHED,
            call_id=call.call_id,
            tool_name=call.tool_name,
            data={
                "success": result.success,
                "error": result.error,
                "duration_ms": result.duration_ms,
            },
        )
        return result

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
        self.tracer.record(TraceEventType.RUNTIME_STARTED)

        for iteration in range(1, self.max_iterations + 1):
            # Ask the future Agent or model for the next action.
            try:
                decision = decision_provider(working_context)  # Text or ToolCall
                if inspect.isawaitable(decision):
                    decision = await decision

                if isinstance(decision, str):
                    self.tracer.record(
                        TraceEventType.RUNTIME_COMPLETED,
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
            data={"reason": "max_iterations", "iterations": self.max_iterations},
        )
        return RuntimeOutcome(
            status=RuntimeStatus.MAX_ITERATIONS,
            tool_results=tool_results,
            iterations=self.max_iterations,
            error="Maximum Harness iterations reached",
        )
