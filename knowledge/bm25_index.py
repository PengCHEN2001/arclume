"""Small dependency-free BM25 index for customer-support document chunks."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable


class BM25Index:
    """Build and query an in-process BM25 index over indexed knowledge chunks."""

    TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 < 0:
            raise ValueError("BM25 k1 must be non-negative")
        if not 0 <= b <= 1:
            raise ValueError("BM25 b must be between zero and one")

        self.k1 = k1                         # Term-frequency saturation factor
        self.b = b                           # Document-length normalization factor
        self._documents: dict[str, dict[str, Any]] = {}
        self._term_frequencies: dict[str, Counter[str]] = {}
        self._document_frequency: Counter[str] = Counter()
        self._average_document_length = 0.0

    @property
    def document_count(self) -> int:
        """Return the number of indexed chunks."""

        return len(self._documents)

    def replace(self, documents: Iterable[dict[str, Any]]) -> None:
        """Replace the complete lexical corpus with the supplied chunks."""

        self._documents.clear()
        for document in documents:
            normalized = self._normalize_document(document)
            self._documents[normalized["chunk_id"]] = normalized
        self._rebuild_statistics()

    def upsert(self, documents: Iterable[dict[str, Any]]) -> None:
        """Insert or replace chunks and rebuild compact corpus statistics."""

        for document in documents:
            normalized = self._normalize_document(document)
            self._documents[normalized["chunk_id"]] = normalized
        self._rebuild_statistics()

    def clear(self) -> None:
        """Remove all lexical documents and statistics."""

        self._documents.clear()
        self._rebuild_statistics()

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        """Return the highest-scoring lexical matches with normalized scores."""

        tokens = self.tokenize(query)
        if not tokens or not self._documents:
            return []

        safe_top_k = max(1, min(int(top_k), 100))
        query_terms = Counter(tokens)
        document_count = len(self._documents)
        scored: list[tuple[float, str]] = []
        for chunk_id, frequencies in self._term_frequencies.items():
            score = 0.0
            document_length = sum(frequencies.values())
            for term, query_frequency in query_terms.items():
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                document_frequency = self._document_frequency[term]
                inverse_document_frequency = math.log(
                    1.0
                    + (document_count - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                denominator = term_frequency + self.k1 * (
                    1.0
                    - self.b
                    + self.b * document_length / max(1.0, self._average_document_length)
                )
                score += (
                    inverse_document_frequency
                    * (term_frequency * (self.k1 + 1.0) / denominator)
                    * min(query_frequency, 3)
                )
            if score > 0:
                scored.append((score, chunk_id))

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = scored[:safe_top_k]
        maximum_score = selected[0][0] if selected else 0.0
        results: list[dict[str, Any]] = []
        for raw_score, chunk_id in selected:
            item = dict(self._documents[chunk_id])
            item["bm25_score"] = round(raw_score, 6)
            item["score"] = round(raw_score / maximum_score, 4) if maximum_score else 0.0
            item["retrieval"] = "bm25"
            results.append(item)
        return results

    @classmethod
    def tokenize(cls, text: str) -> list[str]:
        """Tokenize English words and individual CJK characters deterministically."""

        return cls.TOKEN_PATTERN.findall(str(text).lower())

    def _rebuild_statistics(self) -> None:
        """Recalculate document frequencies after corpus changes."""

        self._term_frequencies = {}
        self._document_frequency = Counter()
        total_length = 0
        for chunk_id, document in self._documents.items():
            terms = self.tokenize(
                f"{document.get('title', '')} {document.get('content', '')}"
            )
            frequencies = Counter(terms)
            self._term_frequencies[chunk_id] = frequencies
            self._document_frequency.update(frequencies.keys())
            total_length += sum(frequencies.values())
        self._average_document_length = total_length / max(1, len(self._documents))

    @staticmethod
    def _normalize_document(document: dict[str, Any]) -> dict[str, Any]:
        """Normalize a knowledge chunk while preserving display metadata."""

        content = str(document.get("content") or "").strip()
        if not content:
            raise ValueError("BM25 documents must contain content")
        chunk_id = str(
            document.get("chunk_id")
            or document.get("id")
            or f"{document.get('source', '')}:{document.get('chunk', '')}:{content}"
        )
        return {
            "chunk_id": chunk_id,
            "title": str(document.get("title") or ""),
            "source": str(document.get("source") or ""),
            "content": content,
            "chunk": document.get("chunk", 0),
            "total_chunks": document.get("total_chunks", 1),
        }
