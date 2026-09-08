"""Optional LLM Judge adapter; never used by default automated tests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable


class JudgeError(RuntimeError):
    """Raised when an optional Judge response cannot be parsed safely."""


@dataclass(frozen=True)
class JudgeResult:
    """Bounded quality scores returned by one Judge call."""

    relevance: float
    accuracy: float
    completeness: float
    helpfulness: float
    rationale: str = ""

    @property
    def correctness(self) -> float:
        """Compatibility alias for callers using the generic term."""

        return self.accuracy

    @property
    def average(self) -> float:
        return (
            self.relevance
            + self.accuracy
            + self.completeness
            + self.helpfulness
        ) / 4.0


class LLMJudge:
    """Ask a configured chat model to score answer quality on a 0-1 scale."""

    def __init__(self, llm: Any) -> None:
        self.llm = llm

    async def judge(
        self,
        question: str,
        answer: str,
        *,
        context: str = "",
        reference_answer: str = "",
    ) -> JudgeResult:
        prompt = (
            "Evaluate a customer-support answer. Return JSON only with numeric "
            "scores from 0 to 1 for relevance, accuracy, completeness, and "
            "helpfulness, plus a short rationale. Do not reward invented facts.\n\n"
            f"Question:\n{question}\n\n"
            f"Answer:\n{answer}\n\n"
            f"Retrieved context:\n{context}\n\n"
            f"Reference answer, if available:\n{reference_answer}"
        )
        try:
            raw = await self.llm.chat(
                prompt,
                system_prompt="You are a strict, evidence-based evaluation judge.",
                temperature=0.0,
                max_tokens=256,
            )
        except Exception as exc:
            raise JudgeError(f"LLM Judge request failed: {exc}") from exc
        return self.parse(raw)

    async def judge_many(
        self,
        cases: Iterable[dict[str, str]],
    ) -> list[JudgeResult]:
        results: list[JudgeResult] = []
        for case in cases:
            results.append(
                await self.judge(
                    case.get("question", ""),
                    case.get("answer", ""),
                    context=case.get("context", ""),
                    reference_answer=case.get("reference_answer", ""),
                )
            )
        return results

    @staticmethod
    def parse(raw: str) -> JudgeResult:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise JudgeError("LLM Judge did not return a JSON object")
        try:
            value = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise JudgeError("LLM Judge returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise JudgeError("LLM Judge response must be a JSON object")

        def score(name: str, *, aliases: tuple[str, ...] = ()) -> float:
            try:
                raw = value.get(name)
                if raw is None:
                    for alias in aliases:
                        if value.get(alias) is not None:
                            raw = value[alias]
                            break
                if raw is None:
                    raw = 0.5
                return max(0.0, min(1.0, float(raw)))
            except (KeyError, TypeError, ValueError) as exc:
                raise JudgeError(f"LLM Judge score is missing: {name}") from exc

        return JudgeResult(
            relevance=score("relevance"),
            accuracy=score("accuracy", aliases=("correctness",)),
            completeness=score("completeness"),
            helpfulness=score("helpfulness"),
            rationale=str(value.get("rationale") or ""),
        )
