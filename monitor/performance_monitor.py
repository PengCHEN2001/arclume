"""Online performance monitoring for the Arclume runtime.

The monitor reads statistics already collected by the Orchestrator and Tool
Manager. It does not add another model call to the customer-service path. Its
responsibilities are to expose the current health picture, detect repeated or
unusual failures, and feed a bounded routing penalty back to the Orchestrator.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
import statistics
from collections import defaultdict, deque
from enum import Enum
from typing import Any, Deque

import httpx

try:  # Prometheus is optional for local development and unit tests.
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        start_http_server,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the optional package
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    CollectorRegistry = Counter = Gauge = Histogram = None  # type: ignore[assignment]
    generate_latest = start_http_server = None  # type: ignore[assignment]
    PROMETHEUS_AVAILABLE = False


logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Alert severity used by the monitoring API."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    """One threshold or anomaly notification."""

    severity: Severity
    metric: str
    message: str
    value: float
    threshold: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resolved: bool = False


@dataclass
class Suggestion:
    """A concrete operational action suggested by observed metrics."""

    title: str
    detail: str
    action: str
    priority: int


class AnomalyDetector:
    """Detect unusual values with a bounded sliding-window Z-score."""

    def __init__(self, *, window: int = 60, sensitivity: float = 2.5) -> None:
        if window < 4:
            raise ValueError("Anomaly window must be at least four samples")
        if sensitivity <= 0:
            raise ValueError("Anomaly sensitivity must be positive")
        self.window = window
        self.sensitivity = sensitivity
        self._history: dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )

    def record(self, metric: str, value: float) -> dict[str, Any] | None:
        """Record a value and return anomaly details when evidence is sufficient."""

        values = self._history[metric]
        values.append(value)
        if len(values) < max(4, self.window // 2):
            return None

        mean = statistics.mean(values)
        deviation = statistics.stdev(values) if len(values) > 1 else 0.0
        if deviation == 0:
            return None

        z_score = abs(value - mean) / deviation
        if z_score <= self.sensitivity:
            return None
        return {
            "metric": metric,
            "value": value,
            "mean": round(mean, 4),
            "z_score": round(z_score, 2),
            "severity": (
                "high" if z_score > self.sensitivity * 1.5 else "medium"
            ),
        }


class PerformanceMonitor:
    """Collect Agent and Tool metrics and provide a small feedback loop."""

    THRESHOLDS: dict[str, tuple[float, Severity, str]] = {
        "agent_success_rate": (0.90, Severity.ERROR, "less_than"),
        "tool_success_rate": (0.95, Severity.WARNING, "less_than"),
        "agent_avg_ms": (3000.0, Severity.WARNING, "greater_than"),
        "tool_avg_ms": (5000.0, Severity.ERROR, "greater_than"),
    }

    def __init__(
        self,
        *,
        orchestrator: Any,
        tool_manager: Any,
        interval_seconds: float = 10.0,
        webhook_url: str | None = None,
        prometheus_port: int | None = None,
        anomaly_window: int = 60,
        anomaly_sensitivity: float = 2.5,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("Monitor interval must be positive")

        self.orchestrator = orchestrator
        self.tool_manager = tool_manager
        self.interval_seconds = interval_seconds
        self.webhook_url = webhook_url
        self.detector = AnomalyDetector(
            window=anomaly_window,
            sensitivity=anomaly_sensitivity,
        )
        self.alerts: list[Alert] = []
        self.suggestions: list[Suggestion] = []
        self.active = False
        self._task: asyncio.Task[None] | None = None
        self._last_collection_at: str | None = None
        self._prometheus_registry = None
        self._prometheus: dict[str, Any] = {}

        if PROMETHEUS_AVAILABLE or prometheus_port:
            self._setup_prometheus(prometheus_port)

    def _setup_prometheus(self, port: int | None) -> None:
        """Create Prometheus metrics and optionally start a scrape server."""

        if not PROMETHEUS_AVAILABLE:
            logger.warning(
                "Prometheus metrics requested but prometheus-client is not installed"
            )
            return

        self._prometheus_registry = CollectorRegistry()
        self._prometheus = {
            "agent_success_rate": Gauge(
                "arclume_agent_success_rate",
                "Current Agent success rate",
                ["agent"],
                registry=self._prometheus_registry,
            ),
            "agent_latency_ms": Histogram(
                "arclume_agent_latency_ms",
                "Observed Agent latency in milliseconds",
                ["agent"],
                registry=self._prometheus_registry,
            ),
            "tool_success_rate": Gauge(
                "arclume_tool_success_rate",
                "Current Tool success rate",
                ["tool"],
                registry=self._prometheus_registry,
            ),
            "requests_total": Counter(
                "arclume_requests_total",
                "Collected request snapshots",
                registry=self._prometheus_registry,
            ),
        }
        if port:
            start_http_server(port, registry=self._prometheus_registry)
            logger.info("Prometheus scrape server started on port %s", port)

    async def start(self) -> None:
        """Start periodic collection without blocking the API lifespan."""

        if self.active:
            return
        self.active = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Performance monitor started with %.1fs interval", self.interval_seconds)

    async def stop(self) -> None:
        """Stop periodic collection and release its task."""

        self.active = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def collect_once(self) -> None:
        """Collect one snapshot; exposed for tests and manual diagnostics."""

        await self._collect()

    async def _run_loop(self) -> None:
        while self.active:
            try:
                await self._collect()
            except Exception:
                logger.exception("Performance monitor collection failed")
            await asyncio.sleep(self.interval_seconds)

    async def _collect(self) -> None:
        agent_stats = self._agent_stats()
        tool_stats = self._tool_stats()
        routing_penalties: dict[str, float] = {}

        for agent_name, stats in agent_stats.items():
            success_rate = self._number(stats, "success_rate", default=1.0)
            average_ms = self._number(
                stats,
                "avg_ms",
                fallback_key="average_ms",
            )
            self._record_anomaly(f"agent_success_rate:{agent_name}", success_rate)
            self._record_anomaly(f"agent_avg_ms:{agent_name}", average_ms)
            self._check_threshold("agent_success_rate", success_rate, agent_name)
            self._check_threshold("agent_avg_ms", average_ms, agent_name)
            self._set_agent_prometheus(agent_name, success_rate, average_ms)
            routing_penalties[agent_name] = self._routing_penalty(
                success_rate,
                average_ms,
            )

        for tool_name, stats in tool_stats.items():
            success_rate = self._number(stats, "success_rate", default=1.0)
            average_ms = self._number(
                stats,
                "avg_latency_ms",
                fallback_key="average_latency_ms",
            )
            consecutive_failures = int(
                self._number(
                    stats,
                    "consecutive_fails",
                    fallback_key="consecutive_failures",
                )
            )
            self._check_threshold("tool_success_rate", success_rate, tool_name)
            self._check_threshold("tool_avg_ms", average_ms, tool_name)
            self._set_tool_prometheus(tool_name, success_rate)
            if consecutive_failures >= 3:
                self._add_suggestion(
                    Suggestion(
                        title=f"Tool {tool_name} has consecutive failures",
                        detail=(
                            f"It has failed {consecutive_failures} times in a row; "
                            f"success rate is {success_rate:.1%} and average latency "
                            f"is {average_ms:.0f}ms."
                        ),
                        action=(
                            "Check the dependency, review the error trace, and "
                            "consider a safer timeout or fallback."
                        ),
                        priority=9,
                    )
                )

        updater = getattr(self.orchestrator, "update_routing_penalties", None)
        if callable(updater):
            updater(routing_penalties)
        self._generate_routing_suggestions(agent_stats)
        self._last_collection_at = datetime.now(timezone.utc).isoformat()
        if "requests_total" in self._prometheus:
            self._prometheus["requests_total"].inc()

    def _agent_stats(self) -> dict[str, dict[str, Any]]:
        provider = getattr(self.orchestrator, "get_stats", None)
        return provider() if callable(provider) else {}

    def _tool_stats(self) -> dict[str, dict[str, Any]]:
        provider = getattr(self.tool_manager, "get_stats", None)
        if not callable(provider):
            provider = getattr(self.tool_manager, "stats_snapshot", None)
        return provider() if callable(provider) else {}

    @staticmethod
    def _number(
        values: dict[str, Any],
        key: str,
        *,
        fallback_key: str | None = None,
        default: float = 0.0,
    ) -> float:
        value = values.get(key)
        if value is None and fallback_key:
            value = values.get(fallback_key)
        try:
            return float(value if value is not None else default)
        except (TypeError, ValueError):
            return default

    def _record_anomaly(self, metric: str, value: float) -> None:
        anomaly = self.detector.record(metric, value)
        if anomaly:
            self._add_alert(
                Alert(
                    severity=Severity.WARNING,
                    metric=f"anomaly:{metric}",
                    message=(
                        f"{metric} changed unusually (z-score "
                        f"{anomaly['z_score']})."
                    ),
                    value=value,
                    threshold=self.detector.sensitivity,
                )
            )

    def _check_threshold(self, metric: str, value: float, label: str) -> None:
        threshold, severity, operator = self.THRESHOLDS[metric]
        triggered = (
            value < threshold if operator == "less_than" else value > threshold
        )
        metric_name = f"{metric}:{label}"
        if not triggered:
            self._resolve_alert(metric_name)
            return
        self._add_alert(
            Alert(
                severity=severity,
                metric=metric_name,
                message=f"{metric_name} is {value:.3f}; threshold is {threshold:.3f}.",
                value=value,
                threshold=threshold,
            )
        )

    def _add_alert(self, alert: Alert) -> None:
        existing = next(
            (
                item
                for item in self.alerts
                if item.metric == alert.metric and not item.resolved
            ),
            None,
        )
        if existing is not None:
            existing.value = alert.value
            existing.message = alert.message
            existing.timestamp = alert.timestamp
            return
        self.alerts.append(alert)
        logger.warning("[%s] %s", alert.severity.value.upper(), alert.message)
        if self.webhook_url:
            asyncio.create_task(self._send_webhook(alert))

    def _resolve_alert(self, metric: str) -> None:
        for alert in self.alerts:
            if alert.metric == metric and not alert.resolved:
                alert.resolved = True

    def _generate_routing_suggestions(
        self,
        agent_stats: dict[str, dict[str, Any]],
    ) -> None:
        for agent_name, stats in agent_stats.items():
            total = int(self._number(stats, "total"))
            success_rate = self._number(stats, "success_rate", default=1.0)
            if total > 10 and success_rate < 0.85:
                routing_score = self._number(stats, "routing_score")
                self._add_suggestion(
                    Suggestion(
                        title=f"Agent {agent_name} success rate is low",
                        detail=(
                            f"Success rate is {success_rate:.1%} after {total} calls; "
                            f"routing score is {routing_score:.3f}."
                        ),
                        action=(
                            "Review the Agent profile and prompt, inspect failed traces, "
                            "and consider adding another instance for this domain."
                        ),
                        priority=8,
                    )
                )

    def _add_suggestion(self, suggestion: Suggestion) -> None:
        if not any(item.title == suggestion.title for item in self.suggestions):
            self.suggestions.append(suggestion)
            self.suggestions.sort(key=lambda item: item.priority, reverse=True)

    @staticmethod
    def _routing_penalty(success_rate: float, average_ms: float) -> float:
        """Convert online performance into a bounded routing penalty."""

        penalty = 0.0
        if success_rate < 0.90:
            penalty += min(0.5, (0.90 - success_rate) * 2)
        if average_ms > 3000:
            penalty += min(0.4, (average_ms - 3000) / 10000)
        return min(penalty, 0.9)

    def _set_agent_prometheus(
        self,
        agent_name: str,
        success_rate: float,
        average_ms: float,
    ) -> None:
        if not self._prometheus:
            return
        self._prometheus["agent_success_rate"].labels(agent=agent_name).set(success_rate)
        self._prometheus["agent_latency_ms"].labels(agent=agent_name).observe(average_ms)

    def _set_tool_prometheus(self, tool_name: str, success_rate: float) -> None:
        if self._prometheus:
            self._prometheus["tool_success_rate"].labels(tool=tool_name).set(success_rate)

    async def _send_webhook(self, alert: Alert) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(self.webhook_url, json=self._alert_payload(alert))
        except Exception:
            logger.exception("Failed to send monitoring alert webhook")

    @staticmethod
    def _alert_payload(alert: Alert) -> dict[str, Any]:
        payload = asdict(alert)
        payload["severity"] = alert.severity.value
        return payload

    def metrics_payload(self) -> tuple[bytes, str]:
        """Return Prometheus text or a dependency-free metrics snapshot."""

        if self._prometheus_registry is not None and generate_latest is not None:
            return generate_latest(self._prometheus_registry), CONTENT_TYPE_LATEST

        lines = [
            "# HELP arclume_monitor_active Whether the monitor loop is active",
            "# TYPE arclume_monitor_active gauge",
            f"arclume_monitor_active {int(self.active)}",
        ]
        for name, stats in self._agent_stats().items():
            labels = f'agent="{name}"'
            lines.append(f'arclume_agent_success_rate{{{labels}}} {self._number(stats, "success_rate", default=1.0)}')
            lines.append(f'arclume_agent_latency_ms{{{labels}}} {self._number(stats, "avg_ms", fallback_key="average_ms")}')
        for name, stats in self._tool_stats().items():
            labels = f'tool="{name}"'
            lines.append(f'arclume_tool_success_rate{{{labels}}} {self._number(stats, "success_rate", default=1.0)}')
        return ("\n".join(lines) + "\n").encode("utf-8"), CONTENT_TYPE_LATEST

    def summary(self) -> dict[str, Any]:
        """Return the monitor response exposed by the HTTP API."""

        return {
            "active": self.active,
            "last_collection_at": self._last_collection_at,
            "prometheus_available": PROMETHEUS_AVAILABLE,
            "agent_stats": self._agent_stats(),
            "tool_stats": self._tool_stats(),
            "active_alerts": [
                self._alert_payload(alert)
                for alert in self.alerts
                if not alert.resolved
            ][-10:],
            "suggestions": [
                {
                    "title": suggestion.title,
                    "detail": suggestion.detail,
                    "action": suggestion.action,
                    "priority": suggestion.priority,
                }
                for suggestion in self.suggestions[:5]
            ],
        }
