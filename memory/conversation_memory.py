"""Redis-backed short-term conversation memory."""

from datetime import datetime, timezone
import json
from typing import Any

from schemas.context import ContextMessage

from memory import MemoryStoreError


class ConversationMemory:
    """Store recent messages for one user conversation in Redis."""

    def __init__(
        self,
        redis_client: Any,
        *,
        max_messages: int = 20,
        ttl_seconds: int = 86_400,
    ) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be at least one")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be at least one")

        self._redis = redis_client                 # Async Redis-compatible client
        self.max_messages = max_messages           # Maximum messages kept per conversation
        self.ttl_seconds = ttl_seconds             # Conversation expiration time

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        max_messages: int = 20,
        ttl_seconds: int = 86_400,
    ) -> "ConversationMemory":
        """Create a memory store using the project's Redis URL."""

        try:
            import redis.asyncio as redis
        except ImportError as exc:
            raise MemoryStoreError(
                "Redis support is not installed. Install requirements.txt first."
            ) from exc

        return cls(
            redis.from_url(redis_url, decode_responses=True),
            max_messages=max_messages,
            ttl_seconds=ttl_seconds,
        )

    async def add_message(
        self,
        user_id: str,
        conversation_id: str,
        message: ContextMessage,
    ) -> None:
        """Append one message and keep only the newest configured messages."""

        key = self._key(user_id, conversation_id)
        payload = json.dumps(
            {
                "role": message.role,
                "content": message.content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        try:
            await self._redis.lpush(key, payload)
            await self._redis.ltrim(key, 0, self.max_messages - 1)
            await self._redis.expire(key, self.ttl_seconds)
        except Exception as exc:
            raise MemoryStoreError("Failed to save conversation message") from exc

    async def get_messages(
        self,
        user_id: str,
        conversation_id: str,
    ) -> list[ContextMessage]:
        """Return recent messages in chronological order."""

        key = self._key(user_id, conversation_id)
        try:
            raw_messages = await self._redis.lrange(
                key,
                0,
                self.max_messages - 1,
            )
        except Exception as exc:
            raise MemoryStoreError("Failed to load conversation messages") from exc

        messages: list[ContextMessage] = []
        for raw_message in reversed(raw_messages):
            try:
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8")
                data = json.loads(raw_message)
                messages.append(
                    ContextMessage(
                        role=data["role"],
                        content=data["content"],
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryStoreError(
                    "Stored conversation message has an invalid format"
                ) from exc

        return messages

    async def clear(self, user_id: str, conversation_id: str) -> None:
        """Delete all short-term messages for one conversation."""

        try:
            await self._redis.delete(self._key(user_id, conversation_id))
        except Exception as exc:
            raise MemoryStoreError("Failed to clear conversation messages") from exc

    async def close(self) -> None:
        """Close the underlying Redis client."""

        await self._redis.aclose()

    @staticmethod
    def _key(user_id: str, conversation_id: str) -> str:
        """Build a namespaced key that isolates users and conversations."""

        return f"arclume:conversation:{user_id}:{conversation_id}"
