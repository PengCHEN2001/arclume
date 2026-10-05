"""Recognize customer-support intent before selecting a domain Agent."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from enum import Enum
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from core.llm_utils import LLMClient


logger = logging.getLogger(__name__)


class IntentCategory(str, Enum):
    """Fine-grained support intents used by the routing table."""

    QUERY = "query"
    COMPLAINT = "complaint"
    REQUEST = "request"
    GREETING = "greeting"
    ESCALATION = "escalation"
    TECHNICAL = "technical"
    BILLING = "billing"
    ACCOUNT = "account"
    FEEDBACK = "feedback"
    ORDER_STATUS = "order_status"
    LOGISTICS = "logistics"
    REFUND = "refund"
    INVOICE = "invoice"
    PAYMENT_ISSUE = "payment_issue"
    ACCOUNT_SECURITY = "account_security"
    TECHNICAL_LOGIN = "technical_login"
    TECHNICAL_CRASH = "technical_crash"
    HUMAN_HANDOFF = "human_handoff"
    OTHER = "other"


class UrgencyLevel(str, Enum):
    """Urgency attached to the current support request."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


InformationNeed = Literal["none", "knowledge", "live_data", "mixed", "action"]


class IntentSubtask(BaseModel):
    """One domain-scoped part of a compound customer request."""

    domain: Literal["general", "technical", "billing"]
    query: str = Field(min_length=1)
    intent: IntentCategory
    information_need: InformationNeed = "none"
    should_use_rag: bool = False
    planned_tool_name: str | None = None
    entities: dict[str, list[str]] = Field(default_factory=dict)


class IntentResult(BaseModel):
    """Normalized intent data shared by the Orchestrator and Agents."""

    intent: IntentCategory
    intent_group: str
    confidence: float = Field(ge=0.0, le=1.0)
    urgency: UrgencyLevel = UrgencyLevel.LOW
    entities: dict[str, list[str]] = Field(default_factory=dict)
    source_scores: dict[str, float] = Field(default_factory=dict)
    domain_scores: dict[str, float] = Field(default_factory=dict)
    matched_intents: list[IntentCategory] = Field(default_factory=list)
    reasoning: str = ""
    latency_ms: float = Field(default=0.0, ge=0.0)
    should_use_rag: bool = False
    information_need: InformationNeed = "none"
    planned_tool_name: str | None = None
    topic_evidence: dict[str, list[str]] = Field(default_factory=dict)
    ambiguity_reasons: list[str] = Field(default_factory=list)
    supporting_domains: list[str] | None = None
    subtasks: list[IntentSubtask] = Field(default_factory=list)


_TEMPLATES: dict[IntentCategory, list[str]] = {
    IntentCategory.GREETING: ["你好", "hello", "hi", "有人吗", "is anyone there"],
    IntentCategory.ORDER_STATUS: [
        "订单状态", "订单有没有发货", "order status", "has my order shipped",
    ],
    IntentCategory.LOGISTICS: [
        "快递什么时候到", "物流一直不更新", "delivery status", "when will my package arrive",
    ],
    IntentCategory.REFUND: [
        "申请退款", "退货退款怎么处理", "refund request", "I want to request a refund",
    ],
    IntentCategory.INVOICE: [
        "帮我开发票", "电子发票在哪里", "invoice", "where is my invoice",
    ],
    IntentCategory.PAYMENT_ISSUE: [
        "重复扣款", "支付失败", "payment failed", "I was charged twice",
    ],
    IntentCategory.ACCOUNT_SECURITY: [
        "账户被盗", "异常登录", "重置密码", "account hacked", "suspicious login",
    ],
    IntentCategory.TECHNICAL_LOGIN: [
        "无法登录", "登录报 401", "验证码收不到", "cannot log in", "I cannot sign in",
    ],
    IntentCategory.TECHNICAL_CRASH: [
        "应用崩溃", "页面报 500", "系统闪退", "the app crashed", "server error 500",
    ],
    IntentCategory.HUMAN_HANDOFF: [
        "转人工客服", "我要找人工", "请升级处理", "connect me to a human", "human support",
    ],
    IntentCategory.COMPLAINT: [
        "服务太差", "我要投诉", "等了很久", "the service is terrible", "I want to complain",
    ],
    IntentCategory.FEEDBACK: [
        "服务很好", "非常满意", "给个好评", "great service", "I am very satisfied",
    ],
    IntentCategory.QUERY: ["怎么处理", "是什么", "how can I", "what is this"],
    IntentCategory.REQUEST: ["帮我处理", "我需要帮助", "please help", "I need assistance"],
}

