"""Focused tests for local Intent feedback and cache diagnostics."""

import unittest

from core.intent_recognizer import IntentCategory, IntentRecognizer


class IntentRecognizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_specific_refund_topic_beats_generic_question_words(self) -> None:
        recognizer = IntentRecognizer()
        for message in (
            "What is your refund policy?",
            "How long does a refund take?",
            "Please explain the refund policy.",
        ):
            with self.subTest(message=message):
                result = await recognizer.recognize(message)
                self.assertEqual(result.intent, IntentCategory.REFUND)
                self.assertEqual(result.information_need, "knowledge")
                self.assertTrue(result.should_use_rag)
                self.assertIn("refund", result.topic_evidence)
                self.assertFalse(result.ambiguity_reasons)

    async def test_separate_billing_and_login_issues_keep_both_domains(self) -> None:
        result = await IntentRecognizer().recognize(
            "I cannot log in and I was charged twice."
        )
        self.assertEqual(result.supporting_domains, ["billing", "technical"])
        self.assertEqual(result.information_need, "mixed")
        self.assertTrue(result.should_use_rag)
        self.assertFalse(result.ambiguity_reasons)
        queries = {task.domain: task.query for task in result.subtasks}
        self.assertEqual(queries["technical"], "I cannot log in")
        self.assertEqual(queries["billing"], "I was charged twice.")

    async def test_compound_policy_and_product_questions_are_scoped_by_domain(self) -> None:
        result = await IntentRecognizer().recognize(
            "how long does it take for the shipping? and can u introduce the mini desk lamp? "
            "and how can i get the refund?"
        )

        tasks = {task.domain: task for task in result.subtasks}
        self.assertEqual(set(tasks), {"general", "billing"})
        self.assertIn("shipping", tasks["general"].query)
        self.assertIn("mini desk lamp", tasks["general"].query)
        self.assertNotIn("refund", tasks["general"].query)
        self.assertEqual(tasks["billing"].query, "how can i get the refund?")
        self.assertEqual(tasks["general"].information_need, "knowledge")
        self.assertEqual(tasks["billing"].information_need, "knowledge")
        self.assertTrue(tasks["general"].should_use_rag)
        self.assertTrue(tasks["billing"].should_use_rag)

    async def test_ambiguous_return_word_does_not_route_to_billing(self) -> None:
        result = await IntentRecognizer().recognize(
            "How do I return to the login page?"
        )
        self.assertEqual(result.intent, IntentCategory.QUERY)
        self.assertIn("weak_or_ambiguous_keyword", result.ambiguity_reasons)
        self.assertEqual(result.supporting_domains, [])

    async def test_shopping_word_does_not_match_hi_greeting(self) -> None:
        result = await IntentRecognizer().recognize("Tell me about shipping.")
        self.assertNotEqual(result.intent, IntentCategory.GREETING)

    async def test_product_introduction_uses_general_knowledge_path(self) -> None:
        result = await IntentRecognizer().recognize(
            "Can u introduce the Mini Desk Lamp?"
        )
        self.assertEqual(result.intent, IntentCategory.QUERY)
        self.assertEqual(result.subtasks[0].domain, "general")
        self.assertEqual(result.information_need, "knowledge")
        self.assertTrue(result.should_use_rag)

    async def test_order_with_id_plans_read_only_lookup_not_rag(self) -> None:
        result = await IntentRecognizer().recognize("Where is my order #AB1234?")
        self.assertEqual(result.intent, IntentCategory.ORDER_STATUS)
        self.assertEqual(result.information_need, "live_data")
        self.assertEqual(result.planned_tool_name, "order_query")
        self.assertFalse(result.should_use_rag)

    async def test_exact_learned_template_recovers_topic_without_keywords(self) -> None:
        recognizer = IntentRecognizer()
        recognizer.learn("amber parcel adjustment", IntentCategory.REFUND)
        result = await recognizer.recognize("amber parcel adjustment")
        self.assertEqual(result.intent, IntentCategory.REFUND)
        self.assertGreaterEqual(result.source_scores["template"], 0.75)

    async def test_llm_review_is_only_used_for_unclear_local_evidence(self) -> None:
        class ClassifierLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def chat(self, message, **kwargs):
                self.calls += 1
                return '{"intent":"technical_login","confidence":0.9}'

        llm = ClassifierLLM()
        recognizer = IntentRecognizer(llm=llm, use_llm=True)
        await recognizer.recognize("What is your refund policy?")
        self.assertEqual(llm.calls, 0)
        result = await recognizer.recognize("How do I return to the login page?")
        self.assertEqual(llm.calls, 1)
        self.assertEqual(result.intent, IntentCategory.TECHNICAL_LOGIN)

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
