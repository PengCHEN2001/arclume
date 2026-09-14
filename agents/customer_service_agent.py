"""Shared execution logic for Arclume's domain customer-service Agents."""

from datetime import datetime, timezone
import asyncio
import json
import logging
import re
from uuid import uuid4

from core.context_builder import ContextBuilder
from agents.agent_profile import AgentProfile
from core.llm_utils import LLMClient
from core.skill_loader import SkillError, SkillLoader
from harness.runtime import HarnessRuntime
from harness.trace import TraceEventType
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
    "or human judgment, explain the limitation and recommend human support. "
    "If human support is required, start the final answer with "
    "'[ESCALATE]' followed by a short reason. Do not use this marker for ordinary requests."
)


_ESCALATION_MARKER = re.compile(
    r"^\s*\[ESCALATE\]\s*(?P<reason>[^\n]*)",
    re.IGNORECASE,
)


DEFAULT_AGENT_PROFILE = AgentProfile(
    role="Customer support assistant",
    mission="Resolve the current support request using verified context and safe next steps.",
    workflow=["understand the request", "use available evidence", "answer or escalate"],
    input_contract=["user message", "conversation history", "case state", "knowledge context"],
    output_contract=["direct answer", "necessary missing information", "safe next step"],
    handoff_conditions=["human judgment or an unavailable business operation is required"],
    tool_scope=["knowledge_search"],
    temperature=0.2,
    max_tokens=1024,
)


