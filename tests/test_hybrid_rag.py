"""Focused tests for BM25, dense retrieval, and RRF fusion."""

import unittest

from knowledge.bm25_index import BM25Index
from knowledge.hybrid_retriever import HybridRetriever
from tools.tool_manager import ToolManager


DOCUMENTS = [
    {
        "chunk_id": "chunk-refund",
        "title": "Refund Policy",
        "source": "refund_policy.md",
        "content": "Approved refunds return to the original payment method within five business days.",
        "chunk": 0,
        "total_chunks": 1,
    },
    {
        "chunk_id": "chunk-shipping",
        "title": "Shipping Policy",
        "source": "shipping_policy.md",
        "content": "Shipping delays should be checked with the tracking number and delivery status.",
        "chunk": 0,
        "total_chunks": 1,
    },
]


class FakeKnowledgeBase:
    """Dense retrieval substitute exposing the KnowledgeBase contract."""

    revision = 1

    async def get_indexed_chunks_async(self) -> list[dict[str, object]]:
        return list(DOCUMENTS)

    async def search_async(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
        if "refund" in query.lower() or "payment" in query.lower():
            return [dict(DOCUMENTS[0], score=0.92)][:top_k]
        return [dict(DOCUMENTS[1], score=0.91)][:top_k]


class UnavailableLexicalIndexKnowledgeBase(FakeKnowledgeBase):
    """Dense retrieval substitute whose full-corpus read is unavailable."""

    async def get_indexed_chunks_async(self) -> list[dict[str, object]]:
        raise RuntimeError("lexical corpus unavailable")


class HybridRAGTests(unittest.IsolatedAsyncioTestCase):
    """Verify the first hybrid retrieval implementation."""

    def test_bm25_returns_lexical_match(self) -> None:
        index = BM25Index()
        index.replace(DOCUMENTS)

        results = index.search("refund payment", top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["chunk_id"], "chunk-refund")
        self.assertEqual(results[0]["retrieval"], "bm25")
        self.assertGreater(results[0]["bm25_score"], 0)

    async def test_hybrid_retriever_fuses_dense_and_bm25(self) -> None:
        retriever = HybridRetriever(FakeKnowledgeBase())
        await retriever.initialize_async()

        result = await retriever.search_async("refund payment", top_k=2)

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0]["retrieval"], "hybrid")
        self.assertEqual(
            set(result.results[0]["retrieval_methods"]),
            {"dense", "bm25"},
        )
        self.assertEqual(len(result.dense_results), 1)
        self.assertEqual(len(result.bm25_results), 1)
        self.assertFalse(result.degraded)

    async def test_tool_manager_exposes_hybrid_retrieval_metadata(self) -> None:
        manager = ToolManager(knowledge_base=FakeKnowledgeBase())
        await manager.initialize_async()

        result = await manager.search_with_rewrite("refund payment", top_k=1)

        self.assertEqual(result["retrieval_mode"], "hybrid")
        self.assertEqual(result["fusion_method"], "rrf")
        self.assertGreater(result["dense_count"], 0)
        self.assertGreater(result["bm25_count"], 0)
        self.assertGreater(result["fused_count"], 0)
        self.assertTrue(result["results"])

    async def test_dense_branch_survives_bm25_refresh_failure(self) -> None:
        retriever = HybridRetriever(UnavailableLexicalIndexKnowledgeBase())

        result = await retriever.search_async("refund payment", top_k=1)

        self.assertTrue(result.dense_results)
        self.assertFalse(result.bm25_results)
        self.assertTrue(result.degraded)


if __name__ == "__main__":
    unittest.main()
