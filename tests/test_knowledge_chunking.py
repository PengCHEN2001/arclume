"""English knowledge-document chunk boundaries and overlap."""

import unittest

from knowledge.knowledge_base import KnowledgeBase


class KnowledgeChunkingTests(unittest.TestCase):
    def test_preserves_paragraphs_and_heading_context(self) -> None:
        base = KnowledgeBase(chunk_size=100, chunk_overlap=12, collection=object())
        first = "Refunds are reviewed by the billing team within three working days."
        second = "Approved refunds are returned to the original payment method."
        third = "Login errors should be checked against the account status first."
        chunks = base._chunk_text(
            f"# Help\n\n## Refunds\n\n{first}\n\n{second}\n\n## Login\n\n{third}"
        )

        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))
        self.assertTrue(any(first in chunk for chunk in chunks))
        self.assertTrue(any(second in chunk for chunk in chunks))
        self.assertTrue(any(third in chunk for chunk in chunks))
        self.assertTrue(all("Refunds" not in chunk for chunk in chunks if "## Login" in chunk))
        self.assertTrue(all("## Refunds" in chunk for chunk in chunks if first in chunk))

    def test_oversized_english_paragraph_splits_and_overlaps(self) -> None:
        base = KnowledgeBase(chunk_size=90, chunk_overlap=15, collection=object())
        chunks = base._chunk_text(
            "## Shipping\n\n" + "Orders ship after payment confirmation. " * 5
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 90 for chunk in chunks))
        self.assertTrue(all(chunk.startswith("## Shipping") for chunk in chunks))
        self.assertTrue(any("\n\nconfirmation.\n\nOrders" in chunk for chunk in chunks[1:]))

    def test_invalid_overlap_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            KnowledgeBase(chunk_size=50, chunk_overlap=50, collection=object())


if __name__ == "__main__":
    unittest.main()
