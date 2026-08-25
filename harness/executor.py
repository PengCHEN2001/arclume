"""Safe execution and result normalization for registered internal Tools."""

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from schemas.tool import ToolCall, ToolResult

from harness.policy import ToolRiskLevel


ToolHandler = Callable[
    [dict[str, Any], dict[str, Any] | None],
    Any | Awaitable[Any],
]


@dataclass(slots=True)
class ToolDefinition:
    """Metadata and executable handler for one internal Tool."""

    name: str                                      # Unique Tool name
    description: str                               # Tool purpose
    handler: ToolHandler                           # Actual Python function
    input_schema: dict[str, Any] = field(default_factory=dict)  # Accepted arguments
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW  # Risk level checked by Policy
    timeout_seconds: float = 10.0                  # Maximum execution time
    max_retries: int = 0                           # Extra attempts after failure
    allowed_agents: set[str] | None = None         # Optional Agent allowlist
    enabled: bool = True                           # Whether the Tool is available

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Tool name cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("Tool timeout must be greater than zero")
        if self.max_retries < 0:
            raise ValueError("Tool retries cannot be negative")


class ToolExecutor:
    """Register Tools and execute them after Harness policy approval."""

    def __init__(self, tools: list[ToolDefinition] | None = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}  # Registered Tools by name
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        """Add or replace one Tool definition by name."""

        self._tools[tool.name] = tool

    def unregister(self, tool_name: str) -> None:
        """Remove one Tool definition if it is registered."""

        self._tools.pop(tool_name, None)

    def get(self, tool_name: str) -> ToolDefinition | None:
        """Return a registered Tool definition, if present."""

        return self._tools.get(tool_name)

    def list_tools(self) -> list[ToolDefinition]:
        """Return the currently registered Tool definitions."""

        return list(self._tools.values())

    async def execute(
        self,
        call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Find, validate, execute, and normalize one ToolCall.

        The execution flow is: find the registered Tool, reject unavailable
        Tools, validate arguments, run the handler with a timeout, retry when
        configured, and return one consistent ToolResult.
        """

        tool = self.get(call.tool_name)       # Registered Tool definition
        if tool is None:
            # Unknown Tools must never be executed.
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=f"Unknown tool: {call.tool_name}",
            )

        if not tool.enabled:
            # Keep the Executor safe when it is called directly without Policy.
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=f"Tool is disabled: {call.tool_name}",
            )

        started_at = time.perf_counter()      # Used to calculate duration
        last_error = "Tool execution failed"  # Latest failure reason

        for _attempt in range(tool.max_retries + 1):
            # Validate and execute the handler. A failure may be retried.
            try:
                self._validate_arguments(tool, call.arguments)
                raw_result = await asyncio.wait_for(
                    self._run_handler(tool, call.arguments, context),
                    timeout=tool.timeout_seconds,
                )
                duration_ms = (time.perf_counter() - started_at) * 1000  # Elapsed time
                return self._normalize_result(
                    call,
                    raw_result,
                    duration_ms=duration_ms,
                )
            except asyncio.TimeoutError:
                # Timeout is contained and can trigger the configured retry.
                last_error = f"Tool timed out after {tool.timeout_seconds:.1f}s"
            except Exception as exc:  # Keep Tool failures inside the boundary.
                # Convert handler errors into a safe ToolResult.
                last_error = str(exc) or "Tool execution failed"

        # All attempts failed, so return one normalized failure result.
        duration_ms = (time.perf_counter() - started_at) * 1000
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            success=False,
            error=last_error,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _validate_arguments(
        tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> None:
        """Check required fields and basic JSON Schema value types."""

        schema = tool.input_schema                    # Tool input schema
        required = schema.get("required", [])         # Required field names
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError(f"Missing required arguments: {', '.join(missing)}")

        type_map = {  # JSON Schema types mapped to Python types
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        for name, property_schema in schema.get("properties", {}).items():
            if name not in arguments:
                continue
            expected_type = type_map.get(property_schema.get("type"))
            if expected_type is not None and not isinstance(arguments[name], expected_type):
                raise ValueError(f"Invalid type for argument: {name}")

    @staticmethod
    async def _run_handler(
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> Any:
        """Run async handlers directly and sync handlers in a worker thread."""

        if inspect.iscoroutinefunction(tool.handler):
            return await tool.handler(arguments, context)

        result = await asyncio.to_thread(tool.handler, arguments, context)  # Avoid blocking
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _normalize_result(
        call: ToolCall,
        raw_result: Any,
        *,
        duration_ms: float,
    ) -> ToolResult:
        """Convert handler output into the shared ToolResult model."""

        if isinstance(raw_result, ToolResult):
            return raw_result.model_copy(
                update={
                    "call_id": call.call_id,
                    "tool_name": call.tool_name,
                    "duration_ms": duration_ms,
                }
            )

        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            success=True,
            data=raw_result,
            duration_ms=duration_ms,
        )
