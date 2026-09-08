import unittest

from monitor.performance_monitor import PerformanceMonitor


class FakeOrchestrator:
    def __init__(self) -> None:
        self.agent_stats = {
            "technical_0": {
                "total": 12,
                "success": 9,
                "success_rate": 0.75,
                "avg_ms": 3500.0,
                "routing_score": 0.4,
            }
        }
        self.penalties: dict[str, float] = {}

    def get_stats(self) -> dict[str, dict[str, object]]:
        return self.agent_stats

    def update_routing_penalties(self, penalties: dict[str, float]) -> None:
        self.penalties = penalties


class FakeToolManager:
    def __init__(self) -> None:
        self.tool_stats = {
            "order_query": {
                "total": 4,
                "success_rate": 0.5,
                "avg_latency_ms": 100.0,
                "consecutive_fails": 3,
                "circuit_state": "closed",
            }
        }

    def get_stats(self) -> dict[str, dict[str, object]]:
        return self.tool_stats


class PerformanceMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_alerts_suggestions_and_routing_penalties(self) -> None:
        orchestrator = FakeOrchestrator()
        monitor = PerformanceMonitor(
            orchestrator=orchestrator,
            tool_manager=FakeToolManager(),
        )

        await monitor.collect_once()
        summary = monitor.summary()

        self.assertTrue(summary["active_alerts"])
        self.assertTrue(summary["suggestions"])
        self.assertGreater(orchestrator.penalties["technical_0"], 0.0)
        self.assertIn("arclume_monitor_active", monitor.metrics_payload()[0].decode())

    async def test_recovered_metric_resolves_alert(self) -> None:
        orchestrator = FakeOrchestrator()
        monitor = PerformanceMonitor(
            orchestrator=orchestrator,
            tool_manager=FakeToolManager(),
        )

        await monitor.collect_once()
        orchestrator.agent_stats["technical_0"].update(
            {"success_rate": 1.0, "avg_ms": 100.0}
        )
        await monitor.collect_once()

        self.assertFalse(
            any(
                alert["metric"] == "agent_success_rate:technical_0"
                for alert in monitor.summary()["active_alerts"]
            )
        )

    async def test_monitor_lifecycle_is_bounded(self) -> None:
        monitor = PerformanceMonitor(
            orchestrator=FakeOrchestrator(),
            tool_manager=FakeToolManager(),
            interval_seconds=0.01,
        )

        await monitor.start()
        self.assertTrue(monitor.active)
        await monitor.stop()
        self.assertFalse(monitor.active)


if __name__ == "__main__":
    unittest.main()
