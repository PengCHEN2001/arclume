"""Hybrid dense and lexical retrieval with Reciprocal Rank Fusion."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from knowledge import KnowledgeBaseError
from knowledge.bm25_index import BM25Index
from knowledge.knowledge_base import KnowledgeBase


logger = logging.getLogger(__name__)


@dataclass
class HybridSearchResult:
    """One query's dense, lexical, and fused retrieval results."""

    results: list[dict[str, Any]]
    dense_results: list[dict[str, Any]]
    bm25_results: list[dict[str, Any]]
    degraded: bool = False


class HybridRetriever:
    """Run ChromaDB and BM25 against the same knowledge chunk corpus."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        *,
        bm25_index: BM25Index | None = None,
        rrf_k: int = 60,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("RRF k must be at least one")
        self.knowledge_base = knowledge_base       # Dense retrieval adapter
        self.bm25 = bm25_index or BM25Index()      # In-process lexical index
        self.rrf_k = rrf_k                         # RRF rank-smoothing constant
        self._initialized = False                 # Whether the lexical corpus is loaded
        self._loaded_revision: int | None = None  # KnowledgeBase revision at last refresh
        self._refresh_lock = asyncio.Lock()        # Prevent concurrent index rebuilds

    @property
    def document_count(self) -> int:
        """Return the number of chunks currently available to BM25."""

        return self.bm25.document_count

    @property
    def initialized(self) -> bool:
        """Return whether the lexical index has completed its first load."""

        return self._initialized

    async def initialize_async(self) -> None:
        """Load the current ChromaDB chunk corpus into BM25."""

        await self.refresh_async()

    async def refresh_async(self) -> None:
        """Rebuild BM25 from the same chunks stored in the dense collection."""

        async with self._refresh_lock:
            loader = getattr(self.knowledge_base, "get_indexed_chunks_async", None)
            if not callable(loader):
                # Small test doubles may only implement dense search.
                self._initialized = True
                return
            documents = await loader()
            await asyncio.to_thread(self.bm25.replace, documents)
            self._loaded_revision = getattr(self.knowledge_base, "revision", None)
            self._initialized = True
            logger.info("BM25 index loaded with %s knowledge chunks", len(documents))

    async def search_async(
        self,
        query: str,
        *,
        top_k: int = 10,
        use_bm25: bool = True,
    ) -> HybridSearchResult:
        """Retrieve dense and lexical candidates concurrently, then fuse ranks."""

        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("Hybrid retrieval query cannot be empty")

        index_error: Exception | None = None
        try:
            await self._ensure_current_index()
        except Exception as exc:
            # A lexical-index refresh must not block the dense retrieval branch.
            index_error = exc
            logger.warning("BM25 index refresh failed; using available branches: %s", exc)
        safe_top_k = max(1, min(int(top_k), 100))
        dense_task = self.knowledge_base.search_async(cleaned_query, safe_top_k)
        tasks: list[Any] = [dense_task]
        if use_bm25:
            tasks.append(asyncio.to_thread(self.bm25.search, cleaned_query, top_k=safe_top_k))
        branches = await asyncio.gather(*tasks, return_exceptions=True)

        dense_results: list[dict[str, Any]] = []
        bm25_results: list[dict[str, Any]] = []
        errors: list[Exception] = []
        if isinstance(branches[0], Exception):
            errors.append(branches[0])
        else:
            dense_results = list(branches[0])
        if use_bm25 and len(branches) > 1:
            if isinstance(branches[1], Exception):
                errors.append(branches[1])
            else:
                bm25_results = list(branches[1])

        if not dense_results and not bm25_results and errors:
            raise KnowledgeBaseError("All hybrid retrieval branches failed") from errors[0]

        return HybridSearchResult(
            results=self._rrf_fuse(dense_results, bm25_results, top_k=safe_top_k),
            dense_results=dense_results,
            bm25_results=bm25_results,
            degraded=bool(errors) or index_error is not None,
        )

    async def _ensure_current_index(self) -> None:
        """Load or refresh BM25 when the Chroma corpus changes."""

        current_revision = getattr(self.knowledge_base, "revision", None)
        if not self._initialized or (
            current_revision is not None and current_revision != self._loaded_revision
        ):
            await self.refresh_async()

    def _rrf_fuse(
        self,
        dense_results: list[dict[str, Any]],
        bm25_results: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Fuse ranked branches with equal Reciprocal Rank Fusion weight."""

        fused: dict[str, dict[str, Any]] = {}
        for branch_name, branch in (
            ("dense", dense_results),
            ("bm25", bm25_results),
        ):
            for rank, item in enumerate(branch, start=1):
                key = self._chunk_key(item)
                current = fused.setdefault(
                    key,
                    {
                        **item,
                        "retrieval_methods": [],
                        "rrf_score": 0.0,
                    },
                )
                current["rrf_score"] += 1.0 / (self.rrf_k + rank)
                if branch_name not in current["retrieval_methods"]:
                    current["retrieval_methods"].append(branch_name)
                current[f"{branch_name}_score"] = item.get("score")

        ordered = sorted(
            fused.values(),
            key=lambda item: (-float(item["rrf_score"]), self._chunk_key(item)),
        )[:top_k]
        maximum_score = float(ordered[0]["rrf_score"]) if ordered else 0.0
        for item in ordered:
            item["rrf_score"] = round(float(item["rrf_score"]), 6)
            item["score"] = round(
                float(item["rrf_score"]) / maximum_score,
                4,
            ) if maximum_score else 0.0
            item["retrieval"] = (
                "hybrid" if len(item["retrieval_methods"]) > 1 else item["retrieval_methods"][0]
            )
        return ordered

    @staticmethod
    def _chunk_key(item: dict[str, Any]) -> str:
        """Use a stable chunk ID, with a content hash as a final fallback."""

        chunk_id = item.get("chunk_id") or item.get("id")
        if chunk_id:
            return str(chunk_id)
        source = str(item.get("source") or "")
        chunk = str(item.get("chunk") or "")
        if source or chunk:
            return f"{source}:{chunk}"
        return hashlib.sha256(str(item.get("content") or "").encode("utf-8")).hexdigest()
