"""Focused tests for local Intent feedback and cache diagnostics."""

import unittest

from core.intent_recognizer import IntentCategory, IntentRecognizer


class IntentRecognizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_human_feedback_is_added_to_local_templates(self) -> None:
        recognizer = IntentRecognizer()
        recognizer.learn("please use my custom refund wording", IntentCategory.REFUND)

        result = await recognizer.recognize("please use my custom refund wording")

        self.assertEqual(result.intent, IntentCategory.REFUND)
        self.assertEqual(recognizer.cache_stats()["learned_examples"], 1)

    async def test_cache_stats_count_hits_and_misses(self) -> None:
        recognizer = IntentRecognizer()

        await recognizer.recognize("hello")
        await recognizer.recognize("hello")

        stats = recognizer.cache_stats()
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hits"], 1)


if __name__ == "__main__":
    unittest.main()
