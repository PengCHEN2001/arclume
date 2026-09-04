"""Route one request to the right domain Agent and combine its result."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from agents.customer_service_agent import CustomerServiceAgent
from agents.escalation_agent import EscalationAgent
from agents.response_composer import ResponseComposer
from core.intent_recognizer import IntentCategory, IntentRecognizer, IntentResult, UrgencyLevel
from core.llm_utils import LLMConfigurationError, LLMRequestError


logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Executable Agent roles used by the routing layer."""

    GENERAL = "general"
    TECHNICAL = "technical"
    BILLING = "billing"
    ESCALATION = "escalation"


@dataclass
class AgentStats:
    """Small in-process statistics object used by future performance routing."""

    total: int = 0
    success: int = 0
    total_ms: float = 0.0
    monitor_penalty: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 1.0

    @property
    def average_ms(self) -> float:
        return self.total_ms / self.total if self.total else 0.0

    def routing_score(self) -> float:
        """Prefer reliable Agents while leaving room for Monitor penalties later."""

        latency_score = 1.0 / (1.0 + self.average_ms / 1000.0)
        base_score = self.success_rate * 0.7 + latency_score * 0.3
        return round(base_score * max(0.0, 1.0 - self.monitor_penalty), 4)


@dataclass
class AgentResponse:
    """Internal normalized result returned by one domain Agent."""

    agent_type: AgentType
    content: str
    success: bool
    latency_ms: float = 0.0
    escalated: bool = False
    tools_used: list[str] = field(default_factory=list)
    tool_traces: list[dict[str, Any]] = field(default_factory=list)
    error: Exception | None = None


@dataclass
class RoutingDecision:
    """Structured decision describing primary and supporting Agents."""

    primary_agent: AgentType
    supporting_agents: list[AgentType] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    use_rag: bool = False

    @property
    def agent_types(self) -> list[AgentType]:
        return [self.primary_agent, *self.supporting_agents]


@dataclass
class OrchestratorResult:
    """Public result returned to the API layer after orchestration."""

    request_id: str
    response: str
    intent: IntentResult
    primary_agent: AgentType
    supporting_agents: list[AgentType] = field(default_factory=list)
    routing_reason: str = ""
    routing_confidence: float = 0.0
    escalated: bool = False
    latency_ms: float = 0.0
    tools_used: list[str] = field(default_factory=list)
    tool_traces: list[dict[str, Any]] = field(default_factory=list)


