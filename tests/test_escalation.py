"""Tests for explicit Agent escalation signals and complete Tool traces."""

import unittest

from agents.customer_service_agent import CustomerServiceAgent
from schemas.tool import ToolResult


class AgentEscalationTests(unittest.TestCase):
    """Verify the lightweight escalation protocol without an LLM call."""

    def setUp(self) -> None:
        self.agent = CustomerServiceAgent.__new__(CustomerServiceAgent)
        self.agent._last_escalated = False
        self.agent._last_escalation_reason = None
        self.agent._last_escalation_source = None
        self.agent._last_tools_used = []
        self.agent._last_tool_traces = []

    def test_model_marker_becomes_structured_output(self) -> None:
        answer = self.agent._parse_escalation_marker(
            "[ESCALATE] Account verification is required.\nPlease contact support."
        )

        self.assertEqual(answer, "Please contact support.")
        self.assertTrue(self.agent.last_escalated)
        self.assertEqual(self.agent.last_escalation_source, "agent_decision")
        self.assertEqual(
            self.agent.last_escalation_reason,
            "Account verification is required.",
        )

    def test_tool_trace_keeps_governance_fields(self) -> None:
        self.agent._record_tool_result(
            tool_name="order_query",
            call_id="call-1",
            result=ToolResult(
                call_id="call-1",
                tool_name="order_query",
                success=True,
                duration_ms=12.5,
                cached=True,
                fallback_used=False,
                reranked=True,
            ),
        )

        self.assertEqual(self.agent.last_tools_used, ["order_query"])
        self.assertEqual(
            self.agent.last_tool_traces[0],
            {
                "agent_name": "customer_service",
                "tool_name": "order_query",
                "call_id": "call-1",
                "success": True,
                "error": None,
                "duration_ms": 12.5,
                "cached": True,
                "fallback_used": False,
                "reranked": True,
                "requires_approval": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
