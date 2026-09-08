"""Tests for dependency-free Evaluation metrics and regression checks."""

import unittest

from evaluation.judge import JudgeError, LLMJudge
from evaluation.metrics import (
    classification_details,
    classification_metrics,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    retrieval_metrics,
)
from evaluation.models import EvaluationReport, IntentCase, RetrievalCase
from evaluation.regression import compare_reports
from evaluation.runner import evaluate_intent_cases, evaluate_retrieval_cases
from evaluation.evaluator import EndToEndEvaluator, IntentEvaluator, IntentTestCase


class EvaluationMetricTests(unittest.TestCase):
    def test_classification_metrics(self) -> None:
        metrics = classification_metrics(
            ["refund", "technical", "refund"],
            ["refund", "refund", "refund"],
        )

        self.assertAlmostEqual(metrics["accuracy"], 2 / 3)
        self.assertLess(metrics["macro_f1"], 1.0)

    def test_classification_details_include_per_class_precision_recall_f1(self) -> None:
        details = classification_details(
            ["refund", "technical", "refund"],
            ["refund", "refund", "refund"],
        )

        self.assertIn("per_class", details)
        self.assertEqual(details["per_class"]["refund"]["precision"], 2 / 3)
        self.assertEqual(details["per_class"]["technical"]["recall"], 0.0)

    def test_ranked_retrieval_metrics(self) -> None:
        retrieved = ["wrong", "relevant", "other"]
        relevant = {"relevant"}

        self.assertEqual(recall_at_k(retrieved, relevant, 2), 1.0)
        self.assertEqual(reciprocal_rank(retrieved, relevant), 0.5)
        self.assertAlmostEqual(ndcg_at_k(retrieved, relevant, 2), 1 / 1.5849625)
        metrics = retrieval_metrics([(retrieved, relevant, 2)])
        self.assertEqual(metrics["mrr"], 0.5)

    def test_regression_report_detects_drop(self) -> None:
        baseline = EvaluationReport("baseline", {"mrr": 0.8, "accuracy": 0.9})
        current = EvaluationReport("current", {"mrr": 0.6, "accuracy": 0.9})

        comparison = compare_reports(baseline, current)

        self.assertFalse(comparison.passed)
        self.assertEqual(comparison.regressions[0].metric, "mrr")


class EvaluationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_intent_runner_accepts_model_like_result(self) -> None:
        class Result:
            def __init__(self, intent: str) -> None:
                self.intent = intent

        async def recognize(message: str) -> Result:
            return Result("refund" if "refund" in message else "technical")

        report = await evaluate_intent_cases(
            [
                IntentCase("one", "refund please", "refund", "billing"),
                IntentCase("two", "app crashed", "technical", "technical"),
            ],
            recognize,
            route=lambda result: "billing" if result.intent == "refund" else "technical",
        )

        self.assertEqual(report.metrics["intent_accuracy"], 1.0)
        self.assertEqual(report.metrics["route_accuracy"], 1.0)
        self.assertEqual(report.failures, [])

    async def test_retrieval_runner_reads_result_payload(self) -> None:
        async def search(query: str, *, top_k: int) -> dict[str, object]:
            return {
                "results": [
                    {"chunk_id": "chunk-a"},
                    {"chunk_id": "chunk-b"},
                ]
            }

        report = await evaluate_retrieval_cases(
            [RetrievalCase("one", "refund", ("chunk-b",), top_k=2)],
            search,
        )

        self.assertEqual(report.metrics["recall_at_k"], 1.0)
        self.assertEqual(report.metrics["mrr"], 0.5)


class JudgeTests(unittest.TestCase):
    def test_judge_parses_and_bounds_scores(self) -> None:
        result = LLMJudge.parse(
            '{"relevance": 1.2, "correctness": 0.8, '
            '"completeness": -1, "helpfulness": 0.7, "rationale": "ok"}'
        )

        self.assertEqual(result.relevance, 1.0)
        self.assertEqual(result.completeness, 0.0)
        self.assertEqual(result.accuracy, 0.8)

    def test_judge_defaults_missing_score(self) -> None:
        result = LLMJudge.parse('{"relevance": 1.0}')

        self.assertEqual(result.relevance, 1.0)
        self.assertEqual(result.accuracy, 0.5)

    def test_judge_rejects_invalid_json(self) -> None:
        with self.assertRaises(JudgeError):
            LLMJudge.parse("not-json")


class EndToEndEvaluatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_end_to_end_report_runs_intent_and_dialog_cases(self) -> None:
        from types import SimpleNamespace

        class FakeRecognizer:
            async def recognize(self, message: str) -> SimpleNamespace:
                return SimpleNamespace(
                    intent="refund",
                    confidence=0.9,
                    reasoning="matched refund",
                )

        class FakeOrchestrator:
            async def run(self, message: str, **kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(
                    response="Please follow the refund steps.",
                    primary_agent="billing",
                    intent=SimpleNamespace(intent="refund"),
                )

        class FakeJudge:
            async def judge(self, *args: object, **kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(
                    relevance=1.0,
                    accuracy=1.0,
                    completeness=1.0,
                    helpfulness=1.0,
                )

        evaluator = EndToEndEvaluator(
            orchestrator=FakeOrchestrator(),
            recognizer=FakeRecognizer(),
            judge=FakeJudge(),
        )
        report = await evaluator.run(
            intent_cases=[IntentTestCase("refund", "refund")],
            dialog_cases=[{"question": "How do I get a refund?"}],
        )

        self.assertEqual(report.total, 2)
        self.assertEqual(report.passed, 2)
        self.assertEqual(report.pass_rate, 1.0)
        self.assertEqual(report.avg_scores["intent_accuracy"], 1.0)
        self.assertEqual(report.avg_scores["accuracy"], 1.0)

    async def test_intent_evaluator_is_available_as_a_standalone_component(self) -> None:
        from types import SimpleNamespace

        class FakeRecognizer:
            async def recognize(self, message: str) -> SimpleNamespace:
                return SimpleNamespace(intent="refund" if "refund" in message else "technical")

        report = await IntentEvaluator(FakeRecognizer()).evaluate(
            [
                IntentTestCase("refund please", "refund"),
                IntentTestCase("the app crashed", "technical"),
            ]
        )

        self.assertEqual(report["accuracy"], 1.0)
        self.assertEqual(report["correct"], 2)


if __name__ == "__main__":
    unittest.main()
