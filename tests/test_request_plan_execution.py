"""Planned evidence reads happen before the Agent asks the model to answer."""

import unittest
from types import SimpleNamespace

from agents.billing_agent import BillingAgent
from agents.general_agent import GeneralAgent
from core.skill_loader import SkillLoader
from harness.executor import ToolExecutor
from harness.runtime import HarnessRuntime
from schemas.context import ContextMessage
from tools.tool_functions import register_tools


class RecordingLLM:
    def __init__(self) -> None:
        self.histories: list[list[dict[str, str]]] = []
        self.system_prompts: list[str] = []

    async def chat(self, message, **kwargs):
        self.histories.append(kwargs.get("history", []))
        self.system_prompts.append(kwargs.get("system_prompt", ""))
        return "A cautious answer."


class FakeKnowledgeBase:
    def __init__(self, *, empty=False) -> None:
        self.queries: list[str] = []
        self.empty = empty

    async def search_async(self, query, top_k=3):
        self.queries.append(query)
        return [] if self.empty else [
            {"content": "Refunds are processed after review.", "source": "policy.md"}
        ]


class ToolCapableLLM:
    def __init__(self) -> None:
        self.messages = []

    async def chat_with_tools(self, messages, tool_schemas, **kwargs):
        self.messages = messages
        return SimpleNamespace(content="A cautious answer.", tool_calls=[])


class RequestPlanExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_intent_selected_skill_is_injected_without_keyword_repeat(self):
        llm = RecordingLLM()
        agent = BillingAgent(llm=llm, skill_loader=SkillLoader("skills"))

        await agent.respond(
            "I need my money back.",
            knowledge_enabled=False,
            intent="refund",
            skill_names=["refund"],
        )

        self.assertTrue(any(
            "Handle refund-related customer questions" in item["content"]
            for item in llm.histories[0]
        ))

    async def test_required_knowledge_is_fetched_before_model_answer(self):
        llm = RecordingLLM()
        knowledge = FakeKnowledgeBase()
        harness = HarnessRuntime(executor=register_tools(ToolExecutor()))
        agent = BillingAgent(llm=llm, knowledge_base=knowledge, harness=harness)

        await agent.respond(
            "What is your refund policy?",
            knowledge_enabled=True,
            information_need="knowledge",
            intent="refund",
        )

        self.assertEqual(knowledge.queries, ["What is your refund policy?"])
        self.assertIn("knowledge_search", agent.last_tools_used)
        self.assertTrue(any(
            "Refunds are processed after review." in item["content"]
            for item in llm.histories[0]
        ))

    async def test_tool_capable_model_also_receives_prefetched_knowledge(self):
        llm = ToolCapableLLM()
        knowledge = FakeKnowledgeBase()
        harness = HarnessRuntime(executor=register_tools(ToolExecutor()))
        agent = BillingAgent(llm=llm, knowledge_base=knowledge, harness=harness)

        await agent.respond(
            "What is your refund policy?",
            knowledge_enabled=True,
            information_need="knowledge",
            intent="refund",
        )

        self.assertEqual(len(knowledge.queries), 1)
        self.assertTrue(any(
            "Refunds are processed after review." in str(item.get("content"))
            for item in llm.messages
        ))

    async def test_planned_order_lookup_uses_harness_and_marks_mock_data(self):
        llm = RecordingLLM()
        harness = HarnessRuntime(executor=register_tools(ToolExecutor()))
        agent = GeneralAgent(llm=llm, harness=harness)

        await agent.respond(
            "Where is my order #AB1234?",
            knowledge_enabled=False,
            information_need="live_data",
            planned_tool_name="order_query",
            intent="order_status",
            entities={"order_id": ["AB1234"]},
        )

        self.assertIn("order_query", agent.last_tools_used)
        self.assertTrue(any(
            "Mock order data" in item["content"]
            for item in llm.histories[0]
        ))
        self.assertFalse(any(
            "[Relevant knowledge]" in item["content"]
            for item in llm.histories[0]
        ))

    async def test_empty_required_retrieval_is_explicitly_marked_unverified(self):
        llm = RecordingLLM()
        knowledge = FakeKnowledgeBase(empty=True)
        harness = HarnessRuntime(executor=register_tools(ToolExecutor()))
        agent = BillingAgent(llm=llm, knowledge_base=knowledge, harness=harness)

        await agent.respond(
            "What is your refund policy?",
            knowledge_enabled=True,
            information_need="knowledge",
            intent="refund",
        )

        self.assertEqual(len(knowledge.queries), 1)
        self.assertIn("knowledge_search", agent.last_tools_used)
        self.assertTrue(any(
            "no_verified_results" in item["content"]
            for item in llm.histories[0]
        ))

    async def test_delegated_subtask_prompt_limits_history_scope(self):
        llm = RecordingLLM()
        agent = BillingAgent(llm=llm)
        await agent.respond(
            "How can I get a refund?",
            knowledge_enabled=False,
            intent="refund",
            task_scoped=True,
            memory_context={
                "recent_messages": [
                    ContextMessage(
                        role="assistant",
                        content="Shipping takes one day. The Mini lamp has touch controls.",
                    ),
                ],
            },
        )

        self.assertIn("Answer only that subtask", llm.system_prompts[0])

    async def test_action_plan_does_not_auto_execute_a_write_tool(self):
        llm = RecordingLLM()
        harness = HarnessRuntime(executor=register_tools(ToolExecutor()))
        agent = BillingAgent(llm=llm, harness=harness)

        await agent.respond(
            "Please issue my refund",
            knowledge_enabled=False,
            information_need="action",
            intent="refund",
        )

        self.assertFalse(agent.last_tools_used)


if __name__ == "__main__":
    unittest.main()
