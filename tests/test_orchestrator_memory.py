"""The stored assistant turn must match the final client-visible answer."""

import unittest

from agents.agent_orchestrator import AgentOrchestrator, AgentType
from agents.customer_service_agent import CustomerServiceAgent
from core.intent_recognizer import IntentCategory, IntentRecognizer, IntentResult


class RecordingMemory:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.profiles: list[dict[str, object]] = []

    async def add_message(self, user_id, conversation_id, message, *, compact=True):
        self.messages.append((message.role, message.content))

    async def update_profile(self, user_id, conversation_id, *, message, entities):
        self.profiles.append({"message": message, "entities": entities})


class StubAgent:
    def __init__(self, memory: RecordingMemory, answer: str, *, fail=False) -> None:
        self.memory = memory
        self.answer = answer
        self.fail = fail
        self.harness = None
        self.last_tools_used = []
        self.last_tool_traces = []
        self.last_escalated = False
        self.last_escalation_reason = None
        self.last_escalation_source = None
        self.calls: list[dict[str, object]] = []

    async def respond(self, message, **kwargs):
        self.calls.append({"message": message, **kwargs})
        if self.fail:
            raise RuntimeError("agent failed")
        return self.answer


class StubRecognizer:
    def __init__(self, result: IntentResult) -> None:
        self.result = result

    async def recognize(self, message, *, history=None):
        return self.result


class StubLLM:
    async def chat(self, message, **kwargs):
        return "Direct answer"


def intent(category, *, technical=0.0, billing=0.0, confidence=0.9):
    return IntentResult(
        intent=category,
        intent_group="support",
        confidence=confidence,
        domain_scores={"technical": technical, "billing": billing, "general": 0.1},
    )


class OrchestratorMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_skill_candidates_follow_fine_grained_intent(self):
        self.assertEqual(
            AgentOrchestrator._skills_for(AgentType.BILLING, IntentCategory.REFUND),
            ["refund"],
        )
        self.assertEqual(
            AgentOrchestrator._skills_for(AgentType.BILLING, IntentCategory.PAYMENT_ISSUE),
            ["refund"],
        )
        self.assertEqual(
            AgentOrchestrator._skills_for(AgentType.BILLING, IntentCategory.INVOICE),
            [],
        )
        self.assertEqual(
            AgentOrchestrator._skills_for(AgentType.BILLING, IntentCategory.BILLING),
            [],
        )

    async def run_case(self, analysis, *, fail_technical=False, message="Please help with this request"):
        memory = RecordingMemory()
        general = StubAgent(memory, "General answer")
        technical = StubAgent(memory, "Technical answer", fail=fail_technical)
        billing = StubAgent(memory, "Billing answer")
        orchestrator = AgentOrchestrator(
            general_agent=general,
            technical_agent=technical,
            billing_agent=billing,
            escalation_agent=StubAgent(memory, "Handoff answer"),
            intent_recognizer=StubRecognizer(analysis),
        )
        result = await orchestrator.run(
            message,
            user_id="user-1",
            conversation_id="conversation-1",
        )
        self.assertEqual(
            memory.messages,
            [("user", message), ("assistant", result.response)],
        )
        self.assertEqual(len(memory.profiles), 1)
        return result, general, technical, billing

    async def test_parallel_stores_composed_answer_once(self):
        result, _, technical, billing = await self.run_case(
            intent(IntentCategory.TECHNICAL, technical=0.8, billing=0.7)
        )
        self.assertIn("Technical answer", result.response)
        self.assertIn("Billing answer", result.response)
        self.assertFalse(technical.calls[0]["persist_conversation"])
        self.assertFalse(billing.calls[0]["persist_conversation"])

    async def test_single_agent_stores_answer_once(self):
        result, _, technical, _ = await self.run_case(
            intent(IntentCategory.TECHNICAL, technical=0.8)
        )
        self.assertEqual(result.response, "Technical answer")
        self.assertTrue(technical.calls[0]["persist"])

    async def test_fallback_stores_actual_general_answer(self):
        result, general, _, _ = await self.run_case(
            intent(IntentCategory.TECHNICAL, technical=0.8), fail_technical=True
        )
        self.assertEqual(result.response, "General answer")
        self.assertTrue(general.calls[0]["persist"])

    async def test_clarification_stores_visible_prompt(self):
        result, general, _, _ = await self.run_case(
            intent(IntentCategory.OTHER, confidence=0.1)
        )
        self.assertIn("Please clarify", result.response)
        self.assertFalse(general.calls)

    async def test_refund_policy_routes_to_billing_with_required_knowledge(self):
        message = "What is your refund policy?"
        analysis = await IntentRecognizer().recognize(message)
        result, general, _, billing = await self.run_case(analysis, message=message)
        self.assertEqual(result.primary_agent.value, "billing")
        self.assertFalse(general.calls)
        self.assertTrue(billing.calls[0]["knowledge_enabled"])
        self.assertEqual(billing.calls[0]["information_need"], "knowledge")

    async def test_two_clear_domains_keep_supporting_agent(self):
        message = "I cannot log in and I was charged twice."
        analysis = await IntentRecognizer().recognize(message)
        result, _, technical, billing = await self.run_case(analysis, message=message)
        self.assertEqual({result.primary_agent.value, *(agent.value for agent in result.supporting_agents)},
                         {"technical", "billing"})
        self.assertTrue(technical.calls)
        self.assertTrue(billing.calls)
        self.assertEqual(technical.calls[0]["message"], "I cannot log in")
        self.assertEqual(billing.calls[0]["message"], "I was charged twice.")

    async def test_three_questions_delegate_only_relevant_text_to_each_agent(self):
        message = (
            "how long does it take for the shipping? and can u introduce the mini desk lamp? "
            "and how can i get the refund?"
        )
        analysis = await IntentRecognizer().recognize(message)

        result, general, _, billing = await self.run_case(analysis, message=message)

        self.assertEqual(result.primary_agent.value, "general")
        self.assertEqual([agent.value for agent in result.supporting_agents], ["billing"])
        self.assertIn("shipping", general.calls[0]["message"])
        self.assertIn("mini desk lamp", general.calls[0]["message"])
        self.assertNotIn("refund", general.calls[0]["message"])
        self.assertEqual(billing.calls[0]["message"], "how can i get the refund?")
        self.assertTrue(general.calls[0]["knowledge_enabled"])
        self.assertTrue(billing.calls[0]["knowledge_enabled"])

    async def test_direct_agent_keeps_original_persistence_behavior(self):
        memory = RecordingMemory()
        agent = CustomerServiceAgent(llm=StubLLM(), memory=memory)
        answer = await agent.respond(
            "A direct question",
            conversation_id="conversation-1",
            memory_context={"recent_messages": []},
            knowledge_enabled=False,
        )
        self.assertEqual(memory.messages, [("user", "A direct question"), ("assistant", answer)])

    async def test_agent_can_defer_conversation_without_losing_answer(self):
        memory = RecordingMemory()
        agent = CustomerServiceAgent(llm=StubLLM(), memory=memory)
        answer = await agent.respond(
            "A delegated question",
            conversation_id="conversation-1",
            memory_context={"recent_messages": []},
            knowledge_enabled=False,
            persist_conversation=False,
        )
        self.assertEqual(answer, "Direct answer")
        self.assertFalse(memory.messages)
        self.assertFalse(memory.profiles)


if __name__ == "__main__":
    unittest.main()
