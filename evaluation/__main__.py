"""Run the dependency-free local Intent/route evaluation dataset."""

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


async def _run(dataset_path: Path, report_path: Path | None, baseline_path: Path | None) -> int:
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

    print(json.dumps(output, ensure_ascii=False, indent=2))
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
        default=Path("evaluation/data/cases.json"),
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    return asyncio.run(_run(args.dataset, args.report, args.baseline))


if __name__ == "__main__":
    raise SystemExit(main())
