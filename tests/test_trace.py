"""Tests for request-level Trace recording."""

import unittest

from harness.runtime import HarnessRuntime, RuntimeStatus
from harness.trace import TraceEventType, TraceRecorder


class TraceRecorderTests(unittest.TestCase):
    """Verify correlation, serialization, and bounded retention."""

    def test_events_are_filtered_by_request_and_bounded(self) -> None:
        recorder = TraceRecorder(max_events=3)
        recorder.record(TraceEventType.REQUEST_STARTED, request_id="one")
        recorder.record(TraceEventType.ROUTE_SELECTED, request_id="one")
        recorder.record(TraceEventType.REQUEST_COMPLETED, request_id="one")
        recorder.record(TraceEventType.REQUEST_STARTED, request_id="two")

        self.assertEqual(len(recorder.events()), 3)
        self.assertEqual(len(recorder.events("one")), 2)
        self.assertEqual(recorder.events("one")[0].event_type, TraceEventType.ROUTE_SELECTED)

    def test_event_is_json_serializable(self) -> None:
        recorder = TraceRecorder()
        event = recorder.record(
            TraceEventType.AGENT_COMPLETED,
            request_id="request-1",
            agent_name="billing",
            data={"success": True},
        )

        payload = event.model_dump(mode="json")

        self.assertEqual(payload["request_id"], "request-1")
        self.assertEqual(payload["data"]["success"], True)


class HarnessTraceTests(unittest.IsolatedAsyncioTestCase):
    """Verify that the model-independent Harness loop keeps request context."""

    async def test_runtime_events_keep_request_id(self) -> None:
        recorder = TraceRecorder()
        runtime = HarnessRuntime(tracer=recorder)

        outcome = await runtime.run(
            lambda _: "done",
            context={
                "request_id": "request-1",
                "conversation_id": "conversation-1",
                "agent_name": "general",
            },
        )

        self.assertEqual(outcome.status, RuntimeStatus.COMPLETED)
        events = recorder.events("request-1")
        self.assertEqual(
            [event.event_type for event in events],
            [TraceEventType.RUNTIME_STARTED, TraceEventType.RUNTIME_COMPLETED],
        )
        self.assertEqual(events[0].conversation_id, "conversation-1")
        self.assertEqual(events[0].agent_name, "general")


if __name__ == "__main__":
    unittest.main()
