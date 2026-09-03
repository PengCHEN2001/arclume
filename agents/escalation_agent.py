"""Deterministic Agent for human handoff requests."""

import json
from datetime import datetime, timezone

from agents.agent_profile import AgentProfile
from agents.customer_service_agent import CustomerServiceAgent
from schemas.context import ContextMessage
from schemas.state import AgentStatus


class EscalationAgent(CustomerServiceAgent):
    """Create a safe handoff response without inventing a completed operation."""

    name = "escalation"
    profile = AgentProfile(
        role="Human handoff and case transfer",
        mission="Summarize the request and tell the user that human support will continue it.",
        workflow=["confirm the handoff", "summarize known information", "state the next step"],
        input_contract=["user message", "intent", "urgency", "entities", "conversation history"],
        output_contract=["handoff reason", "known information", "safe next step"],
        handoff_conditions=["explicit human request", "critical urgency", "high-risk operation"],
        tool_scope=["create_handoff_summary"],
        temperature=0.0,
        max_tokens=500,
    )
    system_prompt = "You handle human-support handoffs. Do not claim that a backend action is complete."

    async def respond(
        self,
        message: str,
        *,
        user_id: str = "anonymous",
        conversation_id: str | None = None,
        intent: str | None = None,
        intent_group: str | None = None,
        intent_confidence: float = 0.0,
        urgency: str | None = None,
        entities: dict[str, object] | None = None,
        supporting_agents: list[str] | None = None,
        routing_reason: str | None = None,
        persist: bool = True,
        **_: object,
    ) -> str:
        """Persist a handoff marker and return a deterministic user message."""

        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Agent message cannot be empty")
        if (self.memory or self.state_store) and not conversation_id:
            raise ValueError("conversation_id is required when persistence is enabled")

        if persist and conversation_id and self.memory:
            await self.memory.add_message(
                user_id,
                conversation_id,
                ContextMessage(role="user", content=cleaned_message),
            )

        if conversation_id and self.state_store:
            state = await self.state_store.get_or_create(user_id, conversation_id)
            state = state.model_copy(
                update={
                    "status": AgentStatus.ESCALATED,
                    "active_agent": self.name,
                    "intent": intent,
                    "intent_group": intent_group,
                    "intent_confidence": intent_confidence,
                    "urgency": urgency,
                    "entities": dict(entities or {}),
                    "supporting_agents": list(supporting_agents or []),
                    "routing_reason": routing_reason,
                    "needs_human": True,
                    "needs_rag": False,
                    "version": state.version + 1,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            if persist:
                await self.state_store.save(state)

        response = (
            "I have marked this request for human support. "
            f"The recorded reason is {intent or 'a request that needs further review'}, "
            f"with urgency {urgency or 'low'}. "
            "Please do not share passwords, one-time codes, or full payment credentials."
        )
        if entities:
            # Only show non-sensitive structured identifiers that were already extracted.
            response += f" Known request details: {json.dumps(entities, ensure_ascii=False)}."

        if persist and conversation_id and self.memory:
            await self.memory.add_message(
                user_id,
                conversation_id,
                ContextMessage(role="assistant", content=response),
            )
        return response