class CustomerServiceAgent:
    """Handle one customer message with one provider-agnostic LLM client."""

    name = "customer_service"
    system_prompt = DEFAULT_SYSTEM_PROMPT
    profile = DEFAULT_AGENT_PROFILE

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
        profile: AgentProfile | None = None,
        enable_tool_loop: bool = True,
        max_tool_iterations: int = 3,
    ) -> None:
        if max_tool_iterations < 1:
            raise ValueError("max_tool_iterations must be at least one")
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
        self.profile = profile or getattr(type(self), "profile", DEFAULT_AGENT_PROFILE)
        self.enable_tool_loop = enable_tool_loop       # Whether model Tool use is enabled
        self.max_tool_iterations = max_tool_iterations # Safety limit for one Agent turn
        self._last_tools_used: list[str] = []          # Tools used in the latest turn
        self._last_tool_traces: list[dict[str, object]] = [] # Latest Tool call details
        self._last_escalated = False                   # Agent's explicit escalation signal
        self._last_escalation_reason: str | None = None # Why human support is needed
        self._last_escalation_source: str | None = None # intent, policy, tool_failure, or agent_decision
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
        request_id: str | None = None,
        memory_context: dict[str, object] | None = None,
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

        self._last_tools_used = []
        self._last_tool_traces = []
        self._last_escalated = False
        self._last_escalation_reason = None
        self._last_escalation_source = None

        if (self.memory or self.state_store) and not conversation_id:
            raise ValueError("conversation_id is required when persistence is enabled")

        history: list[ContextMessage] = []
        loaded_memory: dict[str, object] = dict(memory_context or {})
        state: AgentState | None = None

        if conversation_id and self.memory:
            if not loaded_memory:
                loaded_memory = await self.memory.get_context(
                    user_id,
                    conversation_id,
                    query=cleaned_message,
                )
            history = list(loaded_memory.get("recent_messages") or [])
            if persist:
                await self.memory.add_message(
                    user_id,
                    conversation_id,
                    ContextMessage(role="user", content=cleaned_message),
                    compact=False,
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

        tool_schemas = self._tool_schemas(knowledge_enabled)
        active_tool_scope = {
            str(item["function"]["name"])
            for item in tool_schemas
            if isinstance(item.get("function"), dict)
            and item["function"].get("name")
        }
        tool_loop_active = bool(
            tool_schemas
            and self.enable_tool_loop
            and callable(getattr(self.llm, "chat_with_tools", None))
        )

        knowledge_results = []
        if self.knowledge_base and knowledge_enabled and not tool_loop_active:
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
                        context=self._tool_context(
                            state=state,
                            conversation_id=conversation_id,
                            intent=intent,
                            entities=entities,
                            request_id=request_id,
                        ),
                        allowed_tools=active_tool_scope,
                    )
                    self._record_tool_result(
                        tool_name="knowledge_search",
                        call_id="knowledge_search",
                        result=tool_result,
                    )
                    if tool_result.success and isinstance(tool_result.data, list):
                        knowledge_results = tool_result.data
                    elif tool_result.success and isinstance(tool_result.data, dict):
                        knowledge_results = list(tool_result.data.get("results") or [])
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

        self._record_trace(
            TraceEventType.RAG_COMPLETED,
            request_id=request_id,
            conversation_id=conversation_id,
            data={
                "enabled": knowledge_enabled,
                "tool_loop_active": tool_loop_active,
                "result_count": len(knowledge_results),
            },
        )

        selected_skill_names = (
            list(skill_names) if skill_names is not None else self.default_skill_names
        )
        skill_instructions: list[str] = []
        selected_skill_documents = []
        if self.skill_loader:
            try:
                selected_skill_documents = await asyncio.to_thread(
                    self.skill_loader.select_for_agent,
                    self.name,
                    cleaned_message,
                    selected_skill_names,
                )
                skill_prompt = self.skill_loader.render(selected_skill_documents)
                if skill_prompt:
                    skill_instructions = [skill_prompt]
            except SkillError as exc:
                # A missing optional Skill should not break the base assistant.
                logger.warning("Skill loading skipped: %s", exc)
        self._record_trace(
            TraceEventType.SKILLS_SELECTED,
            request_id=request_id,
            conversation_id=conversation_id,
            data={
                "skills": [document.name for document in selected_skill_documents],
                "requested": selected_skill_names,
            },
        )

        context = self.context_builder.build(
            cleaned_message,
            conversation_history=history,
            memory_summary=self._memory_text(loaded_memory.get("summary")),
            episodic_memories=self._memory_records(
                loaded_memory.get("episodic_memories")
            ),
            user_profile=self._memory_profile(loaded_memory.get("user_profile")),
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
                "request_id": request_id,
            },
        )
        history_payload = self.context_builder.render_history(context)
        system_prompt = self.context_builder.render_system_prompt(context)
        profile_prompt = self._profile_prompt()
        if profile_prompt:
            system_prompt = f"{system_prompt}\n\n{profile_prompt}" if system_prompt else profile_prompt
        if tool_loop_active:
            answer = await self._run_tool_loop(
                user_message=context.user_message,
                history_payload=history_payload,
                system_prompt=system_prompt,
                tool_schemas=tool_schemas,
                allowed_tools=active_tool_scope,
                state=state,
                intent=intent,
                entities=entities,
                request_id=request_id,
                conversation_id=conversation_id,
            )
        else:
            llm_kwargs = {"system_prompt": system_prompt}
            if history_payload:
                llm_kwargs["history"] = history_payload
            answer = await self.llm.chat(context.user_message, **llm_kwargs)

        # Convert the model's small protocol marker into structured Agent output.
        answer = self._parse_escalation_marker(answer)

        if persist and conversation_id and self.memory:
            await self.memory.add_message(
                user_id,
                conversation_id,
                ContextMessage(role="assistant", content=answer),
            )
            await self.memory.update_profile(
                user_id,
                conversation_id,
                message=cleaned_message,
                entities=entities,
            )

        if persist and conversation_id and self.state_store and state:
            needs_human = (
                self._last_escalated
                or urgency in {"high", "critical"}
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

        self._record_trace(
            TraceEventType.MEMORY_UPDATED,
            request_id=request_id,
            conversation_id=conversation_id,
            data={
                "conversation_persisted": bool(persist and conversation_id and self.memory),
                "state_persisted": bool(persist and conversation_id and self.state_store),
            },
        )

        return answer

    def _tool_schemas(self, knowledge_enabled: bool) -> list[dict[str, object]]:
        """Build the model-visible Tool list from the Agent profile scope."""

        if not self.harness:
            return []
        enabled_tools = set(self.profile.tool_scope)
        if not knowledge_enabled:
            enabled_tools.discard("knowledge_search")
        return self.harness.tool_schemas(
            agent_name=self.name,
            allowed_tools=self.profile.tool_scope,
            enabled_tools=enabled_tools,
        )

    def _profile_prompt(self) -> str:
        """Render the AgentProfile as concise model instructions."""

        return (
            "[Agent profile]\n"
            f"Role: {self.profile.role}\n"
            f"Mission: {self.profile.mission}\n"
            f"Workflow: {' -> '.join(self.profile.workflow)}\n"
            f"Input contract: {', '.join(self.profile.input_contract)}\n"
            f"Output contract: {', '.join(self.profile.output_contract)}\n"
            f"Handoff conditions: {', '.join(self.profile.handoff_conditions) or 'none'}\n"
            f"Allowed Tools: {', '.join(self.profile.tool_scope) or 'none'}\n"
            "Do not claim that an unavailable query, refund, account change, or ticket action was completed."
        )

    @staticmethod
    def _memory_text(value: object) -> str | None:
        """Accept only a non-empty string as a conversation summary."""

        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _memory_records(value: object) -> list[dict[str, object]]:
        """Keep only structured episodic records for Context."""

        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _memory_profile(value: object) -> dict[str, object]:
        """Keep only a structured user profile for Context."""

        return dict(value) if isinstance(value, dict) else {}

    def _tool_context(
        self,
        *,
        state: AgentState | None,
        conversation_id: str | None,
        intent: str | None,
        entities: dict[str, object] | None,
        request_id: str | None,
    ) -> dict[str, object]:
        """Provide safe request context to internal Tool handlers."""

        return {
            "knowledge_base": self.knowledge_base,
            "tool_manager": self.harness.executor if self.harness else None,
            "state": state,
            "agent_name": self.name,
            "conversation_id": conversation_id,
            "intent": intent,
            "entities": dict(entities or {}),
            "request_id": request_id,
        }

    def _record_trace(
        self,
        event_type: TraceEventType,
        *,
        request_id: str | None,
        conversation_id: str | None,
        data: dict[str, object],
    ) -> None:
        """Write an Agent event when this instance has a Harness tracer."""

        if self.harness:
            self.harness.record_trace(
                event_type,
                request_id=request_id,
                conversation_id=conversation_id,
                agent_name=self.name,
                data=data,
            )

    async def _run_tool_loop(
        self,
        *,
        user_message: str,
        history_payload: list[dict[str, str]],
        system_prompt: str | None,
        tool_schemas: list[dict[str, object]],
        allowed_tools: set[str],
        state: AgentState | None,
        intent: str | None,
        entities: dict[str, object] | None,
        request_id: str | None,
        conversation_id: str | None,
    ) -> str:
        """Let the model request scoped Tools until it returns a final answer."""

        messages: list[dict[str, object]] = list(history_payload)
        messages.append({"role": "user", "content": user_message})
        tool_context = self._tool_context(
            state=state,
            conversation_id=conversation_id,
            intent=intent,
            entities=entities,
            request_id=request_id,
        )

        for _ in range(self.max_tool_iterations):
            completion = await self.llm.chat_with_tools(
                messages,
                tool_schemas,
                system_prompt=system_prompt,
                model=self.profile.model,
                temperature=self.profile.temperature,
                max_tokens=self.profile.max_tokens,
            )
            if not completion.tool_calls:
                if not completion.content.strip():
                    raise RuntimeError("Agent returned an empty final response")
                return completion.content.strip()

            messages.append(
                {
                    "role": "assistant",
                    "content": completion.content or None,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for call in completion.tool_calls
                    ],
                }
            )
            for call in completion.tool_calls:
                result = await self.harness.handle_tool_call(
                    ToolCall(
                        call_id=call.call_id,
                        tool_name=call.name,
                        arguments=call.arguments,
                        requested_by=self.name,
                    ),
                    state=state,
                    context=tool_context,
                    allowed_tools=allowed_tools,
                )
                self._record_tool_result(
                    tool_name=call.name,
                    call_id=call.call_id,
                    result=result,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": json.dumps(
                            result.model_dump(mode="json"),
                            ensure_ascii=False,
                        ),
                    }
                )

        raise RuntimeError("Agent Tool loop reached its maximum iterations")

    def _record_tool_result(
        self,
        *,
        tool_name: str,
        call_id: str,
        result: object,
    ) -> None:
        """Keep a small normalized record for the Orchestrator result."""

        success = bool(getattr(result, "success", False))
        requires_approval = bool(getattr(result, "requires_approval", False))
        error = getattr(result, "error", None)
        cached = bool(getattr(result, "cached", False))
        fallback_used = bool(getattr(result, "fallback_used", False))
        reranked = bool(getattr(result, "reranked", False))

        if success and tool_name not in self._last_tools_used:
            self._last_tools_used.append(tool_name)
        if not self._last_escalated and requires_approval:
            self._last_escalated = True
            self._last_escalation_source = "policy"
            self._last_escalation_reason = str(
                error or "This Tool action requires human approval."
            )
        elif (
            not self._last_escalated
            and not success
            and tool_name != "knowledge_search"
        ):
            self._last_escalated = True
            self._last_escalation_source = "tool_failure"
            self._last_escalation_reason = str(
                error or f"Tool '{tool_name}' could not complete the request."
            )
        self._last_tool_traces.append(
            {
                "agent_name": self.name,
                "tool_name": tool_name,
                "call_id": call_id,
                "success": success,
                "error": error,
                "duration_ms": getattr(result, "duration_ms", None),
                "cached": cached,
                "fallback_used": fallback_used,
                "reranked": reranked,
                "requires_approval": requires_approval,
            }
        )

    def _parse_escalation_marker(self, answer: str) -> str:
        """Extract the explicit Agent escalation marker and keep user text clean."""

        match = _ESCALATION_MARKER.match(answer)
        if not match:
            return answer.strip()

        self._last_escalated = True
        self._last_escalation_source = "agent_decision"
        self._last_escalation_reason = (
            match.group("reason").strip()
            or "The Agent determined that human support is required."
        )
        return answer[match.end():].lstrip() or (
            "I have marked this request for human support."
        )

    @property
    def last_tools_used(self) -> list[str]:
        """Return Tool names used during the latest Agent turn."""

        return list(self._last_tools_used)

    @property
    def last_tool_traces(self) -> list[dict[str, object]]:
        """Return Tool traces produced during the latest Agent turn."""

        return [dict(trace) for trace in self._last_tool_traces]

    @property
    def last_escalated(self) -> bool:
        """Return whether the Agent explicitly requested human support."""

        return self._last_escalated

    @property
    def last_escalation_reason(self) -> str | None:
        """Return the latest structured escalation reason."""

        return self._last_escalation_reason

    @property
    def last_escalation_source(self) -> str | None:
        """Return what produced the escalation signal."""

        return self._last_escalation_source
