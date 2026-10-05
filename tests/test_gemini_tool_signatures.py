"""Gemini 3 Tool-call compatibility tests.

Gemini's OpenAI-compatible endpoint validates the provider-specific
``extra_content.google.thought_signature`` when a Tool result is sent back.
These tests ensure the generic client keeps that optional data without making
other OpenAI-compatible providers depend on it.
"""

import unittest

from agents.general_agent import GeneralAgent
from core.llm_utils import LLMClient, LLMSettings, LLMToolCall, LLMToolResponse
from harness.executor import ToolExecutor
from harness.runtime import HarnessRuntime
from tools.tool_functions import register_tools


class StaticResponseLLMClient(LLMClient):
    """Avoid network access while testing OpenAI-compatible response parsing."""

    def __init__(self, response):
        super().__init__(
            LLMSettings(
                provider="test",
                api_key="test-key",
                base_url="https://example.test/v1",
                model="test-model",
                timeout_seconds=1,
            )
        )
        self.response = response

    async def _post_completion(self, payload, headers):
        return self.response


class SignatureAwareLLM:
    """Mimic a Gemini Tool call followed by a final answer."""

    def __init__(self) -> None:
        self.requests: list[list[dict[str, object]]] = []

    async def chat_with_tools(self, messages, tool_schemas, **kwargs):
        self.requests.append(messages)
        if len(self.requests) == 1:
            return LLMToolResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        call_id="call-1",
                        name="suggest_required_fields",
                        arguments={},
                        extra_content={
                            "google": {"thought_signature": "signature-from-gemini"}
                        },
                    )
                ],
            )

        returned_call = messages[-2]["tool_calls"][0]
        assert returned_call["extra_content"] == {
            "google": {"thought_signature": "signature-from-gemini"}
        }
        return LLMToolResponse(content="Here is what I need from you.", tool_calls=[])


class GeminiToolSignatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_preserves_gemini_extra_content_when_parsing(self):
        client = StaticResponseLLMClient(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "extra_content": {
                                        "google": {
                                            "thought_signature": "signature-from-gemini"
                                        }
                                    },
                                    "function": {
                                        "name": "suggest_required_fields",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
        try:
            response = await client.chat_with_tools(
                messages=[{"role": "user", "content": "Help me with a refund."}],
                tools=[],
            )
        finally:
            await client.close()

        self.assertEqual(
            response.tool_calls[0].extra_content,
            {"google": {"thought_signature": "signature-from-gemini"}},
        )

    async def test_tool_loop_returns_provider_extra_content_to_next_model_call(self):
        llm = SignatureAwareLLM()
        harness = HarnessRuntime(executor=register_tools(ToolExecutor()))
        agent = GeneralAgent(llm=llm, harness=harness)

        response = await agent.respond(
            "What information do you need?",
            knowledge_enabled=False,
            intent="other",
        )

        self.assertEqual(response, "Here is what I need from you.")
        self.assertEqual(len(llm.requests), 2)
        self.assertIn("suggest_required_fields", agent.last_tools_used)


if __name__ == "__main__":
    unittest.main()