_PATTERNS: dict[IntentCategory, tuple[str, ...]] = {
    # Specific patterns are checked before broad domain patterns.
    IntentCategory.HUMAN_HANDOFF: (
        "转人工", "人工客服", "找人工", "supervisor", "human agent", "connect me to a human",
    ),
    IntentCategory.ORDER_STATUS: (
        "订单状态", "订单有没有发货", "订单处理到哪", "order status", "has my order shipped",
        "my order", "order #",
    ),
    IntentCategory.LOGISTICS: (
        "物流", "快递", "配送", "运单", "包裹", "包裹什么时候到",
        "delivery", "shipping", "tracking", "package", "when will my package arrive",
    ),
    IntentCategory.REFUND: (
        "退款", "退货退款", "退货", "refund", "return", "money back",
    ),
    IntentCategory.INVOICE: ("发票", "抬头", "税号", "invoice", "tax receipt"),
    IntentCategory.PAYMENT_ISSUE: (
        "重复扣款", "多扣", "支付失败", "扣费异常", "payment failed", "charged twice",
    ),
    IntentCategory.ACCOUNT_SECURITY: (
        "账户被盗", "异常登录", "重置密码", "两步验证", "account hacked", "suspicious login",
    ),
    IntentCategory.TECHNICAL_LOGIN: (
        "无法登录", "登录失败", "401", "验证码收不到", "cannot log in", "cannot sign in",
    ),
    IntentCategory.TECHNICAL_CRASH: (
        "崩溃", "闪退", "500", "报错", "crash", "error code", "server error",
    ),
    IntentCategory.ESCALATION: (
        "投诉", "找经理", "经理", "supervisor", "投诉处理", "escalate this issue",
    ),
    IntentCategory.COMPLAINT: (
        "太差", "糟糕", "horrible", "等了很久", "不满意", "terrible service",
    ),
    IntentCategory.FEEDBACK: (
        "服务很好", "非常满意", "好评", "great service", "满意", "very satisfied",
    ),
    IntentCategory.GREETING: (
        "你好", "嗨", "hello", "hi", "早上好", "good morning", "is anyone there",
    ),
    IntentCategory.QUERY: (
        "?", "？", "怎么", "什么", "如何", "how", "what", "where", "when",
        "introduce", "tell me about", "feature", "features", "specification", "specifications",
    ),
    IntentCategory.REQUEST: (
        "帮我", "需要", "请协助", "please", "help", "I need", "can you",
    ),
    IntentCategory.BILLING: (
        "账单", "扣款", "订阅", "billing", "payment", "subscription",
    ),
    IntentCategory.TECHNICAL: (
        "技术问题", "系统错误", "技术支持", "technical support", "technical issue",
    ),
    IntentCategory.ACCOUNT: (
        "账户", "邮箱", "个人信息", "account", "password", "profile",
    ),
}

_INTENT_GROUPS: dict[IntentCategory, str] = {
    IntentCategory.ORDER_STATUS: "query",
    IntentCategory.LOGISTICS: "query",
    IntentCategory.REFUND: "billing",
    IntentCategory.INVOICE: "billing",
    IntentCategory.PAYMENT_ISSUE: "billing",
    IntentCategory.ACCOUNT_SECURITY: "account",
    IntentCategory.TECHNICAL_LOGIN: "technical",
    IntentCategory.TECHNICAL_CRASH: "technical",
    IntentCategory.HUMAN_HANDOFF: "escalation",
}

_TECHNICAL_INTENTS = {
    IntentCategory.TECHNICAL,
    IntentCategory.TECHNICAL_LOGIN,
    IntentCategory.TECHNICAL_CRASH,
}

