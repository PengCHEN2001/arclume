"""Offline Evaluation helpers for Intent, routing, retrieval, and regression checks."""

from evaluation.judge import LLMJudge, JudgeError
from evaluation.evaluator import (
    DEFAULT_DIALOG_CASES,
    DEFAULT_INTENT_CASES,
    EndToEndEvaluator,
    EvalReport,
    EvalResult,
    IntentEvaluator,
    IntentTestCase,
    QualityScores,
)
from evaluation.metrics import (
    classification_details,
    classification_metrics,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    retrieval_metrics,
)
from evaluation.models import (
    EvaluationDataset,
    EvaluationReport,
    IntentCase,
    RegressionIssue,
    RegressionReport,
    RetrievalCase,
)
from evaluation.regression import compare_reports
from evaluation.runner import evaluate_intent_cases, evaluate_retrieval_cases

__all__ = [
    "EvaluationDataset",
    "EvaluationReport",
    "IntentCase",
    "RetrievalCase",
    "RegressionIssue",
    "RegressionReport",
    "LLMJudge",
    "JudgeError",
    "EndToEndEvaluator",
    "IntentEvaluator",
    "EvalReport",
    "EvalResult",
    "IntentTestCase",
    "QualityScores",
    "DEFAULT_INTENT_CASES",
    "DEFAULT_DIALOG_CASES",
    "classification_metrics",
    "classification_details",
    "recall_at_k",
    "reciprocal_rank",
    "ndcg_at_k",
    "retrieval_metrics",
    "evaluate_intent_cases",
    "evaluate_retrieval_cases",
    "compare_reports",
]
