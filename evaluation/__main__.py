"""Run the local Intent and route evaluation dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agents.agent_orchestrator import AgentOrchestrator, AgentType
from core.intent_recognizer import IntentCategory, IntentRecognizer, UrgencyLevel
from evaluation.models import EvaluationDataset, EvaluationReport
from evaluation.regression import compare_reports
from evaluation.runner import evaluate_intent_cases, evaluate_retrieval_cases


def _route_without_agent_instances(result: object) -> AgentType:
    """Mirror the deterministic routing table without starting the API stack."""

    intent = getattr(result, "intent", IntentCategory.OTHER)
    urgency = getattr(result, "urgency", UrgencyLevel.LOW)
    if urgency is UrgencyLevel.CRITICAL or intent in AgentOrchestrator._ESCALATION_INTENTS:
        return AgentType.ESCALATION
    return AgentOrchestrator._INTENT_ROUTING.get(intent, AgentType.GENERAL)


async def _run(
    dataset_path: Path,
    report_path: Path | None,
    baseline_path: Path | None,
    *,
    verbose: bool = False,
) -> int:
    dataset = EvaluationDataset.load(dataset_path)
    report = await evaluate_intent_cases(
        dataset.intent_cases,
        IntentRecognizer().recognize,
        route=_route_without_agent_instances,
        name="local-intent-routing",
    )
    if dataset.retrieval_cases:
        retrieval_report = await evaluate_retrieval_cases(
            dataset.retrieval_cases,
            _search_not_configured,
            name="local-rag-retrieval",
        )
        report.metrics.update(retrieval_report.metrics)
        report.counts.update(retrieval_report.counts)
        report.failures.extend(retrieval_report.failures)
        report.metadata["retrieval"] = retrieval_report.metadata
    if report_path:
        report.save(report_path)

    output = report.to_dict()
    if baseline_path:
        comparison = compare_reports(
            EvaluationReport.load(baseline_path),
            report,
        )
        output["regression"] = comparison.to_dict()

    if verbose:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        summary: dict[str, object] = {
            "dataset": str(dataset_path),
            "metrics": report.metrics,
            "counts": report.counts,
            "failure_count": len(report.failures),
            "failure_preview": report.failures[:10],
            "intent_per_class": report.metadata.get("intent_per_class", {}),
        }
        if "route_per_class" in report.metadata:
            summary["route_per_class"] = report.metadata["route_per_class"]
        if "regression" in output:
            summary["regression"] = output["regression"]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if baseline_path and not output["regression"]["passed"]:
        return 1
    return 0


async def _search_not_configured(query: str, *, top_k: int) -> list[dict[str, object]]:
    """Keep the default CLI model-free; API code supplies the live retriever."""

    raise RuntimeError(
        "The local CLI has no live KnowledgeBase. Pass retrieval cases to an "
        "application-level runner with ToolManager.search_with_rewrite()."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evaluation/data/intent_cases_500.json"),
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use the small dependency-free smoke dataset instead of the full set",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every case and failure instead of a compact summary",
    )
    args = parser.parse_args()
    dataset_path = Path("evaluation/data/cases.json") if args.smoke else args.dataset
    return asyncio.run(
        _run(
            dataset_path,
            args.report,
            args.baseline,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
