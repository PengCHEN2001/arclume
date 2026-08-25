"""The first single-Agent customer-service implementation."""

from datetime import datetime, timezone
import logging

from core.context_builder import ContextBuilder
from core.llm_utils import LLMClient
from knowledge import KnowledgeBaseError
from knowledge.knowledge_base import KnowledgeBase
from memory.conversation_memory import ConversationMemory
from memory.state_store import StateStore
from schemas.context import ContextMessage
from schemas.state import AgentState, AgentStatus


logger = logging.getLogger(__name__)


DEFAULT_SYSTEM_PROMPT = (
    "You are Arclume's customer-service assistant. "
    "Respond clearly, politely, and concisely. "
    "Use the conversation and any relevant knowledge provided in the context. "
    "Do not invent policies or facts when the available information is insufficient. "
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
        memory: ConversationMemory | None = None,
        state_store: StateStore | None = None,
        context_builder: ContextBuilder | None = None,
        knowledge_base: KnowledgeBase | None = None,
        knowledge_top_k: int = 3,
    ) -> None:
        self.llm = llm                         # Shared model transport
        self.system_prompt = system_prompt     # Stable instructions for this Agent
        self.memory = memory                   # Short-term conversation history
        self.state_store = state_store         # Persisted active-case state
        self.knowledge_base = knowledge_base     # Optional semantic knowledge retrieval
        self.knowledge_top_k = knowledge_top_k   # Number of chunks added to Context
        self.context_builder = context_builder or ContextBuilder([system_prompt])

    async def respond(
        self,
        message: str,
        *,
        user_id: str = "anonymous",
        conversation_id: str | None = None,
    ) -> str:
        """Process one turn, including Context construction and persistence.

        The flow is: validate the message, load recent history and AgentState,
        save the user message, retrieve relevant knowledge, build Context, call
        the model, save the reply, and persist the updated active-case state.
        Intent gating, query rewriting, reranking, Skills, routing, and Tool
        calls are still outside this step.
        """

        cleaned_message = message.strip()  # Remove accidental surrounding whitespace
        if not cleaned_message:
            raise ValueError("Agent message cannot be empty")

        if (self.memory or self.state_store) and not conversation_id:
            raise ValueError("conversation_id is required when persistence is enabled")

        history: list[ContextMessage] = []
        state: AgentState | None = None

        if conversation_id and self.memory:
            history = await self.memory.get_messages(user_id, conversation_id)
            await self.memory.add_message(
                user_id,
                conversation_id,
                ContextMessage(role="user", content=cleaned_message),
            )

        if conversation_id and self.state_store:
            state = await self.state_store.get_or_create(user_id, conversation_id)
            state = state.model_copy(
                update={
                    "status": AgentStatus.ACTIVE,
                    "active_agent": self.name,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            await self.state_store.save(state)

        knowledge_results = []
        if self.knowledge_base:
            try:
                knowledge_results = await self.knowledge_base.search_async(
                    cleaned_message,
                    top_k=self.knowledge_top_k,
                )
            except KnowledgeBaseError as exc:
                # Retrieval is helpful evidence, but it must not take down chat.
                logger.warning("Knowledge retrieval skipped: %s", exc)

        context = self.context_builder.build(
            cleaned_message,
            conversation_history=history,
            state=state,
            knowledge_results=knowledge_results,
        )
        history_payload = self.context_builder.render_history(context)
        llm_kwargs = {
            "system_prompt": self.context_builder.render_system_prompt(context)
        }
        if history_payload:
            llm_kwargs["history"] = history_payload

        answer = await self.llm.chat(context.user_message, **llm_kwargs)

        if conversation_id and self.memory:
            await self.memory.add_message(
                user_id,
                conversation_id,
                ContextMessage(role="assistant", content=answer),
            )

        if conversation_id and self.state_store and state:
            state = state.model_copy(
                update={
                    "version": state.version + 1,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            await self.state_store.save(state)

        return answer
