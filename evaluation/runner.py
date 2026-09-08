"""Async runners that connect the generic metrics to project components."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Iterable

from evaluation.metrics import classification_details, retrieval_metrics
from evaluation.models import EvaluationReport, IntentCase, RetrievalCase


async def _resolve(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _label(value: Any) -> str:
    normalized = getattr(value, "value", value)
    return str(normalized)


async def evaluate_intent_cases(
    cases: Iterable[IntentCase],
    recognize: Callable[[str], Any | Awaitable[Any]],
    *,
    route: Callable[[Any], Any | Awaitable[Any]] | None = None,
    name: str = "intent",
) -> EvaluationReport:
    """Evaluate an intent recognizer and optionally its routing decision.

    ``recognize`` may return an ``IntentResult`` or a plain label. If ``route``
    is supplied, it receives the recognizer's raw result and may return an
    Agent name or an object with a ``primary_agent`` attribute.
    """

    case_list = list(cases)
    expected_intents: list[str] = []
    predicted_intents: list[str] = []
    expected_agents: list[str] = []
    predicted_agents: list[str] = []
    failures: list[dict[str, Any]] = []

    for case in case_list:
        expected_intents.append(case.expected_intent)
        try:
            raw_result = await _resolve(recognize(case.message))
            raw_intent = getattr(raw_result, "intent", raw_result)
            predicted_intent = _label(raw_intent)
            predicted_intents.append(predicted_intent)

            if route is not None and case.expected_agent is not None:
                expected_agents.append(case.expected_agent)
                try:
                    raw_route = await _resolve(route(raw_result))
                    predicted_agent = _label(
                        getattr(raw_route, "primary_agent", raw_route)
                    )
                    predicted_agents.append(predicted_agent)
                except Exception as exc:
                    predicted_agents.append("__error__")
                    failures.append(
                        {
                            "case_id": case.case_id,
                            "type": "route_exception",
                            "error": str(exc),
                            "message": case.message,
                        }
                    )

            if predicted_intent != case.expected_intent:
                failures.append(
                    {
                        "case_id": case.case_id,
                        "type": "intent",
                        "expected": case.expected_intent,
                        "predicted": predicted_intent,
                        "message": case.message,
                    }
                )
        except Exception as exc:
            predicted_intents.append("__error__")
            if route is not None and case.expected_agent is not None:
                expected_agents.append(case.expected_agent)
                predicted_agents.append("__error__")
            failures.append(
                {
                    "case_id": case.case_id,
                    "type": "exception",
                    "error": str(exc),
                    "message": case.message,
                }
            )

    intent_details = classification_details(
        expected_intents,
        predicted_intents,
    )
    metrics = {
        f"intent_{key}": value
        for key, value in intent_details.items()
        if key != "per_class"
    }
    counts = {
        "intent_cases": len(case_list),
        "intent_failures": sum(
            item["type"] == "intent" for item in failures
        ),
        "intent_errors": sum(
            item["type"] == "exception" for item in failures
        ),
    }
    metadata: dict[str, Any] = {
        "kind": "intent_and_routing",
        "intent_per_class": intent_details["per_class"],
    }
    if expected_agents:
        route_details = classification_details(expected_agents, predicted_agents)
        metrics.update(
            {
                f"route_{key}": value
                for key, value in route_details.items()
                if key != "per_class"
            }
        )
        counts["route_cases"] = len(expected_agents)
        counts["route_failures"] = sum(
            expected != predicted
            for expected, predicted in zip(expected_agents, predicted_agents)
        )
        metadata["route_per_class"] = route_details["per_class"]

    return EvaluationReport(
        name=name,
        metrics=metrics,
        counts=counts,
        failures=failures,
        metadata=metadata,
    )


async def evaluate_retrieval_cases(
    cases: Iterable[RetrievalCase],
    search: Callable[..., Any],
    *,
    name: str = "retrieval",
) -> EvaluationReport:
    """Evaluate a retriever returning chunk dictionaries or a result payload."""

    case_list = list(cases)
    metric_inputs: list[tuple[list[str], tuple[str, ...], int]] = []
    failures: list[dict[str, Any]] = []

    for case in case_list:
        try:
            raw_result = await _resolve(search(case.query, top_k=case.top_k))
            if isinstance(raw_result, dict):
                results = raw_result.get("results") or []
            else:
                results = raw_result or []
            retrieved_ids = [
                str(item["chunk_id"])
                for item in results
                if isinstance(item, dict) and item.get("chunk_id") is not None
            ]
            metric_inputs.append(
                (retrieved_ids, case.relevant_chunk_ids, case.top_k)
            )
            if not set(retrieved_ids[: case.top_k]) & set(case.relevant_chunk_ids):
                failures.append(
                    {
                        "case_id": case.case_id,
                        "type": "retrieval_miss",
                        "query": case.query,
                        "relevant_chunk_ids": list(case.relevant_chunk_ids),
                        "retrieved_chunk_ids": retrieved_ids[: case.top_k],
                    }
                )
        except Exception as exc:
            metric_inputs.append(([], case.relevant_chunk_ids, case.top_k))
            failures.append(
                {
                    "case_id": case.case_id,
                    "type": "exception",
                    "error": str(exc),
                    "query": case.query,
                }
            )

    metrics = retrieval_metrics(metric_inputs)
    return EvaluationReport(
        name=name,
        metrics=metrics,
        counts={
            "retrieval_cases": len(case_list),
            "retrieval_failures": sum(
                item["type"] == "retrieval_miss" for item in failures
            ),
            "retrieval_errors": sum(
                item["type"] == "exception" for item in failures
            ),
        },
        failures=failures,
        metadata={"kind": "retrieval"},
    )