class AgentOrchestrator:
    """Coordinate intent recognition, routing, execution, and fallback."""

    _INTENT_ROUTING: dict[IntentCategory, AgentType] = {
        IntentCategory.TECHNICAL: AgentType.TECHNICAL,
        IntentCategory.TECHNICAL_LOGIN: AgentType.TECHNICAL,
        IntentCategory.TECHNICAL_CRASH: AgentType.TECHNICAL,
        IntentCategory.BILLING: AgentType.BILLING,
        IntentCategory.REFUND: AgentType.BILLING,
        IntentCategory.INVOICE: AgentType.BILLING,
        IntentCategory.PAYMENT_ISSUE: AgentType.BILLING,
        IntentCategory.ACCOUNT: AgentType.BILLING,
        IntentCategory.ACCOUNT_SECURITY: AgentType.BILLING,
    }

    _ESCALATION_INTENTS = {
        IntentCategory.ESCALATION,
        IntentCategory.HUMAN_HANDOFF,
    }

    def __init__(
        self,
        *,
        general_agent: CustomerServiceAgent,
        technical_agent: CustomerServiceAgent,
        billing_agent: CustomerServiceAgent,
        escalation_agent: CustomerServiceAgent | None = None,
        intent_recognizer: IntentRecognizer | None = None,
        confidence_threshold: float = 0.5,
        response_composer: ResponseComposer | None = None,
    ) -> None:
        self.intent_recognizer = intent_recognizer or IntentRecognizer()
        self.confidence_threshold = confidence_threshold  # Clarification boundary
        self.response_composer = response_composer or ResponseComposer()
        self.escalation_agent = escalation_agent or EscalationAgent(
            llm=general_agent.llm,
            memory=general_agent.memory,
            state_store=general_agent.state_store,
            context_builder=general_agent.context_builder,
            knowledge_base=general_agent.knowledge_base,
            skill_loader=general_agent.skill_loader,
            harness=general_agent.harness,
        )
        self._pool: dict[AgentType, list[CustomerServiceAgent]] = {
            AgentType.GENERAL: [general_agent],
            AgentType.TECHNICAL: [technical_agent],
            AgentType.BILLING: [billing_agent],
            AgentType.ESCALATION: [self.escalation_agent],
        }
        self._stats = {
            agent_type: [AgentStats() for _ in agents]
            for agent_type, agents in self._pool.items()
        }

    async def run(
        self,
        message: str,
        *,
        user_id: str,
        conversation_id: str,
        history: list[dict[str, str]] | None = None,
        memory_context: dict[str, object] | None = None,
        request_id: str | None = None,
    ) -> OrchestratorResult:
        """Run intent recognition, routing, Agent execution, and fallback."""

        request_id = request_id or str(uuid4())
        started = time.monotonic()
        analysis = await self.intent_recognizer.recognize(message, history=history)
        if self._needs_clarification(analysis, message):
            return OrchestratorResult(
                request_id=request_id,
                response=(
                    "I am not yet sure which issue you want to handle. "
                    "Please clarify whether this concerns an order or delivery, "
                    "a refund or payment, an account, or a technical problem."
                ),
                intent=analysis,
                primary_agent=AgentType.GENERAL,
                routing_reason="Low-confidence intent; clarification requested",
                routing_confidence=analysis.confidence,
                latency_ms=(time.monotonic() - started) * 1000,
            )

        decision = self._make_decision(analysis)
        if decision.supporting_agents:
            responses = await self._run_parallel(
                message,
                analysis,
                decision,
                user_id=user_id,
                conversation_id=conversation_id,
                request_id=request_id,
                memory_context=memory_context,
            )
            successful = [response for response in responses if response.success]
            if not successful:
                self._raise_if_model_error(responses)
                response_text = "The support Agents were unable to complete this request."
            else:
                response_text = self.response_composer.compose(
                    successful,
                    primary_agent=decision.primary_agent.value,
                )
            escalated = analysis.urgency in {
                UrgencyLevel.HIGH,
                UrgencyLevel.CRITICAL,
            } or analysis.intent in self._ESCALATION_INTENTS
            return OrchestratorResult(
                request_id=request_id,
                response=response_text,
                intent=analysis,
                primary_agent=decision.primary_agent,
                supporting_agents=decision.supporting_agents,
                routing_reason=decision.reason,
                routing_confidence=decision.confidence,
                escalated=escalated,
                latency_ms=(time.monotonic() - started) * 1000,
                tools_used=self._unique_tools(responses),
                tool_traces=self._tool_traces(responses),
            )

        response = await self._execute(
            decision.primary_agent,
            message,
            analysis,
            decision,
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            memory_context=memory_context,
            persist=True,
        )
        if not response.success and decision.primary_agent != AgentType.GENERAL:
            logger.warning("%s failed; falling back to GeneralAgent", decision.primary_agent.value)
            response = await self._execute(
                AgentType.GENERAL,
                message,
                analysis,
                decision,
                user_id=user_id,
                conversation_id=conversation_id,
                request_id=request_id,
                memory_context=memory_context,
                persist=False,
            )
        if not response.success:
            self._raise_if_model_error([response])
            response_text = "The support Agent was unable to complete this request."
        else:
            response_text = response.content

        escalated = response.escalated or analysis.urgency in {
            UrgencyLevel.HIGH,
            UrgencyLevel.CRITICAL,
        } or analysis.intent in self._ESCALATION_INTENTS
        return OrchestratorResult(
            request_id=request_id,
            response=response_text,
            intent=analysis,
            primary_agent=decision.primary_agent,
            routing_reason=decision.reason,
            routing_confidence=decision.confidence,
            escalated=escalated,
            latency_ms=(time.monotonic() - started) * 1000,
            tools_used=list(response.tools_used),
            tool_traces=list(response.tool_traces),
        )

    async def _run_parallel(
        self,
        message: str,
        analysis: IntentResult,
        decision: RoutingDecision,
        *,
        user_id: str,
        conversation_id: str,
        request_id: str,
        memory_context: dict[str, object] | None,
    ) -> list[AgentResponse]:
        """Run the primary Agent and supporting Agents concurrently."""

        tasks = [
            self._execute(
                agent_type,
                message,
                analysis,
                decision,
                user_id=user_id,
                conversation_id=conversation_id,
                request_id=request_id,
                memory_context=memory_context,
                persist=agent_type == decision.primary_agent,
            )
            for agent_type in decision.agent_types
        ]
        return list(await asyncio.gather(*tasks))

    async def _execute(
        self,
        agent_type: AgentType,
        message: str,
        analysis: IntentResult,
        decision: RoutingDecision,
        *,
        user_id: str,
        conversation_id: str,
        request_id: str,
        memory_context: dict[str, object] | None,
        persist: bool,
    ) -> AgentResponse:
        """Execute one Agent and update local performance statistics."""

        agent, stats = self._best_agent(agent_type)
        if agent is None or stats is None:
            return AgentResponse(
                agent_type=AgentType.GENERAL,
                content="No available Agent is configured.",
                success=False,
            )

        started = time.monotonic()
        stats.total += 1
        try:
            content = await agent.respond(
                message,
                user_id=user_id,
                conversation_id=conversation_id,
                request_id=request_id,
                memory_context=memory_context,
                skill_names=self._skills_for(agent_type, analysis.intent),
                knowledge_enabled=decision.use_rag,
                intent=analysis.intent.value,
                intent_group=analysis.intent_group,
                intent_confidence=analysis.confidence,
                urgency=analysis.urgency.value,
                entities=analysis.entities,
                supporting_agents=[
                    item.value
                    for item in decision.supporting_agents
                    if item != agent_type
                ],
                routing_reason=decision.reason,
                persist=persist,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - started) * 1000
            stats.total_ms += elapsed
            logger.exception("Agent %s failed", agent_type.value)
            return AgentResponse(
                agent_type=agent_type,
                content="",
                success=False,
                latency_ms=elapsed,
                error=exc,
            )

        elapsed = (time.monotonic() - started) * 1000
        stats.success += 1
        stats.total_ms += elapsed
        return AgentResponse(
            agent_type=agent_type,
            content=content,
            success=True,
            latency_ms=elapsed,
            escalated=analysis.intent in self._ESCALATION_INTENTS,
            tools_used=agent.last_tools_used,
            tool_traces=agent.last_tool_traces,
        )

    def _make_decision(self, analysis: IntentResult) -> RoutingDecision:
        """Choose a primary Agent and optional supporting domain Agents."""

        if analysis.urgency == UrgencyLevel.CRITICAL or analysis.intent in self._ESCALATION_INTENTS:
            return RoutingDecision(
                primary_agent=AgentType.ESCALATION,
                reason="Escalation or critical urgency uses the human-support path",
                confidence=max(analysis.confidence, 0.8),
                use_rag=False,
            )

        score_by_type = {
            AgentType.GENERAL: analysis.domain_scores.get("general", 0.1),
            AgentType.TECHNICAL: analysis.domain_scores.get("technical", 0.0),
            AgentType.BILLING: analysis.domain_scores.get("billing", 0.0),
        }
        mapped_agent = self._INTENT_ROUTING.get(analysis.intent)
        primary_agent = mapped_agent or max(score_by_type, key=score_by_type.get)
        primary_score = score_by_type[primary_agent]
        supporting_agents = [
            agent_type
            for agent_type, score in sorted(
                score_by_type.items(), key=lambda item: item[1], reverse=True
            )
            if agent_type != primary_agent
            and agent_type != AgentType.GENERAL
            and score >= 0.45
            and score >= primary_score * 0.55
        ]
        score_text = ", ".join(
            f"{agent_type.value}={score:.2f}"
            for agent_type, score in sorted(
                score_by_type.items(), key=lambda item: item[1], reverse=True
            )
        )
        support_text = ", ".join(agent.value for agent in supporting_agents) or "none"
        reason = (
            f"intent={analysis.intent.value}, group={analysis.intent_group}, "
            f"primary={primary_agent.value}, supporting={support_text}, scores=[{score_text}]"
        )
        return RoutingDecision(
            primary_agent=primary_agent,
            supporting_agents=supporting_agents,
            reason=reason,
            confidence=round(max(analysis.confidence, primary_score), 3),
            use_rag=analysis.should_use_rag,
        )

    def _best_agent(
        self,
        agent_type: AgentType,
    ) -> tuple[CustomerServiceAgent | None, AgentStats | None]:
        agents = self._pool.get(agent_type, [])
        stats = self._stats.get(agent_type, [])
        if not agents:
            return None, None
        index = max(range(len(agents)), key=lambda item: stats[item].routing_score())
        return agents[index], stats[index]

    @staticmethod
    def _skills_for(agent_type: AgentType, intent: IntentCategory) -> list[str]:
        """Select only the small set of rules relevant to this Agent turn."""

        if intent in {IntentCategory.ESCALATION, IntentCategory.HUMAN_HANDOFF}:
            return ["escalation"]
        if agent_type == AgentType.TECHNICAL:
            return ["technical"]
        if agent_type == AgentType.BILLING and intent in {
            IntentCategory.REFUND,
            IntentCategory.INVOICE,
            IntentCategory.PAYMENT_ISSUE,
            IntentCategory.BILLING,
        }:
            return ["refund"]
        if agent_type == AgentType.GENERAL and intent in {
            IntentCategory.ORDER_STATUS,
            IntentCategory.LOGISTICS,
        }:
            return ["logistics"]
        return []

    @staticmethod
    def _needs_clarification(analysis: IntentResult, message: str) -> bool:
        return (
            analysis.intent == IntentCategory.OTHER
            and len(message.strip()) > 2
            and analysis.confidence < 0.5
        )

    @staticmethod
    def _unique_tools(responses: list[AgentResponse]) -> list[str]:
        """Return Tool names in first-use order across all Agent responses."""

        names: list[str] = []
        for response in responses:
            for name in response.tools_used:
                if name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _tool_traces(responses: list[AgentResponse]) -> list[dict[str, Any]]:
        """Flatten Tool traces while keeping the Agent source on each record."""

        return [trace for response in responses for trace in response.tool_traces]

    @staticmethod
    def _raise_if_model_error(responses: list[AgentResponse]) -> None:
        for response in responses:
            if isinstance(response.error, (LLMConfigurationError, LLMRequestError)):
                raise response.error

    def get_stats(self) -> dict[str, dict[str, float | int]]:
        """Expose routing statistics for the future Monitor module."""

        return {
            agent_type.value: {
                "total": stats[0].total,
                "success": stats[0].success,
                "success_rate": round(stats[0].success_rate, 4),
                "average_ms": round(stats[0].average_ms, 2),
                "routing_score": stats[0].routing_score(),
            }
            for agent_type, stats in self._stats.items()
            if stats
        }

    def list_agents(self) -> list[AgentType]:
        """Return the currently registered executable Agent types."""

        return list(self._pool)
