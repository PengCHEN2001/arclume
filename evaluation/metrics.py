"""Dependency-free metrics for classification and ranked retrieval."""

from __future__ import annotations

import math
from typing import Any, Collection, Iterable, Sequence


def classification_accuracy(
    expected: Sequence[str],
    predicted: Sequence[str],
) -> float:
    """Return exact-match accuracy for equally sized label sequences."""

    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted labels must have equal length")
    if not expected:
        return 0.0
    return sum(left == right for left, right in zip(expected, predicted)) / len(expected)


def macro_f1(
    expected: Sequence[str],
    predicted: Sequence[str],
    *,
    labels: Iterable[str] | None = None,
) -> float:
    """Return unweighted F1 averaged across the observed or supplied labels."""

    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted labels must have equal length")
    label_set = set(labels or ()) | set(expected) | set(predicted)
    if not label_set:
        return 0.0

    scores: list[float] = []
    for label in sorted(label_set):
        true_positive = sum(
            actual == label and guess == label
            for actual, guess in zip(expected, predicted)
        )
        false_positive = sum(
            actual != label and guess == label
            for actual, guess in zip(expected, predicted)
        )
        false_negative = sum(
            actual == label and guess != label
            for actual, guess in zip(expected, predicted)
        )
        precision = true_positive / (true_positive + false_positive) if (
            true_positive + false_positive
        ) else 0.0
        recall = true_positive / (true_positive + false_negative) if (
            true_positive + false_negative
        ) else 0.0
        scores.append(
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
    return sum(scores) / len(scores)


def classification_metrics(
    expected: Sequence[str],
    predicted: Sequence[str],
    *,
    labels: Iterable[str] | None = None,
) -> dict[str, float]:
    """Return the core intent metrics used by the Evaluation report."""

    return {
        "accuracy": classification_accuracy(expected, predicted),
        "macro_f1": macro_f1(expected, predicted, labels=labels),
    }


def classification_details(
    expected: Sequence[str],
    predicted: Sequence[str],
    *,
    labels: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return aggregate metrics and per-class precision/recall/F1."""

    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted labels must have equal length")
    label_set = set(labels or ()) | set(expected) | set(predicted)
    per_class: dict[str, dict[str, float]] = {}
    for label in sorted(label_set):
        true_positive = sum(
            actual == label and guess == label
            for actual, guess in zip(expected, predicted)
        )
        false_positive = sum(
            actual != label and guess == label
            for actual, guess in zip(expected, predicted)
        )
        false_negative = sum(
            actual == label and guess != label
            for actual, guess in zip(expected, predicted)
        )
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        **classification_metrics(expected, predicted, labels=label_set),
        "per_class": per_class,
    }


def _unique_ranked(items: Sequence[str]) -> list[str]:
    """Keep the first occurrence because rank is meaningful for retrieval."""

    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def recall_at_k(
    retrieved: Sequence[str],
    relevant: Collection[str],
    k: int,
) -> float:
    """Return the fraction of relevant items found in the first k results."""

    relevant_set = {str(item) for item in relevant}
    if not relevant_set:
        return 0.0
    selected = set(_unique_ranked(retrieved)[: max(0, k)])
    return len(selected & relevant_set) / len(relevant_set)


def precision_at_k(
    retrieved: Sequence[str],
    relevant: Collection[str],
    k: int,
) -> float:
    """Return the fraction of the first k results that are relevant."""

    safe_k = max(0, k)
    if safe_k == 0:
        return 0.0
    selected = _unique_ranked(retrieved)[:safe_k]
    if not selected:
        return 0.0
    relevant_set = {str(item) for item in relevant}
    return sum(item in relevant_set for item in selected) / safe_k


def reciprocal_rank(
    retrieved: Sequence[str],
    relevant: Collection[str],
    *,
    k: int | None = None,
) -> float:
    """Return reciprocal rank of the first relevant result, or zero."""

    relevant_set = {str(item) for item in relevant}
    ranked = _unique_ranked(retrieved)
    if k is not None:
        ranked = ranked[: max(0, k)]
    for index, item in enumerate(ranked, start=1):
        if item in relevant_set:
            return 1.0 / index
    return 0.0


def ndcg_at_k(
    retrieved: Sequence[str],
    relevant: Collection[str],
    k: int,
) -> float:
    """Return binary-relevance NDCG@K for one ranked result list."""

    relevant_set = {str(item) for item in relevant}
    safe_k = max(0, k)
    if not relevant_set or safe_k == 0:
        return 0.0

    ranked = _unique_ranked(retrieved)[:safe_k]
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, item in enumerate(ranked)
        if item in relevant_set
    )
    ideal_hits = min(len(relevant_set), safe_k)
    ideal_dcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def retrieval_metrics(
    cases: Iterable[tuple[Sequence[str], Collection[str], int]],
) -> dict[str, float]:
    """Aggregate Recall@K, Precision@K, MRR, and NDCG over labeled cases."""

    values = list(cases)
    if not values:
        return {
            "recall_at_k": 0.0,
            "precision_at_k": 0.0,
            "mrr": 0.0,
            "ndcg_at_k": 0.0,
        }

    recall_values = [recall_at_k(*value) for value in values]
    precision_values = [precision_at_k(*value) for value in values]
    reciprocal_values = [
        reciprocal_rank(retrieved, relevant, k=k)
        for retrieved, relevant, k in values
    ]
    ndcg_values = [ndcg_at_k(*value) for value in values]
    return {
        "recall_at_k": sum(recall_values) / len(values),
        "precision_at_k": sum(precision_values) / len(values),
        "mrr": sum(reciprocal_values) / len(values),
        "ndcg_at_k": sum(ndcg_values) / len(values),
    }
