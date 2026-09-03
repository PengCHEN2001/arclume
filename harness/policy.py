"""Policy decisions for model-requested tool calls.

This module decides whether a registered tool call may proceed. It does not
execute tools and it does not call an LLM. Keeping authorization separate from
execution makes the boundary easy to test and change later.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from schemas.state import AgentState
from schemas.tool import ToolCall


class ToolRiskLevel(str, Enum):
    """Risk categories used by the first policy implementation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PolicyAction(str, Enum):
    """The action the Harness should take after policy evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PolicyTool(Protocol):
    """The tool attributes required by the policy layer."""

    name: str
    risk_level: ToolRiskLevel
    allowed_agents: set[str] | None
    enabled: bool


@dataclass(frozen=True, slots=True)
class PolicyResult:
    """A deterministic decision about one requested tool call."""

    action: PolicyAction                      # Action selected by Policy
    reason: str                               # Explanation for the decision
    risk_level: ToolRiskLevel | None = None  # Risk level of the requested Tool

    @property
    def allowed(self) -> bool:
        """Return whether the call can proceed without human approval."""

        return self.action is PolicyAction.ALLOW


class ToolPolicy:
    """Apply basic availability, agent, and risk rules to ToolCall objects."""

    def __init__(
        self,
        *,
        approval_required_levels: set[ToolRiskLevel] | None = None,
    ) -> None:
        self.approval_required_levels = approval_required_levels or {
            ToolRiskLevel.HIGH
        }  # Risk levels that pause execution for human approval

    def evaluate(
        self,
        call: ToolCall,
        tool: PolicyTool | None,
        state: AgentState | None = None,
        allowed_tools: set[str] | None = None,
    ) -> PolicyResult:
        """Check availability, Agent access, and risk without executing the Tool."""

        # A missing Tool can never be executed.
        if tool is None:
            return PolicyResult(
                action=PolicyAction.DENY,
                reason=f"Unknown tool: {call.tool_name}",
            )

        # Disabled Tools remain registered but cannot be used.
        if not tool.enabled:
            return PolicyResult(
                action=PolicyAction.DENY,
                reason=f"Tool is disabled: {call.tool_name}",
                risk_level=tool.risk_level,
            )

        # An Agent profile may narrow the registered Tool set for one request.
        if allowed_tools is not None and call.tool_name not in allowed_tools:
            return PolicyResult(
                action=PolicyAction.DENY,
                reason=f"Tool is outside the Agent scope: {call.tool_name}",
                risk_level=tool.risk_level,
            )

        # Restrict the Tool to its configured Agent allowlist when one exists.
        if tool.allowed_agents:
            active_agent = state.active_agent if state and state.active_agent else call.requested_by
            if active_agent not in tool.allowed_agents:
                return PolicyResult(
                    action=PolicyAction.DENY,
                    reason=f"Agent is not allowed to use tool: {call.tool_name}",
                    risk_level=tool.risk_level,
                )

        # High-risk actions stop here until a later approval flow resumes them.
        if tool.risk_level in self.approval_required_levels:
            return PolicyResult(
                action=PolicyAction.REQUIRE_APPROVAL,
                reason=f"Human approval is required for tool: {call.tool_name}",
                risk_level=tool.risk_level,
            )

        return PolicyResult(
            action=PolicyAction.ALLOW,
            reason=f"Tool call allowed: {call.tool_name}",
            risk_level=tool.risk_level,
        )
