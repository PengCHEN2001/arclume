"""Shared execution logic for Arclume's domain customer-service Agents."""

from datetime import datetime, timezone
import asyncio
import logging
from uuid import uuid4

from core.context_builder import ContextBuilder
from core.llm_utils import LLMClient
from core.skill_loader import SkillError, SkillLoader
from harness.runtime import HarnessRuntime
from knowledge import KnowledgeBaseError
from knowledge.knowledge_base import KnowledgeBase
from memory.conversation_memory import ConversationMemory
from memory.state_store import StateStore
from schemas.context import ContextMessage
from schemas.state import AgentState, AgentStatus
from schemas.tool import ToolCall


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
    system_prompt = DEFAULT_SYSTEM_PROMPT

    def __init__(
        self,
        llm: LLMClient,
        system_prompt: str | None = None,
        memory: ConversationMemory | None = None,
        state_store: StateStore | None = None,
        context_builder: ContextBuilder | None = None,
        knowledge_base: KnowledgeBase | None = None,
        knowledge_top_k: int = 3,
        skill_loader: SkillLoader | None = None,
        default_skill_names: list[str] | None = None,
        harness: HarnessRuntime | None = None,
    ) -> None:
        self.llm = llm                         # Shared model transport
        self.system_prompt = system_prompt or getattr(
            self, "system_prompt", DEFAULT_SYSTEM_PROMPT
        )                                       # Stable instructions for this Agent
        self.memory = memory                   # Short-term conversation history
        self.state_store = state_store         # Persisted active-case state
        self.knowledge_base = knowledge_base     # Optional semantic knowledge retrieval
        self.knowledge_top_k = knowledge_top_k   # Number of chunks added to Context
        self.skill_loader = skill_loader         # Read-only static Skill loader
        self.default_skill_names = list(default_skill_names or [])  # Optional manual Skills
        self.harness = harness                     # Tool policy and execution boundary
        self.context_builder = context_builder or ContextBuilder([self.system_prompt])

    async def respond(
        self,
        message: str,
        *,
        user_id: str = "anonymous",
        conversation_id: str | None = None,
        skill_names: list[str] | None = None,
        knowledge_enabled: bool = True,
        intent: str | None = None,
        intent_group: str | None = None,
        intent_confidence: float = 0.0,
        urgency: str | None = None,
        entities: dict[str, object] | None = None,
        supporting_agents: list[str] | None = None,
        routing_reason: str | None = None,
        persist: bool = True,
    ) -> str:
        """Process one turn, including Context construction and persistence.

        The flow is: validate the message, load recent history and AgentState,
        save the user message, retrieve relevant knowledge, build Context, call
        the model, save the reply, and persist the updated active-case state.
        The Orchestrator supplies intent and routing metadata. ``persist=False``
        is used for supporting Agents so parallel collaboration does not write
        duplicate messages into the shared conversation history.
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
            if persist:
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
                    "intent": intent,
                    "intent_group": intent_group,
                    "intent_confidence": intent_confidence,
                    "urgency": urgency,
                    "entities": dict(entities or {}),
                    "supporting_agents": list(supporting_agents or []),
                    "routing_reason": routing_reason,
                    "needs_rag": knowledge_enabled,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            if persist:
                await self.state_store.save(state)

        knowledge_results = []
        if self.knowledge_base and knowledge_enabled:
            try:
                if self.harness:
                    # Even low-risk retrieval uses the same Tool boundary in the API flow.
                    tool_result = await self.harness.handle_tool_call(
                        ToolCall(
                            call_id=str(uuid4()),
                            tool_name="knowledge_search",
                            arguments={
                                "query": cleaned_message,
                                "top_k": self.knowledge_top_k,
                            },
                            requested_by=self.name,
                        ),
                        state=state,
                        context={"knowledge_base": self.knowledge_base},
                    )
                    if tool_result.success and isinstance(tool_result.data, list):
                        knowledge_results = tool_result.data
                    elif tool_result.error:
                        logger.warning("Knowledge retrieval skipped: %s", tool_result.error)
                else:
                    # Keep direct use available for small unit tests without a Harness.
                    knowledge_results = await self.knowledge_base.search_async(
                        cleaned_message,
                        top_k=self.knowledge_top_k,
                    )
            except KnowledgeBaseError as exc:
                # Retrieval is helpful evidence, but it must not take down chat.
                logger.warning("Knowledge retrieval skipped: %s", exc)

        selected_skill_names = (
            list(skill_names) if skill_names is not None else self.default_skill_names
        )
        skill_instructions: list[str] = []
        if selected_skill_names and self.skill_loader:
            try:
                skill_documents = await asyncio.to_thread(
                    self.skill_loader.load_many,
                    selected_skill_names,
                )
                skill_instructions = [
                    f"[Skill: {document.name}]\n{document.content}"
                    for document in skill_documents
                ]
            except SkillError as exc:
                # A missing optional Skill should not break the base assistant.
                logger.warning("Skill loading skipped: %s", exc)

        context = self.context_builder.build(
            cleaned_message,
            conversation_history=history,
            state=state,
            knowledge_results=knowledge_results,
            skill_instructions=skill_instructions,
            metadata={
                "intent": intent,
                "intent_group": intent_group,
                "intent_confidence": intent_confidence,
                "urgency": urgency,
                "entities": dict(entities or {}),
                "active_agent": self.name,
                "supporting_agents": list(supporting_agents or []),
                "routing_reason": routing_reason,
                "rag_enabled": knowledge_enabled,
            },
        )
        history_payload = self.context_builder.render_history(context)
        llm_kwargs = {
            "system_prompt": self.context_builder.render_system_prompt(context)
        }
        if history_payload:
            llm_kwargs["history"] = history_payload

        answer = await self.llm.chat(context.user_message, **llm_kwargs)

        if persist and conversation_id and self.memory:
            await self.memory.add_message(
                user_id,
                conversation_id,
                ContextMessage(role="assistant", content=answer),
            )

        if persist and conversation_id and self.state_store and state:
            needs_human = (
                urgency in {"high", "critical"}
                or intent in {"escalation", "human_handoff"}
            )
            state = state.model_copy(
                update={
                    "version": state.version + 1,
                    "status": AgentStatus.ESCALATED if needs_human else AgentStatus.ACTIVE,
                    "needs_human": needs_human,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            await self.state_store.save(state)

        return answer
