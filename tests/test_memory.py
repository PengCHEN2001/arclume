"""Focused tests for layered Memory behavior without external services."""

import unittest

from memory import MemoryStoreError
from memory.conversation_memory import ConversationMemory
from schemas.context import ContextMessage


class FakeRedis:
    """Small async Redis substitute used by the Memory tests."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.expirations: dict[str, int] = {}

    async def lpush(self, key: str, value: str) -> None:
        values = self.data.setdefault(key, [])
        assert isinstance(values, list)
        values.insert(0, value)

    async def ltrim(self, key: str, start: int, end: int) -> None:
        values = self.data.get(key, [])
        assert isinstance(values, list)
        self.data[key] = values[start : end + 1 if end >= 0 else None]

    async def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds

    async def llen(self, key: str) -> int:
        values = self.data.get(key, [])
        return len(values) if isinstance(values, list) else 0

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.data.get(key, [])
        if not isinstance(values, list):
            return []
        return values[start : end + 1 if end >= 0 else None]

    async def get(self, key: str) -> object | None:
        return self.data.get(key)

    async def setex(self, key: str, seconds: int, value: str) -> None:
        self.data[key] = value
        self.expirations[key] = seconds

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)

    async def aclose(self) -> None:
        return None


class FailingReadRedis(FakeRedis):
    """Redis substitute that represents a core working-memory outage."""

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        raise RuntimeError("Redis is unavailable")


class RecordingLongTermMemory:
    """Long-term Memory substitute for episodic and profile assertions."""

    def __init__(self) -> None:
        self.episodic: list[dict[str, str]] = []
        self.profile: dict[str, object] = {}

    async def add_episodic_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: str,
        *,
        full_text: str = "",
    ) -> str:
        self.episodic.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "summary": summary,
                "full_text": full_text,
            }
        )
        return f"episodic:{len(self.episodic)}"

    async def search_episodic(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 3,
    ) -> list[dict[str, object]]:
        return [
            {"content": item["summary"], "score": 0.9}
            for item in self.episodic
            if item["user_id"] == user_id
        ][:top_k]

    async def get_user_profile(self, user_id: str) -> dict[str, object]:
        value = self.profile.get(user_id)
        return dict(value) if isinstance(value, dict) else {}

    async def update_user_profile(
        self,
        user_id: str,
        *,
        entities: dict[str, object] | None = None,
        preferences: dict[str, object] | None = None,
    ) -> None:
        self.profile[user_id] = {
            "user_id": user_id,
            "entities": dict(entities or {}),
            "preferences": dict(preferences or {}),
        }


class EpisodicFailureLongTermMemory(RecordingLongTermMemory):
    """Long-term substitute whose episodic search fails independently."""

    async def search_episodic(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 3,
    ) -> list[dict[str, object]]:
        raise MemoryStoreError("episodic storage is unavailable")


class ConversationMemoryTests(unittest.IsolatedAsyncioTestCase):
    """Verify compression and failure boundaries for the Memory layer."""

    @staticmethod
    def _message(index: int) -> ContextMessage:
        return ContextMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"message {index}",
        )

    async def test_compaction_keeps_recent_messages_and_writes_summary(self) -> None:
        memory = ConversationMemory(
            FakeRedis(),
            compress_at=4,
            retain_messages=2,
        )
        for index in range(4):
            await memory.add_message("user-1", "conversation-1", self._message(index))

        messages = await memory.get_messages("user-1", "conversation-1")
        summary = await memory.get_summary("user-1", "conversation-1")

        self.assertEqual(
            [message.content for message in messages],
            ["message 2", "message 3"],
        )
        self.assertTrue(summary)

    async def test_long_term_memory_is_added_to_context(self) -> None:
        long_term = RecordingLongTermMemory()
        memory = ConversationMemory(
            FakeRedis(),
            compress_at=4,
            retain_messages=2,
            long_term_memory=long_term,
        )
        for index in range(4):
            await memory.add_message("user-1", "conversation-1", self._message(index))
        await memory.update_profile(
            "user-1",
            "conversation-1",
            entities={"order_id": ["A-1001"]},
        )

        context = await memory.get_context(
            "user-1",
            "conversation-1",
            query="order status",
        )

        self.assertEqual(len(long_term.episodic), 1)
        self.assertTrue(context["episodic_memories"])
        self.assertEqual(
            context["user_profile"]["entities"]["order_id"],
            ["A-1001"],
        )

    async def test_redis_failure_is_not_silently_converted_to_empty_memory(self) -> None:
        memory = ConversationMemory(FailingReadRedis())

        with self.assertRaises(MemoryStoreError):
            await memory.get_context("user-1", "conversation-1", query="status")

    async def test_episodic_failure_does_not_hide_available_profile(self) -> None:
        long_term = EpisodicFailureLongTermMemory()
        long_term.profile["user-1"] = {
            "user_id": "user-1",
            "entities": {"order_id": ["A-1001"]},
        }
        memory = ConversationMemory(FakeRedis(), long_term_memory=long_term)

        context = await memory.get_context("user-1", "conversation-1", query="status")

        self.assertEqual(context["episodic_memories"], [])
        self.assertEqual(context["user_profile"]["user_id"], "user-1")


if __name__ == "__main__":
    unittest.main()
