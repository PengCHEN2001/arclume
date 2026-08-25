"""The first single-Agent customer-service implementation."""

from core.llm_utils import LLMClient


DEFAULT_SYSTEM_PROMPT = (
    "You are Arclume's customer-service assistant. "
    "Respond clearly, politely, and concisely. "
    "Use only information available in the conversation. "
    "If the request requires account access, a business-system operation, "
    "or human judgment, explain the limitation and recommend human support."
)


class CustomerServiceAgent:
    """Handle one customer message with one provider-agnostic LLM client."""

    name = "customer_service"

    def __init__(
        self,
        llm: LLMClient,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.llm = llm                 # Shared model transport
        self.system_prompt = system_prompt  # Stable instructions for this Agent

    async def respond(self, message: str) -> str:
        """Send one message to the model using the Agent's system instructions.

        This first Agent has no memory, retrieval, Skills, routing, or Tool
        calls. Those responsibilities will be added around this stable entry
        point in later stages.
        """

        cleaned_message = message.strip()  # Remove accidental surrounding whitespace
        if not cleaned_message:
            raise ValueError("Agent message cannot be empty")

        return await self.llm.chat(
            cleaned_message,
            system_prompt=self.system_prompt,
        )