_BILLING_INTENTS = {
    IntentCategory.BILLING,
    IntentCategory.ACCOUNT,
    IntentCategory.ACCOUNT_SECURITY,
    IntentCategory.REFUND,
    IntentCategory.INVOICE,
    IntentCategory.PAYMENT_ISSUE,
}

_GENERAL_INTENTS = {
    IntentCategory.QUERY,
    IntentCategory.COMPLAINT,
    IntentCategory.REQUEST,
    IntentCategory.GREETING,
    IntentCategory.FEEDBACK,
    IntentCategory.ORDER_STATUS,
    IntentCategory.LOGISTICS,
    IntentCategory.OTHER,
}

_TOPIC_INTENTS = _TECHNICAL_INTENTS | _BILLING_INTENTS | {
    IntentCategory.ORDER_STATUS,
    IntentCategory.LOGISTICS,
}
_WEAK_TOPIC_KEYWORDS = {"return", "account", "profile", "payment", "401", "500"}
_KNOWLEDGE_CUES = re.compile(
    r"\b(?:policy|policies|rules?|terms?|eligible|eligibility|how long|how to|"
    r"what steps|process|procedure|troubleshoot|fix|resolve|why does|introduce|"
    r"tell me about|features?|specifications?|product details?)\b",
    re.IGNORECASE,
)
_LIVE_DATA_CUES = re.compile(
    r"\b(?:my order|my package|my shipment|tracking status|order status|"
    r"delivery status|shipping status|track my|where is my|charged twice|"
    r"duplicate charge|my refund status)\b",
    re.IGNORECASE,
)
_ACTION_CUES = re.compile(
    r"\b(?:I want|I need|please|can you)\b.{0,35}\b(?:refund|cancel|change|create)\b",
    re.IGNORECASE,
)
_REFERENCE_ONLY = re.compile(r"\b(?:it|that|this|them)\b", re.IGNORECASE)

_URGENCY_KEYWORDS: dict[UrgencyLevel, tuple[str, ...]] = {
    UrgencyLevel.CRITICAL: (
        "紧急", "emergency", "urgent", "asap", "立刻", "immediately",
    ),
    UrgencyLevel.HIGH: ("马上", "尽快", "hurry", "now", "立即", "right away"),
    UrgencyLevel.MEDIUM: ("这周", "soon", "快点", "this week", "as soon as possible"),
}


