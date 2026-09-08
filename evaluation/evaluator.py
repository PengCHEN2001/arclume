"""End-to-end Agent Evaluation.

This module combines Intent metrics, end-to-end dialog execution, LLM-as-Judge
quality scoring, and baseline regression detection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
from typing import Any, Iterable

from evaluation.judge import LLMJudge
from evaluation.metrics import classification_details


@dataclass(frozen=True)
class IntentTestCase:
    """One Intent case used by the end-to-end evaluator."""

    message: str
    expected_intent: str
    context: dict[str, Any] | None = None


@dataclass(frozen=True)
class QualityScores:
    """Four LLM-as-Judge dimensions used by the evaluator."""

    relevance: float
    accuracy: float
    completeness: float
    helpfulness: float
    judge_failed: bool = False
    error: str | None = None

    @property
    def correctness(self) -> float:
        """Compatibility alias for the generic ``correctness`` name."""

        return self.accuracy

    @property
    def overall(self) -> float:
        return statistics.mean(
            [self.relevance, self.accuracy, self.completeness, self.helpfulness]
        )


@dataclass
class EvalResult:
    """One Intent or dialog evaluation result."""

    test_id: str
    passed: bool
    scores: dict[str, float]
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalReport:
    """Report returned by the end-to-end evaluator."""

    timestamp: str
    total: int
    passed: int
    pass_rate: float
    avg_scores: dict[str, float]
    regressions: list[str]
    recommendations: list[str]
    results: list[EvalResult]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvalReport":
        return cls(
            timestamp=str(value.get("timestamp", "")),
            total=int(value.get("total", 0)),
            passed=int(value.get("passed", 0)),
            pass_rate=float(value.get("pass_rate", 0.0)),
            avg_scores={
                str(key): float(item)
                for key, item in (value.get("avg_scores") or {}).items()
            },
            regressions=[str(item) for item in value.get("regressions") or []],
            recommendations=[
                str(item) for item in value.get("recommendations") or []
            ],
            results=[
                EvalResult(
                    test_id=str(item.get("test_id", "")),
                    passed=bool(item.get("passed", False)),
                    scores={
                        str(key): float(score)
                        for key, score in (item.get("scores") or {}).items()
                    },
                    detail=str(item.get("detail", "")),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in value.get("results") or []
            ],
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "EvalReport":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Evaluation report must be a JSON object")
        return cls.from_dict(value)


DEFAULT_INTENT_CASES: list[IntentTestCase] = [
    IntentTestCase("我的订单什么时候到？", "logistics"),
    IntentTestCase("帮我取消订单", "request"),
    IntentTestCase("你们服务太差了！", "complaint"),
    IntentTestCase("应用一直报500错误", "technical_crash"),
    IntentTestCase("为什么扣了两次款？", "payment_issue"),
    IntentTestCase("我要投诉，转人工！", "human_handoff"),
    IntentTestCase("你好", "greeting"),
    IntentTestCase("修改我的邮箱地址", "account"),
    IntentTestCase("帮我开发票", "invoice"),
    IntentTestCase("退款多久到账？", "refund"),
    IntentTestCase("登录一直报401", "technical_login"),
]


DEFAULT_DIALOG_CASES: list[dict[str, Any]] = [
    {"question": "我的订单 #12345 还没到，已经超时了"},
    {"question": "应用登录一直报错 401"},
    {"question": "为什么这个月多扣了 50 块钱？"},
    {"question": "帮我把收货地址改成北京市朝阳区"},
    {"turns": ["你好，我想退款", "订单号是 #12345", "退款多久能到账？"]},
]


class EndToEndEvaluator:
    """Run Intent, dialog-quality, and baseline evaluation."""

    PASS_THRESHOLD = 0.75
    REGRESSION_THRESHOLD = 0.05

    def __init__(
        self,
        *,
        orchestrator: Any,
        recognizer: Any,
        llm: Any | None = None,
        judge: LLMJudge | Any | None = None,
        baseline_path: str | Path | None = None,
        pass_threshold: float = PASS_THRESHOLD,
        regression_threshold: float = REGRESSION_THRESHOLD,
    ) -> None:
        self.orchestrator = orchestrator
        self.recognizer = recognizer
        self.judge = judge or (LLMJudge(llm) if llm is not None else None)
        self.baseline_path = Path(baseline_path) if baseline_path else None
        self.pass_threshold = pass_threshold
        self.regression_threshold = regression_threshold
        self.history: list[EvalReport] = []
        self.baseline = self._load_baseline()

    async def run(
        self,
        intent_cases: Iterable[IntentTestCase] | None = None,
        dialog_cases: Iterable[dict[str, Any]] | None = None,
    ) -> EvalReport:
        """Run the complete Evaluation flow."""

        intent_cases = list(intent_cases) if intent_cases is not None else list(
            DEFAULT_INTENT_CASES
        )
        dialog_cases = list(dialog_cases) if dialog_cases is not None else list(
            DEFAULT_DIALOG_CASES
        )
        results: list[EvalResult] = []
        avg_scores: dict[str, float] = {}

        intent_result, intent_scores = await self._evaluate_intent(intent_cases)
        if intent_result is not None:
            results.append(intent_result)
            avg_scores.update(intent_scores)

        quality_values: dict[str, list[float]] = {
            "relevance": [],
            "accuracy": [],
            "completeness": [],
            "helpfulness": [],
        }
        for index, case in enumerate(dialog_cases):
            case_results = await self._evaluate_dialog_case(case, index)
            results.extend(case_results)
            for result in case_results:
                for key in quality_values:
                    if key in result.scores:
                        quality_values[key].append(result.scores[key])
        avg_scores.update(
            {
                key: round(statistics.mean(values), 4)
                for key, values in quality_values.items()
                if values
            }
        )

        report = EvalReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total=len(results),
            passed=sum(1 for result in results if result.passed),
            pass_rate=0.0,
            avg_scores=avg_scores,
            regressions=self._detect_regressions(avg_scores),
            recommendations=self._recommendations(avg_scores),
            results=results,
        )
        report.pass_rate = report.passed / report.total if report.total else 0.0
        self.history.append(report)
        self._save_baseline(report)
        return report

    async def _evaluate_intent(
        self,
        cases: list[IntentTestCase],
    ) -> tuple[EvalResult | None, dict[str, float]]:
        if not cases:
            return None, {}
        expected: list[str] = []
        predicted: list[str] = []
        details: list[dict[str, Any]] = []
        for case in cases:
            expected.append(case.expected_intent)
            try:
                result = await self.recognizer.recognize(case.message)
                raw_intent = getattr(result, "intent", result)
                label = getattr(raw_intent, "value", raw_intent)
                predicted_label = str(label)
                details.append(
                    {
                        "message": case.message,
                        "expected": case.expected_intent,
                        "predicted": predicted_label,
                        "confidence": getattr(result, "confidence", None),
                        "reasoning": getattr(result, "reasoning", ""),
                    }
                )
            except Exception as exc:
                predicted_label = "__error__"
                details.append(
                    {
                        "message": case.message,
                        "expected": case.expected_intent,
                        "predicted": predicted_label,
                        "error": str(exc),
                    }
                )
            predicted.append(predicted_label)

        metrics = classification_details(expected, predicted)
        correct = sum(left == right for left, right in zip(expected, predicted))
        result = EvalResult(
            test_id="intent_recognition",
            passed=metrics["accuracy"] >= self.pass_threshold,
            scores={
                "accuracy": metrics["accuracy"],
                "macro_f1": metrics["macro_f1"],
            },
            detail=(
                f"准确率 {metrics['accuracy']:.1%}，"
                f"Macro-F1 {metrics['macro_f1']:.3f}"
            ),
            metadata={
                "total": len(cases),
                "correct": correct,
                "per_class": metrics["per_class"],
                "cases": details,
            },
        )
        return result, {"intent_accuracy": metrics["accuracy"], "intent_macro_f1": metrics["macro_f1"]}

    async def _evaluate_dialog_case(
        self,
        case: dict[str, Any],
        case_index: int,
    ) -> list[EvalResult]:
        questions = self._dialog_turns(case)
        if not questions:
            return []
        conv_id = str(case.get("conv_id") or f"eval_{case_index}")
        user_id = str(case.get("user_id") or "eval_user")
        reference_answer = str(case.get("reference_answer") or "")
        history: list[dict[str, str]] = []
        results: list[EvalResult] = []

        for turn_index, question in enumerate(questions):
            context = self._history_context(history)
            try:
                orchestrator_result = await self.orchestrator.run(
                    question,
                    user_id=user_id,
                    conversation_id=conv_id,
                    history=history[-6:] or None,
                    memory_context=None,
                )
                answer = str(getattr(orchestrator_result, "response", ""))
                scores = await self._judge_answer(
                    question,
                    answer,
                    context=context,
                    reference_answer=reference_answer,
                )
                metadata = {
                    "question": question,
                    "response": answer,
                    "agent_type": self._value(
                        getattr(
                            orchestrator_result,
                            "primary_agent",
                            getattr(orchestrator_result, "agent_type", None),
                        )
                    ),
                    "intent": self._value(
                        getattr(
                            getattr(orchestrator_result, "intent", None),
                            "intent",
                            getattr(orchestrator_result, "intent", None),
                        )
                    ),
                    "turn": turn_index,
                    "conv_id": conv_id,
                    "judge_failed": scores.judge_failed,
                    "judge_error": scores.error,
                }
                detail = f"Q: {question[:30]}... → 综合评分 {scores.overall:.3f}"
            except Exception as exc:
                answer = ""
                scores = QualityScores(
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    judge_failed=True,
                    error=str(exc),
                )
                metadata = {
                    "question": question,
                    "response": answer,
                    "turn": turn_index,
                    "conv_id": conv_id,
                    "execution_failed": True,
                    "error": str(exc),
                }
                detail = f"Q: {question[:30]}... → 执行失败"

            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": answer})
            test_id = (
                f"dialog_{case_index}"
                if len(questions) == 1
                else f"dialog_{case_index}_turn_{turn_index}"
            )
            results.append(
                EvalResult(
                    test_id=test_id,
                    passed=scores.overall >= self.pass_threshold,
                    scores={
                        "relevance": scores.relevance,
                        "accuracy": scores.accuracy,
                        "completeness": scores.completeness,
                        "helpfulness": scores.helpfulness,
                        "overall": scores.overall,
                    },
                    detail=detail,
                    metadata=metadata,
                )
            )
        return results

    async def _judge_answer(
        self,
        question: str,
        answer: str,
        *,
        context: str,
        reference_answer: str,
    ) -> QualityScores:
        if self.judge is None:
            return QualityScores(
                0.5,
                0.5,
                0.5,
                0.5,
                judge_failed=True,
                error="LLM Judge is not configured",
            )
        try:
            result = await self.judge.judge(
                question,
                answer,
                context=context,
                reference_answer=reference_answer,
            )
            accuracy = getattr(result, "accuracy", None)
            if accuracy is None:
                accuracy = getattr(result, "correctness")
            return QualityScores(
                relevance=float(result.relevance),
                accuracy=float(accuracy),
                completeness=float(result.completeness),
                helpfulness=float(result.helpfulness),
            )
        except Exception as exc:
            return QualityScores(
                0.5,
                0.5,
                0.5,
                0.5,
                judge_failed=True,
                error=str(exc),
            )

    @staticmethod
    def _dialog_turns(case: dict[str, Any]) -> list[str]:
        turns = case.get("turns")
        if isinstance(turns, list):
            return [str(turn) for turn in turns if str(turn).strip()]
        question = case.get("question")
        return [str(question)] if question else []

    @staticmethod
    def _history_context(history: list[dict[str, str]]) -> str:
        if not history:
            return ""
        lines = [f"{item['role']}: {item['content']}" for item in history[-8:]]
        return "[评测多轮历史]\n" + "\n".join(lines)

    def _detect_regressions(self, current: dict[str, float]) -> list[str]:
        previous = self.history[-1] if self.history else self.baseline
        if previous is None:
            return []
        regressions: list[str] = []
        for metric, value in current.items():
            old = previous.avg_scores.get(metric)
            if old is None or old <= 0:
                continue
            relative_delta = (value - old) / old
            if relative_delta < -self.regression_threshold:
                regressions.append(
                    f"{metric}: {old:.3f} → {value:.3f} "
                    f"(退化 {abs(relative_delta):.1%})"
                )
        return regressions

    def _recommendations(self, scores: dict[str, float]) -> list[str]:
        recommendations: list[str] = []
        if scores.get("intent_accuracy", 1.0) < 0.90:
            recommendations.append(
                "意图识别准确率 < 90%：增加 Few-shot 示例，或对低 F1 的意图类别补充评测数据"
            )
        if scores.get("relevance", 1.0) < self.pass_threshold:
            recommendations.append("相关性偏低：检查 Agent system prompt 是否聚焦用户问题")
        if scores.get("completeness", 1.0) < self.pass_threshold:
            recommendations.append("完整性偏低：要求 Agent 覆盖解决问题所需的关键步骤")
        if scores.get("helpfulness", 1.0) < self.pass_threshold:
            recommendations.append("有用性偏低：要求回答提供用户可以执行的具体操作")
        if not recommendations:
            recommendations.append("所有已运行指标均达标，继续保持")
        return recommendations

    @staticmethod
    def _value(value: Any) -> Any:
        return getattr(value, "value", value)

    def _load_baseline(self) -> EvalReport | None:
        if not self.baseline_path or not self.baseline_path.exists():
            return None
        try:
            return EvalReport.load(self.baseline_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _save_baseline(self, report: EvalReport) -> None:
        if self.baseline_path:
            report.save(self.baseline_path)
