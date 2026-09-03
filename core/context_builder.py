"""Build the temporary Context used by one model request."""

import json
from typing import Any, Iterable

from schemas.context import Context, ContextMessage
from schemas.state import AgentState
from schemas.tool import ToolResult


class ContextBuilder:
    """Combine request materials without performing I/O or compression."""

    def __init__(self, system_instructions: Iterable[str] | None = None) -> None:
        self.system_instructions = [
            instruction.strip()
            for instruction in (system_instructions or [])
            if instruction.strip()
        ]  # Stable instructions applied to every Context

    def build(
        self,
        user_message: str,
        *,
        conversation_history: list[ContextMessage] | None = None,
        state: AgentState | None = None,
        knowledge_results: list[dict[str, Any]] | None = None,
        skill_instructions: list[str] | None = None,
        tool_results: list[ToolResult] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Context:
        """Create one Context from already-loaded request materials.

        This first version only normalizes and combines data. It does not
        limit message length, count tokens, summarize history, or retrieve
        additional information.
        """

        cleaned_message = user_message.strip()  # Current user request
        if not cleaned_message:
            raise ValueError("Context user_message cannot be empty")

        return Context(
            user_message=cleaned_message,
            conversation_history=list(conversation_history or []),
            state=state,
            system_instructions=list(self.system_instructions),
            knowledge_results=list(knowledge_results or []),
            skill_instructions=[
                instruction.strip()
                for instruction in (skill_instructions or [])
                if instruction.strip()
            ],
            tool_results=list(tool_results or []),
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def render_system_prompt(context: Context) -> str | None:
        """Render stable system instructions for the LLMClient."""

        if not context.system_instructions:
            return None
        return "\n\n".join(context.system_instructions)

    @staticmethod
    def render_history(context: Context) -> list[dict[str, str]]:
        """Render state, optional evidence, and prior messages before the user turn.

        The current user message is intentionally not included here because
        LLMClient appends it after this history. This keeps the current request
        at the end of the model input while preserving the preceding context.
        """

        messages: list[dict[str, str]] = []

        if context.state is not None:
            messages.append(
                {
                    "role": "system",
                    "content": "[Current case state]\n" + ContextBuilder._json_text(
                        context.state.model_dump(mode="json")
                    ),
                }
            )

        if context.metadata:
            request_analysis = {
                key: value
                for key, value in context.metadata.items()
                if value is not None and value != "" and value != [] and value != {}
            }
            if request_analysis:
                messages.append(
                    {
                        "role": "system",
                        "content": "[Request analysis]\n"
                        + ContextBuilder._json_text(request_analysis),
                    }
                )

        if context.skill_instructions:
            messages.append(
                {
                    "role": "system",
                    "content": "[Active instructions]\n"
                    + "\n".join(context.skill_instructions),
                }
            )

        if context.knowledge_results:
            messages.append(
                {
                    "role": "system",
                    "content": "[Relevant knowledge]\n"
                    + ContextBuilder._json_text(context.knowledge_results),
                }
            )

        messages.extend(
            {
                "role": message.role,
                "content": message.content,
            }
            for message in context.conversation_history
        )

        messages.extend(
            {
                "role": "tool",
                "content": ContextBuilder._json_text(result.model_dump(mode="json")),
            }
            for result in context.tool_results
        )
        return messages

    @staticmethod
    def _json_text(value: Any) -> str:
        """Serialize structured context without losing non-ASCII text."""

        return json.dumps(value, ensure_ascii=False, default=str)