class IntentRecognizer:
    """Provide cheap local recognition with an optional LLM refinement pass."""

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        use_llm: bool = False,
        confidence_threshold: float = 0.5,
        cache_size: int = 1000,
    ) -> None:
        self.llm = llm                         # Optional semantic refinement client
        self.use_llm = use_llm                 # Extra model call switch
        self.confidence_threshold = confidence_threshold  # Clarification boundary
        self.cache_size = cache_size           # Maximum in-process result cache
        self._cache: dict[str, IntentResult] = {}
        self._learned_templates: dict[IntentCategory, list[str]] = {
            intent: list(examples) for intent, examples in _TEMPLATES.items()
        }  # Human-corrected examples used by local similarity matching
        self.cache_hits = 0                    # Cache hits since process start
        self.cache_misses = 0                  # Cache misses since process start

    async def recognize(
        self,
        message: str,
        history: Iterable[dict[str, str]] | None = None,
    ) -> IntentResult:
        """Return one normalized result without requiring a model call by default."""

        cleaned = self._clean_text(message).strip()
        if not cleaned:
            raise ValueError("Intent message cannot be empty")

        cache_key = self._cache_key(cleaned, history)
        if cache_key in self._cache:
            self.cache_hits += 1
            return self._cache[cache_key]
        self.cache_misses += 1

        started = time.monotonic()
        evidence = self._pattern_evidence(cleaned)
        pattern_scores = self._scores_from_evidence(evidence)
        strong_topics = self._strong_topics(evidence)
        pattern_intent, pattern_confidence = self._best_match(pattern_scores)
        if strong_topics and pattern_intent not in {
            IntentCategory.HUMAN_HANDOFF, IntentCategory.ESCALATION,
        }:
            # Question words describe speech act, not the business topic.
            pattern_intent, pattern_confidence = self._best_match(
                {intent: pattern_scores[intent] for intent in evidence if intent in strong_topics}
            )
        template_intent, template_confidence, template_margin = self._template_match(cleaned)
        if (
            not strong_topics
            and template_intent in _TOPIC_INTENTS
            and template_confidence >= 0.75
            and template_margin >= 0.15
            and pattern_intent in {IntentCategory.QUERY, IntentCategory.REQUEST, IntentCategory.OTHER}
        ):
            # A strong example match can recover a topic when only generic
            # question/request words were recognized locally.
            pattern_intent = IntentCategory.OTHER
        ambiguity_reasons = self._ambiguity_reasons(
            cleaned, evidence, strong_topics, template_intent,
            template_confidence, template_margin,
        )

        llm_result: dict[str, Any] = {}
        # The local path is the default so intent routing does not double model cost.
        if self.use_llm and self.llm is not None and ambiguity_reasons:
            llm_result = await self._llm_match(cleaned, history)

        intent, confidence, reasoning = self._fuse(
            pattern_intent,
            pattern_confidence,
            template_intent,
            template_confidence,
            llm_result,
        )
        entities = self._extract_entities(cleaned)
        urgency = self._detect_urgency(cleaned, intent)
        information_need = self._information_need(cleaned, intent, strong_topics)
        planned_tool_name = self._planned_tool(intent, information_need, entities)
        supporting_domains = self._independent_domains(cleaned, strong_topics)
        subtasks = self._build_subtasks(cleaned, intent, supporting_domains)
        result = IntentResult(
            intent=intent,
            intent_group=_INTENT_GROUPS.get(intent, intent.value),
            confidence=confidence,
            urgency=urgency,
            entities=entities,
            source_scores={
                "pattern": round(pattern_confidence, 3),
                "template": round(template_confidence, 3),
                "llm": round(float(llm_result.get("confidence", 0.0) or 0.0), 3),
            },
            domain_scores=self._domain_scores(pattern_scores, intent),
            matched_intents=self._matched_intents(pattern_scores),
            reasoning=reasoning,
            latency_ms=(time.monotonic() - started) * 1000,
            should_use_rag=information_need in {"knowledge", "mixed"},
            information_need=information_need,
            planned_tool_name=planned_tool_name,
            topic_evidence={intent.value: hits for intent, hits in evidence.items() if intent in _TOPIC_INTENTS},
            ambiguity_reasons=ambiguity_reasons,
            supporting_domains=supporting_domains,
            subtasks=subtasks,
        )
        self._remember(cache_key, result)
        return result

    def clear_cache(self) -> None:
        """Clear local recognition results after changing routing rules."""

        self._cache.clear()

    def learn(self, message: str, correct: IntentCategory | str) -> None:
        """Add one human-corrected example to the local similarity templates."""

        cleaned = self._clean_text(message).strip()
        if not cleaned:
            raise ValueError("Learned Intent message cannot be empty")
        try:
            intent = correct if isinstance(correct, IntentCategory) else IntentCategory(str(correct))
        except ValueError as exc:
            raise ValueError(f"Unknown Intent category: {correct}") from exc

        examples = self._learned_templates.setdefault(intent, [])
        if cleaned not in examples:
            examples.append(cleaned)
        # Keep feedback bounded so a long-running process cannot grow forever.
        del examples[:-50]
        self.clear_cache()

    def cache_stats(self) -> dict[str, int]:
        """Return local cache and feedback statistics for diagnostics."""

        return {
            "size": len(self._cache),
            "max_size": self.cache_size,
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "learned_examples": sum(
                max(0, len(values) - len(_TEMPLATES.get(intent, [])))
                for intent, values in self._learned_templates.items()
            ),
        }

    def _pattern_scores(self, message: str) -> dict[IntentCategory, float]:
        """Score all matching patterns so compound requests retain both domains."""

        return self._scores_from_evidence(self._pattern_evidence(message))

    @staticmethod
    def _pattern_evidence(message: str) -> dict[IntentCategory, list[str]]:
        """Keep the matched phrases, not only their uncalibrated scores."""

        lowered = message.lower()
        evidence: dict[IntentCategory, list[str]] = {}
        for intent, keywords in _PATTERNS.items():
            hits = [keyword for keyword in keywords if IntentRecognizer._keyword_matches(lowered, keyword)]
            if hits:
                evidence[intent] = hits
        return evidence

    @staticmethod
    def _keyword_matches(lowered: str, keyword: str) -> bool:
        value = keyword.lower()
        if value.isascii() and any(char.isalpha() for char in value):
            suffix = r"(?![a-z0-9])" if value[-1].isalnum() else ""
            return re.search(r"(?<![a-z0-9])" + re.escape(value) + suffix, lowered) is not None
        return value in lowered

    @staticmethod
    def _scores_from_evidence(evidence: dict[IntentCategory, list[str]]) -> dict[IntentCategory, float]:
        scores: dict[IntentCategory, float] = {}
        for intent, hits in evidence.items():
            scores[intent] = min(1.0, 0.5 + 0.2 * (len(hits) - 1))
        return scores

    def _template_match(self, message: str) -> tuple[IntentCategory, float, float]:
        """Compare against preset example questions using local character n-grams."""

        message_vector = self._vectorize(message)
        scores: list[tuple[IntentCategory, float]] = []
        for intent, examples in self._learned_templates.items():
            score = max(
                self._cosine(message_vector, self._vectorize(example))
                for example in examples
            )
            scores.append((intent, max(0.0, min(1.0, score))))
        scores.sort(key=lambda item: item[1], reverse=True)
        best_intent, best_score = scores[0]
        second_score = scores[1][1] if len(scores) > 1 else 0.0
        return best_intent, best_score, best_score - second_score

    @staticmethod
    def _strong_topics(evidence: dict[IntentCategory, list[str]]) -> set[IntentCategory]:
        return {
            intent for intent, hits in evidence.items()
            if intent in _TOPIC_INTENTS
            and any(hit.lower() not in _WEAK_TOPIC_KEYWORDS for hit in hits)
        }

    def _ambiguity_reasons(
        self,
        message: str,
        evidence: dict[IntentCategory, list[str]],
        strong_topics: set[IntentCategory],
        template_intent: IntentCategory,
        template_confidence: float,
        template_margin: float,
    ) -> list[str]:
        """Request model review only when local evidence cannot settle the topic."""

        if IntentCategory.HUMAN_HANDOFF in evidence or IntentCategory.ESCALATION in evidence:
            return []
        strong_domains = {self._domain_for(intent) for intent in strong_topics}
        strong_domains.discard(None)
        if len(strong_domains) > 1:
            return [] if self._independent_domains(message, strong_topics) else ["overlapping_domains"]
        if strong_topics:
            return []
        weak_topics = [intent for intent in evidence if intent in _TOPIC_INTENTS]
        if weak_topics:
            return ["weak_or_ambiguous_keyword"]
        if template_intent not in _TOPIC_INTENTS and (
            IntentCategory.GREETING in evidence or IntentCategory.FEEDBACK in evidence
        ):
            return []
        if template_intent in _TOPIC_INTENTS and template_confidence >= 0.75 and template_margin >= 0.15:
            return []
        if _REFERENCE_ONLY.search(message) or IntentCategory.QUERY in evidence or IntentCategory.REQUEST in evidence:
            return ["no_reliable_business_topic"]
        return []

    @staticmethod
    def _domain_for(intent: IntentCategory) -> str | None:
        if intent in _TECHNICAL_INTENTS:
            return "technical"
        if intent in _BILLING_INTENTS:
            return "billing"
        if intent in {IntentCategory.ORDER_STATUS, IntentCategory.LOGISTICS}:
            return "general"
        return None

    def _independent_domains(self, message: str, strong_topics: set[IntentCategory]) -> list[str]:
        """Require separate clauses before treating two domain hits as two issues."""

        domains = {self._domain_for(intent) for intent in strong_topics}
        domains.discard(None)
        if len(domains) < 2:
            return []
        clauses = re.split(r"[,;]|\b(?:and|also|plus|but)\b", message, flags=re.IGNORECASE)
        clause_domains = [
            {
                domain
                for intent in self._strong_topics(self._pattern_evidence(clause))
                if (domain := self._domain_for(intent)) is not None
            }
            for clause in clauses
        ]
        independent = any(
            left - right and right - left
            for index, left in enumerate(clause_domains)
            for right in clause_domains[index + 1 :]
        )
        return sorted(domains) if independent else []

    def _build_subtasks(
        self,
        message: str,
        final_intent: IntentCategory,
        supporting_domains: list[str],
    ) -> list[IntentSubtask]:
        """Assign independent clauses to domain Agents without another model call.

        A single-domain request remains intact. Compound requests are split only
        after `_independent_domains` has found separate domain evidence, avoiding
        broad sentence splitting for ordinary messages.
        """

        if not supporting_domains:
            domain = self._domain_for(final_intent) or "general"
            evidence = self._pattern_evidence(message)
            strong_topics = self._strong_topics(evidence)
            entities = self._extract_entities(message)
            information_need = self._information_need(message, final_intent, strong_topics)
            return [IntentSubtask(
                domain=domain,
                query=message.strip(),
                intent=final_intent,
                information_need=information_need,
                should_use_rag=information_need in {"knowledge", "mixed"},
                planned_tool_name=self._planned_tool(final_intent, information_need, entities),
                entities=entities,
            )]

        clauses = [
            clause.strip()
            for clause in re.split(
                r"\s*(?:[,;]+|\b(?:and|also|plus|but)\b)\s*",
                message,
                flags=re.IGNORECASE,
            )
            if clause.strip()
        ]
        grouped: dict[str, list[str]] = {}
        for clause in clauses:
            clause_evidence = self._pattern_evidence(clause)
            clause_topics = self._strong_topics(clause_evidence)
            clause_scores = self._scores_from_evidence(clause_evidence)
            topic_scores = {
                intent: score
                for intent, score in clause_scores.items()
                if intent in clause_topics
            }
            clause_intent, _ = self._best_match(topic_scores)
            domain = self._domain_for(clause_intent)
            if domain is None:
                # General owns independent product and routine-information clauses
                # that do not match a specialist domain.
                domain = "general"
            grouped.setdefault(domain, []).append(clause)

        subtasks: list[IntentSubtask] = []
        for domain, domain_clauses in grouped.items():
            query = " ".join(domain_clauses).strip()
            evidence = self._pattern_evidence(query)
            strong_topics = self._strong_topics(evidence)
            scores = {
                intent: score
                for intent, score in self._scores_from_evidence(evidence).items()
                if self._domain_for(intent) == domain
            }
            task_intent, _ = self._best_match(scores)
            if task_intent == IntentCategory.OTHER:
                if self._domain_for(final_intent) == domain:
                    task_intent = final_intent
                else:
                    task_intent = {
                        "technical": IntentCategory.TECHNICAL,
                        "billing": IntentCategory.BILLING,
                    }.get(domain, IntentCategory.QUERY)
            entities = self._extract_entities(query)
            information_need = self._information_need(query, task_intent, strong_topics)
            subtasks.append(IntentSubtask(
                domain=domain,
                query=query,
                intent=task_intent,
                information_need=information_need,
                should_use_rag=information_need in {"knowledge", "mixed"},
                planned_tool_name=self._planned_tool(task_intent, information_need, entities),
                entities=entities,
            ))
        return subtasks

    @staticmethod
    def _information_need(
        message: str,
        intent: IntentCategory,
        strong_topics: set[IntentCategory],
    ) -> InformationNeed:
        if intent in {IntentCategory.HUMAN_HANDOFF, IntentCategory.ESCALATION,
                      IntentCategory.GREETING, IntentCategory.FEEDBACK, IntentCategory.COMPLAINT}:
            return "none"
        live_data = bool(_LIVE_DATA_CUES.search(message))
        requests_action = bool(_ACTION_CUES.search(message))
        knowledge = bool(_KNOWLEDGE_CUES.search(message)) or bool(
            (strong_topics | {intent}) & (_TECHNICAL_INTENTS | {IntentCategory.ACCOUNT_SECURITY})
        ) or (intent == IntentCategory.REFUND and not requests_action)
        if live_data and knowledge:
            return "mixed"
        if live_data:
            return "live_data"
        if knowledge:
            return "knowledge"
        if requests_action:
            return "action"
        if intent in {IntentCategory.PAYMENT_ISSUE, IntentCategory.INVOICE}:
            return "live_data"
        return "none"

    @staticmethod
    def _planned_tool(intent: IntentCategory, need: str, entities: dict[str, list[str]]) -> str | None:
        if need not in {"live_data", "mixed"}:
            return None
        if intent == IntentCategory.ORDER_STATUS and entities.get("order_id"):
            return "order_query"
        if intent == IntentCategory.LOGISTICS and entities.get("tracking_id"):
            return "logistics_query"
        return None

    async def _llm_match(
        self,
        message: str,
        history: Iterable[dict[str, str]] | None,
    ) -> dict[str, Any]:
        """Ask the configured model for refinement when local confidence is low."""

        recent = list(history or [])[-3:]
        history_text = "\n".join(
            f"{item.get('role', 'user')}: {self._clean_text(item.get('content', ''))}"
            for item in recent
        )
        prompt = (
            "Classify this customer-support message as JSON only. "
            "Prefer the most specific intent. "
            f"Allowed intents: {', '.join(item.value for item in IntentCategory)}.\n"
            f"Recent context:\n{history_text}\n"
            f"Message: {message}\n"
            'Return {"intent":"...","confidence":0.0,"reasoning":"..."}. '
        )
        try:
            raw = await self.llm.chat(prompt, system_prompt="You are an intent classifier.")
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                return {}
            data = json.loads(raw[start : end + 1])
            try:
                data["intent"] = IntentCategory(str(data.get("intent", "other")))
            except ValueError:
                data["intent"] = IntentCategory.OTHER
            return data
        except Exception as exc:
            logger.warning("Optional intent LLM refinement failed: %s", exc)
            return {}

    def _fuse(
        self,
        pattern_intent: IntentCategory,
        pattern_confidence: float,
        embedding_intent: IntentCategory,
        embedding_confidence: float,
        llm_result: dict[str, Any],
    ) -> tuple[IntentCategory, float, str]:
        """Combine local evidence and optional model evidence."""

        llm_intent = llm_result.get("intent", IntentCategory.OTHER)
        llm_confidence = float(llm_result.get("confidence", 0.0) or 0.0)
        if not isinstance(llm_intent, IntentCategory):
            llm_intent = IntentCategory.OTHER

        if llm_confidence > 0.0:
            candidates = [
                (llm_intent, llm_confidence * 0.7),
                (embedding_intent, embedding_confidence * 0.2),
                (pattern_intent, pattern_confidence * 0.1),
            ]
            scores: dict[IntentCategory, float] = {}
            for intent, score in candidates:
                scores[intent] = scores.get(intent, 0.0) + score
            intent = max(scores, key=scores.get)
            confidence = min(1.0, scores[intent])
            return intent, confidence, str(llm_result.get("reasoning", "LLM refinement"))

        # A direct business keyword is more reliable than a weak local similarity.
        if pattern_intent != IntentCategory.OTHER and pattern_confidence >= self.confidence_threshold:
            return pattern_intent, pattern_confidence, "pattern match"
        if embedding_intent != IntentCategory.OTHER and embedding_confidence >= self.confidence_threshold:
            return embedding_intent, embedding_confidence, "template similarity match"
        return IntentCategory.OTHER, 0.0, "no reliable intent match"

    def _domain_scores(
        self,
        pattern_scores: dict[IntentCategory, float],
        final_intent: IntentCategory,
    ) -> dict[str, float]:
        """Convert fine-grained evidence into scores for the three Agent domains."""

        scores = {"general": 0.1, "technical": 0.0, "billing": 0.0}
        for intent, score in pattern_scores.items():
            if intent in _TECHNICAL_INTENTS:
                scores["technical"] = max(scores["technical"], score)
            elif intent in _BILLING_INTENTS:
                scores["billing"] = max(scores["billing"], score)
            elif intent in _GENERAL_INTENTS:
                scores["general"] = max(scores["general"], score)

        if final_intent in _TECHNICAL_INTENTS:
            scores["technical"] = max(scores["technical"], 0.75)
        elif final_intent in _BILLING_INTENTS:
            scores["billing"] = max(scores["billing"], 0.75)
        elif final_intent not in _TECHNICAL_INTENTS | _BILLING_INTENTS:
            scores["general"] = max(scores["general"], 0.65)
        return {key: round(min(value, 1.0), 3) for key, value in scores.items()}

    @staticmethod
    def _matched_intents(scores: dict[IntentCategory, float]) -> list[IntentCategory]:
        """Return matched domains in descending confidence order."""

        return [
            intent
            for intent, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
            if score >= 0.5
        ]

    @staticmethod
    def _best_match(scores: dict[IntentCategory, float]) -> tuple[IntentCategory, float]:
        if not scores:
            return IntentCategory.OTHER, 0.0
        return max(scores.items(), key=lambda item: item[1])

    @staticmethod
    def _detect_urgency(message: str, intent: IntentCategory) -> UrgencyLevel:
        lowered = message.lower()
        for level, keywords in _URGENCY_KEYWORDS.items():
            if any(keyword.lower() in lowered for keyword in keywords):
                return level
        if intent in {IntentCategory.ESCALATION, IntentCategory.HUMAN_HANDOFF}:
            return UrgencyLevel.HIGH
        if intent == IntentCategory.COMPLAINT:
            return UrgencyLevel.MEDIUM
        return UrgencyLevel.LOW

    @staticmethod
    def _extract_entities(message: str) -> dict[str, list[str]]:
        """Extract high-value identifiers without another model call."""

        return {
            "order_id": IntentRecognizer._unique(
                re.findall(
                    r"(?:订单号?|order(?:_id)?|order number|#)\s*[:：#]?\s*([A-Za-z0-9_-]{4,32})",
                    message,
                    re.IGNORECASE,
                )
            ),
            "tracking_id": IntentRecognizer._unique(
                re.findall(
                    r"(?:运单号?|物流单号?|tracking(?:_id)?|tracking number)\s*[:：#]?\s*([A-Za-z0-9_-]{4,32})",
                    message,
                    re.IGNORECASE,
                )
            ),
            "amount": IntentRecognizer._unique(
                re.findall(
                    r"(?:¥|￥)\s*\d+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?\s*(?:元|块|rmb|cny|usd|美元)",
                    message,
                    re.IGNORECASE,
                )
            ),
            "error_code": IntentRecognizer._unique(
                re.findall(r"\b(?:[45]\d{2}|[A-Z][A-Z0-9_-]{2,16})\b", message)
            ),
            "date": IntentRecognizer._unique(
                re.findall(
                    r"今天|明天|昨天|本周|这周|下周|today|tomorrow|yesterday|this week|next week|"
                    r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?",
                    message,
                    re.IGNORECASE,
                )
            ),
        }

    def _remember(self, key: str, result: IntentResult) -> None:
        if self.cache_size <= 0:
            return
        if len(self._cache) >= self.cache_size:
            for old_key in list(self._cache)[: max(1, self.cache_size // 2)]:
                del self._cache[old_key]
        self._cache[key] = result

    @staticmethod
    def _cache_key(message: str, history: Iterable[dict[str, str]] | None) -> str:
        payload = {"message": message, "history": list(history or [])[-3:]}
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _vectorize(text: str, dimensions: int = 256) -> list[float]:
        """Create a small deterministic n-gram vector for local similarity."""

        normalized = text.lower().strip()
        vector = [0.0] * dimensions
        grams = {
            normalized[index : index + size]
            for size in (1, 2, 3)
            for index in range(max(0, len(normalized) - size + 1))
        }
        for gram in grams or {normalized}:
            digest = hashlib.md5(gram.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        return vector

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).encode("utf-8", errors="ignore").decode("utf-8")
