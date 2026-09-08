"""Reliable management for internal Tools and enhanced knowledge retrieval."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import logging
import os
import re
import time
from typing import Any

from core.llm_utils import LLMClient
from harness.executor import ToolDefinition, ToolExecutor
from knowledge import KnowledgeBaseError
from knowledge.hybrid_retriever import HybridRetriever
from knowledge.knowledge_base import KnowledgeBase
from schemas.tool import ToolCall, ToolResult


logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """States of one Tool circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ToolStats:
    """In-process metrics collected for one registered Tool."""

    total: int = 0
    success: int = 0
    failed: int = 0
    cache_hits: int = 0
    fallback_count: int = 0
    total_latency_ms: float = 0.0
    consecutive_failures: int = 0

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 1.0

    @property
    def average_latency_ms(self) -> float:
        return self.total_latency_ms / self.total if self.total else 0.0


class CircuitBreaker:
    """Open a Tool circuit after repeated failures and probe recovery later."""

    def __init__(self, *, failure_threshold: int = 5, recovery_seconds: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at: float | None = None

    def allow(self) -> bool:
        """Return whether one execution may pass through the breaker."""

        if self.state is CircuitState.CLOSED:
            return True
        if self.state is CircuitState.OPEN:
            if self.opened_at and time.monotonic() - self.opened_at >= self.recovery_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        """Close the breaker after a successful execution or probe."""

        self.failure_count = 0
        self.opened_at = None
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Count a failure and open the breaker after the configured threshold."""

        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()


class ToolManager(ToolExecutor):
    """Add caching, circuit breaking, fallback, statistics, and RAG orchestration."""

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        knowledge_base: KnowledgeBase | None = None,
        cache_cleanup_interval_seconds: float = 60.0,
        hybrid_retriever: HybridRetriever | None = None,
    ) -> None:
        super().__init__()
        self.llm = llm                              # Optional rewrite/rerank client
        self.knowledge_base = knowledge_base        # Low-level ChromaDB adapter
        self.cache_cleanup_interval_seconds = cache_cleanup_interval_seconds
        self.rag_llm_enabled = self._env_bool("ARCLUME_RAG_LLM_ENABLED", False)
        self.rewrite_count = self._env_int("ARCLUME_RAG_REWRITE_COUNT", 3, minimum=1, maximum=5)
        self.max_candidate_results = self._env_int(
            "ARCLUME_RAG_MAX_CANDIDATES", 30, minimum=1, maximum=100
        )
        self.bm25_enabled = self._env_bool("ARCLUME_RAG_BM25_ENABLED", True)
        self.rrf_k = self._env_int("ARCLUME_RAG_RRF_K", 60, minimum=1, maximum=200)
        self.hybrid_retriever = hybrid_retriever or (
            HybridRetriever(knowledge_base, rrf_k=self.rrf_k)
            if knowledge_base is not None
            else None
        )
        self._cache: dict[str, tuple[float, ToolResult]] = {}
        self._stats: dict[str, ToolStats] = {}
        self._breakers: dict[str, CircuitBreaker] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a Tool and initialize its governance state."""

        super().register(tool)
        self._stats.setdefault(tool.name, ToolStats())
        self._breakers.setdefault(tool.name, CircuitBreaker())

    async def initialize_async(self) -> None:
        """Load the BM25 corpus from the current ChromaDB collection."""

        if self.hybrid_retriever is not None:
            await self.hybrid_retriever.initialize_async()

    async def refresh_hybrid_index(self) -> None:
        """Refresh BM25 after knowledge documents are added or replaced."""

        if self.hybrid_retriever is not None:
            await self.hybrid_retriever.refresh_async()

    async def execute(
        self,
        call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute one Tool with cache, breaker, fallback, and statistics."""

        tool = self.get(call.tool_name)
        if tool is None:
            return await super().execute(call, context)

        stats = self._stats.setdefault(tool.name, ToolStats())
        breaker = self._breakers.setdefault(tool.name, CircuitBreaker())
        stats.total += 1

        cached = self._get_cached(call, tool)
        if cached is not None:
            stats.cache_hits += 1
            stats.success += 1
            return cached.model_copy(
                update={
                    "call_id": call.call_id,
                    "cached": True,
                }
            )

        if not breaker.allow():
            stats.failed += 1
            return await self._fallback(
                call,
                tool,
                context,
                "Tool circuit is open; the dependency is temporarily unavailable.",
                stats,
            )

        started = time.perf_counter()
        result = await super().execute(call, context)
        duration_ms = (time.perf_counter() - started) * 1000
        stats.total_latency_ms += duration_ms

        if result.success:
            stats.success += 1
            stats.consecutive_failures = 0
            breaker.record_success()
            reranked = bool(
                result.reranked
                or (
                    tool.supports_rerank
                    and isinstance(result.data, dict)
                    and result.data.get("reranked")
                )
            )
            result = result.model_copy(
                update={"duration_ms": duration_ms, "reranked": reranked}
            )
            self._set_cached(call, tool, result)
            return result

        stats.failed += 1
        stats.consecutive_failures += 1
        breaker.record_failure()
        return await self._fallback(
            call,
            tool,
            context,
            result.error or "Tool execution failed.",
            stats,
            duration_ms=duration_ms,
        )

    async def _fallback(
        self,
        call: ToolCall,
        tool: ToolDefinition,
        context: dict[str, Any] | None,
        error: str,
        stats: ToolStats,
        *,
        duration_ms: float | None = None,
    ) -> ToolResult:
        """Return a safe fallback result without hiding the original failure."""

        if tool.fallback is None:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=error,
                duration_ms=duration_ms,
            )
        try:
            data = tool.fallback(call.arguments, context)
            if asyncio.iscoroutine(data):
                data = await data
            stats.fallback_count += 1
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=True,
                data=data,
                error=error,
                fallback_used=True,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            logger.warning("Tool fallback failed for %s: %s", tool.name, exc)
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=f"{error}; fallback failed: {exc}",
                duration_ms=duration_ms,
            )

    def stats_snapshot(self) -> dict[str, dict[str, float | int | str]]:
        """Return serializable Tool metrics for health checks and Monitor."""

        snapshot: dict[str, dict[str, float | int | str]] = {}
        for name, stats in self._stats.items():
            snapshot[name] = {
                "total": stats.total,
                "success": stats.success,
                "failed": stats.failed,
                "success_rate": round(stats.success_rate, 4),
                "avg_latency_ms": round(stats.average_latency_ms, 2),
                "average_latency_ms": round(stats.average_latency_ms, 2),
                "cache_hits": stats.cache_hits,
                "fallback_count": stats.fallback_count,
                "consecutive_fails": stats.consecutive_failures,
                "consecutive_failures": stats.consecutive_failures,
                "circuit_state": self._breakers[name].state.value,
            }
        return snapshot

    def get_stats(self) -> dict[str, dict[str, float | int | str]]:
        """Expose the Tool statistics using the Monitor-facing method name."""

        return self.stats_snapshot()

    async def search_with_rewrite(self, query: str, *, top_k: int = 5) -> dict[str, Any]:
        """Run the complete intent-gated RAG retrieval pipeline."""

        if self.knowledge_base is None:
            raise KnowledgeBaseError("KnowledgeBase is not configured")
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("Knowledge query cannot be empty")

        safe_top_k = max(1, min(int(top_k), 20))
        queries = await self.rewrite_query(cleaned_query)
        candidate_k = min(
            self.max_candidate_results,
            max(safe_top_k * 2, 6),
        )
        if self.hybrid_retriever is None:
            raise KnowledgeBaseError("Hybrid retriever is not configured")

        tasks = [
            self.hybrid_retriever.search_async(
                subquery,
                top_k=candidate_k,
                use_bm25=self.bm25_enabled,
            )
            for subquery in queries
        ]
        recalled = await asyncio.gather(*tasks, return_exceptions=True)
        successful_results: list[list[dict[str, Any]]] = []
        errors: list[Exception] = []
        dense_count = 0
        bm25_count = 0
        hybrid_degraded = False
        for result in recalled:
            if isinstance(result, Exception):
                errors.append(result)
            else:
                successful_results.append(result.results)
                dense_count += len(result.dense_results)
                bm25_count += len(result.bm25_results)
                hybrid_degraded = hybrid_degraded or result.degraded
        if not successful_results:
            if errors:
                raise KnowledgeBaseError("All knowledge retrieval branches failed") from errors[0]
            raise KnowledgeBaseError("Knowledge retrieval returned no branches")

        merged = self._deduplicate(successful_results)
        reranked, rerank_method = await self.rerank(cleaned_query, merged, safe_top_k)
        return {
            "query": cleaned_query,
            "queries": queries,
            "results": reranked,
            "reranked": bool(reranked),
            "rerank_method": rerank_method,
            "retrieval_mode": "hybrid" if self.bm25_enabled else "dense",
            "fusion_method": "rrf" if self.bm25_enabled else "none",
            "dense_count": dense_count,
            "bm25_count": bm25_count,
            "fused_count": len(merged),
            "degraded": bool(errors) or hybrid_degraded,
        }

    async def rewrite_query(self, query: str) -> list[str]:
        """Create bounded query variants with optional model rewriting."""

        if self.rag_llm_enabled and self.llm and self.llm.is_configured:
            prompt = (
                "Rewrite this customer-support search query into a JSON array of up to "
                f"{self.rewrite_count} concise search queries. Preserve product terms, "
                "error codes, dates, and identifiers. Return JSON only.\n"
                f"Query: {query}"
            )
            try:
                raw = await self.llm.chat(
                    prompt,
                    system_prompt="You create precise knowledge-base search queries.",
                )
                start, end = raw.find("["), raw.rfind("]")
                if start >= 0 and end > start:
                    values = json.loads(raw[start : end + 1])
                    if isinstance(values, list):
                        rewritten = [str(value).strip() for value in values if str(value).strip()]
                        if rewritten:
                            return self._unique_queries([query, *rewritten])[: self.rewrite_count]
            except Exception as exc:
                logger.warning("RAG query rewriting failed; using local variants: %s", exc)
        return self._local_query_variants(query)[: self.rewrite_count]

    async def rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
        top_k: int,
    ) -> tuple[list[dict[str, Any]], str]:
        """Rerank retrieved chunks locally, with optional model scoring."""

        if not items:
            return [], "none"
        local_items = self._local_rerank(query, items)
        if self.rag_llm_enabled and self.llm and self.llm.is_configured:
            model_items = await self._llm_rerank(query, local_items)
            if model_items is not None:
                return model_items[:top_k], "llm"
        return local_items[:top_k], "local_hybrid"

    async def _llm_rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Ask the configured model to score candidates when explicitly enabled."""

        candidates = [
            {"index": index, "title": item.get("title", ""), "content": str(item.get("content", ""))[:1200]}
            for index, item in enumerate(items)
        ]
        prompt = (
            "Score these knowledge chunks for the customer-support query. Return JSON "
            "only as an array of objects with index and score from 0 to 1. "
            f"Query: {query}\nChunks: {json.dumps(candidates, ensure_ascii=False)}"
        )
        try:
            raw = await self.llm.chat(
                prompt,
                system_prompt="You are a strict retrieval reranker. Do not invent facts.",
            )
            start, end = raw.find("["), raw.rfind("]")
            if start < 0 or end <= start:
                return None
            scores = json.loads(raw[start : end + 1])
            score_map = {
                int(entry["index"]): max(0.0, min(1.0, float(entry["score"])))
                for entry in scores
                if isinstance(entry, dict) and "index" in entry and "score" in entry
            }
            if not score_map:
                return None
            reranked = []
            for index, item in enumerate(items):
                copied = dict(item)
                copied["score"] = round(score_map.get(index, float(item.get("score") or 0.0)), 4)
                reranked.append(copied)
            return sorted(reranked, key=lambda item: float(item.get("score") or 0.0), reverse=True)
        except Exception as exc:
            logger.warning("RAG LLM reranking failed; using local ranking: %s", exc)
            return None

    @staticmethod
    def _deduplicate(branches: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        """Merge recall branches and retain the strongest copy of each chunk."""

        best: dict[str, dict[str, Any]] = {}
        for branch in branches:
            for item in branch:
                content = str(item.get("content", ""))
                key = str(item.get("chunk_id") or "")
                if not key:
                    key = str(item.get("source") or "") + ":" + str(item.get("chunk", ""))
                if key.endswith(":"):
                    key = hashlib.sha256(content.encode("utf-8")).hexdigest()
                score = float(item.get("score") or 0.0)
                if key not in best or score > float(best[key].get("score") or 0.0):
                    best[key] = dict(item)
        return list(best.values())

    @classmethod
    def _local_rerank(cls, query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Combine the fused retrieval score and lexical overlap for a cheap rerank."""

        query_tokens = cls._tokens(query)
        reranked: list[dict[str, Any]] = []
        for item in items:
            content_tokens = cls._tokens(str(item.get("content", "")))
            overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens))
            base_score = max(0.0, min(1.0, float(item.get("score") or 0.0)))
            copied = dict(item)
            copied["score"] = round(0.7 * base_score + 0.3 * overlap, 4)
            reranked.append(copied)
        return sorted(reranked, key=lambda item: float(item.get("score") or 0.0), reverse=True)

    @classmethod
    def _local_query_variants(cls, query: str) -> list[str]:
        """Build deterministic variants when model rewriting is disabled."""

        normalized = re.sub(r"[?!。！？,，]+", " ", query).strip()
        keyword_query = " ".join(sorted(cls._tokens(query))[:20])
        return cls._unique_queries([query, normalized, keyword_query])

    @staticmethod
    def _unique_queries(queries: list[str]) -> list[str]:
        unique: list[str] = []
        for query in queries:
            cleaned = query.strip()
            if cleaned and cleaned not in unique:
                unique.append(cleaned)
        return unique

    @staticmethod
    def _tokens(text: str) -> set[str]:
        """Extract simple English words and CJK characters for local overlap."""

        return set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower()))

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
        except (TypeError, ValueError):
            return default

    def _cache_key(self, call: ToolCall) -> str:
        """Create a stable cache key from the Tool name and arguments."""

        payload = json.dumps(
            {"tool": call.tool_name, "arguments": call.arguments},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get_cached(self, call: ToolCall, tool: ToolDefinition) -> ToolResult | None:
        """Return a live cached result when the Tool configured a TTL."""

        if tool.cache_ttl_seconds <= 0:
            return None
        entry = self._cache.get(self._cache_key(call))
        if entry is None:
            return None
        expires_at, result = entry
        if expires_at <= time.monotonic():
            self._cache.pop(self._cache_key(call), None)
            return None
        return result

    def _set_cached(self, call: ToolCall, tool: ToolDefinition, result: ToolResult) -> None:
        """Store only successful, non-fallback results with a positive TTL."""

        if tool.cache_ttl_seconds <= 0 or not result.success or result.fallback_used:
            return
        self._cache[self._cache_key(call)] = (
            time.monotonic() + tool.cache_ttl_seconds,
            result.model_copy(update={"call_id": call.call_id}),
        )
