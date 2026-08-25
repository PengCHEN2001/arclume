"""Redis-backed persistence for the structured AgentState model."""

from typing import Any

from schemas.state import AgentState

from memory import MemoryStoreError


class StateStore:
    """Save and restore the current structured state of one support case."""

    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = 86_400,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be at least one")

        self._redis = redis_client             # Async Redis-compatible client
        self.ttl_seconds = ttl_seconds         # State expiration time

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        ttl_seconds: int = 86_400,
    ) -> "StateStore":
        """Create a state store using the project's Redis URL."""

        try:
            import redis.asyncio as redis
        except ImportError as exc:
            raise MemoryStoreError(
                "Redis support is not installed. Install requirements.txt first."
            ) from exc

        return cls(
            redis.from_url(redis_url, decode_responses=True),
            ttl_seconds=ttl_seconds,
        )

    async def get(
        self,
        user_id: str,
        conversation_id: str,
    ) -> AgentState | None:
        """Restore one AgentState, or return None when no state exists."""

        try:
            raw_state = await self._redis.get(self._key(user_id, conversation_id))
        except Exception as exc:
            raise MemoryStoreError("Failed to load AgentState") from exc

        if raw_state is None:
            return None
        if isinstance(raw_state, bytes):
            raw_state = raw_state.decode("utf-8")

        try:
            return AgentState.model_validate_json(raw_state)
        except (TypeError, ValueError) as exc:
            raise MemoryStoreError("Stored AgentState has an invalid format") from exc

    async def get_or_create(
        self,
        user_id: str,
        conversation_id: str,
    ) -> AgentState:
        """Restore an existing state or create a new case state."""

        state = await self.get(user_id, conversation_id)
        return state or AgentState(
            user_id=user_id,
            conversation_id=conversation_id,
        )

    async def save(self, state: AgentState) -> None:
        """Serialize and save one AgentState with the configured TTL."""

        try:
            await self._redis.setex(
                self._key(state.user_id, state.conversation_id),
                self.ttl_seconds,
                state.model_dump_json(),
            )
        except Exception as exc:
            raise MemoryStoreError("Failed to save AgentState") from exc

    async def delete(self, user_id: str, conversation_id: str) -> None:
        """Delete one persisted AgentState."""

        try:
            await self._redis.delete(self._key(user_id, conversation_id))
        except Exception as exc:
            raise MemoryStoreError("Failed to delete AgentState") from exc

    async def close(self) -> None:
        """Close the underlying Redis client."""

        await self._redis.aclose()

    @staticmethod
    def _key(user_id: str, conversation_id: str) -> str:
        """Build a namespaced key that isolates users and conversations."""

        return f"arclume:state:{user_id}:{conversation_id}"
