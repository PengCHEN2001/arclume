"""Baseline comparison and regression detection for Evaluation reports."""

from __future__ import annotations

from typing import Mapping

from evaluation.models import EvaluationReport, RegressionIssue, RegressionReport


DEFAULT_TOLERANCES: dict[str, float] = {
    "intent_accuracy": 0.05,
    "intent_macro_f1": 0.05,
    "route_accuracy": 0.05,
    "route_macro_f1": 0.05,
    "recall_at_k": 0.05,
    "precision_at_k": 0.05,
    "mrr": 0.05,
    "ndcg_at_k": 0.05,
}
DEFAULT_RELATIVE_TOLERANCE = 0.05


def compare_reports(
    baseline: EvaluationReport,
    current: EvaluationReport,
    *,
    tolerances: Mapping[str, float] | None = None,
) -> RegressionReport:
    """Fail when a shared metric drops by more than 5 percent by default."""

    allowed = dict(DEFAULT_TOLERANCES)
    allowed.update(tolerances or {})
    result = RegressionReport(
        baseline_name=baseline.name,
        current_name=current.name,
    )

    # Only metrics already present in the baseline are required for a
    # regression comparison. New metrics in the current report are allowed so
    # the evaluation suite can grow without making every old baseline invalid.
    for metric in sorted(baseline.metrics):
        if metric not in current.metrics:
            result.missing_metrics.append(metric)
            continue
        baseline_value = float(baseline.metrics[metric])
        current_value = float(current.metrics[metric])
        delta = current_value - baseline_value
        tolerance = max(
            0.0,
            float(allowed.get(metric, DEFAULT_RELATIVE_TOLERANCE)),
        )
        relative_delta = (
            delta / abs(baseline_value)
            if baseline_value != 0.0
            else (0.0 if delta == 0.0 else 1.0)
        )
        if relative_delta < -tolerance:
            result.regressions.append(
                RegressionIssue(
                    metric=metric,
                    baseline=baseline_value,
                    current=current_value,
                    delta=delta,
                    relative_delta=relative_delta,
                    tolerance=tolerance,
                )
            )
        elif relative_delta > tolerance:
            result.improvements[metric] = relative_delta
        else:
            result.unchanged.append(metric)
    return result
