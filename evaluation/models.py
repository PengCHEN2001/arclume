"""Serializable inputs and outputs used by the offline Evaluation layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IntentCase:
    """One labeled message used to evaluate intent and optional routing."""

    case_id: str
    message: str
    expected_intent: str
    expected_agent: str | None = None
    context: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IntentCase":
        return cls(
            case_id=str(value["case_id"]),
            message=str(value["message"]),
            expected_intent=str(value["expected_intent"]),
            expected_agent=(
                str(value["expected_agent"])
                if value.get("expected_agent") is not None
                else None
            ),
            context=(
                dict(value["context"])
                if isinstance(value.get("context"), dict)
                else None
            ),
        )


@dataclass(frozen=True)
class RetrievalCase:
    """One query and its labeled relevant chunk identifiers."""

    case_id: str
    query: str
    relevant_chunk_ids: tuple[str, ...]
    top_k: int = 5

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RetrievalCase":
        relevant = value.get("relevant_chunk_ids") or []
        return cls(
            case_id=str(value["case_id"]),
            query=str(value["query"]),
            relevant_chunk_ids=tuple(str(item) for item in relevant),
            top_k=max(1, int(value.get("top_k", 5))),
        )


@dataclass
class EvaluationReport:
    """A JSON-safe report produced by one evaluation run."""

    name: str
    metrics: dict[str, float]
    counts: dict[str, int] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvaluationReport":
        return cls(
            name=str(value.get("name", "evaluation")),
            metrics={
                str(key): float(item)
                for key, item in (value.get("metrics") or {}).items()
            },
            counts={
                str(key): int(item)
                for key, item in (value.get("counts") or {}).items()
            },
            failures=list(value.get("failures") or []),
            metadata=dict(value.get("metadata") or {}),
            created_at=str(
                value.get("created_at")
                or datetime.now(timezone.utc).isoformat()
            ),
        )

    def save(self, path: str | Path) -> None:
        """Write the report as readable UTF-8 JSON."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "EvaluationReport":
        """Load a previously saved report."""

        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Evaluation report must be a JSON object")
        return cls.from_dict(value)


@dataclass(frozen=True)
class RegressionIssue:
    """One metric that regressed beyond its allowed tolerance."""

    metric: str
    baseline: float
    current: float
    delta: float
    relative_delta: float
    tolerance: float


@dataclass
class RegressionReport:
    """Comparison between a baseline report and a current report."""

    baseline_name: str
    current_name: str
    regressions: list[RegressionIssue] = field(default_factory=list)
    improvements: dict[str, float] = field(default_factory=dict)
    unchanged: list[str] = field(default_factory=list)
    missing_metrics: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.regressions and not self.missing_metrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_name": self.baseline_name,
            "current_name": self.current_name,
            "passed": self.passed,
            "regressions": [asdict(item) for item in self.regressions],
            "improvements": dict(self.improvements),
            "unchanged": list(self.unchanged),
            "missing_metrics": list(self.missing_metrics),
        }


@dataclass
class EvaluationDataset:
    """Labeled cases loaded from one JSON dataset file."""

    intent_cases: list[IntentCase] = field(default_factory=list)
    retrieval_cases: list[RetrievalCase] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "EvaluationDataset":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Evaluation dataset must be a JSON object")
        return cls(
            intent_cases=[
                IntentCase.from_dict(item)
                for item in (value.get("intent_cases") or [])
            ],
            retrieval_cases=[
                RetrievalCase.from_dict(item)
                for item in (value.get("retrieval_cases") or [])
            ],
        )
