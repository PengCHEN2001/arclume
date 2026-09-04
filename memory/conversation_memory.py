"""Redis-backed working memory with optional long-term memory integration."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from memory import MemoryStoreError
from memory.long_term_memory import LongTermMemory
from schemas.context import ContextMessage


logger = logging.getLogger(__name__)

SummaryFunction = Callable[[str, str], Awaitable[str]]


class ConversationMemory:
    """Manage Redis working memory and the current conversation summary."""

    def __init__(
        self,
        redis_client: Any,
        *,
        max_messages: int = 20,
        ttl_seconds: int = 86_400,
        compress_at: int = 15,
        retain_messages: int = 5,
        summary_ttl_seconds: int = 86_400,
        llm: Any | None = None,
        long_term_memory: LongTermMemory | None = None,
        llm_summary_enabled: bool = False,
        episodic_top_k: int = 3,
        summary_max_chars: int = 800,
        summarizer: SummaryFunction | None = None,
    ) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be at least one")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be at least one")
        if compress_at < 2:
            raise ValueError("compress_at must be at least two")
        if retain_messages < 1 or retain_messages >= compress_at:
            raise ValueError("retain_messages must be smaller than compress_at")
        if summary_ttl_seconds < 1:
            raise ValueError("summary_ttl_seconds must be at least one")
        if episodic_top_k < 1:
            raise ValueError("episodic_top_k must be at least one")
        if summary_max_chars < 100:
            raise ValueError("summary_max_chars must be at least 100")

        self._redis = redis_client                 # Async Redis-compatible client
        self.max_messages = max_messages           # Maximum working-memory messages
        self.ttl_seconds = ttl_seconds             # Working-memory expiration time
        self.compress_at = compress_at             # Message count that triggers compaction
        self.retain_messages = retain_messages     # Recent messages kept after compaction
        self.summary_ttl_seconds = summary_ttl_seconds  # Summary expiration time
        self.llm = llm                             # Optional provider-neutral model client
        self.long_term_memory = long_term_memory   # Optional ChromaDB memory adapter
        self.llm_summary_enabled = llm_summary_enabled  # Extra model-call switch
        self.episodic_top_k = episodic_top_k       # Historical summaries returned per query
        self.summary_max_chars = summary_max_chars # Maximum Redis summary size
        self.summarizer = summarizer               # Injectable summary function for tests

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        max_messages: int = 20,
        ttl_seconds: int = 86_400,
        compress_at: int = 15,
        retain_messages: int = 5,
        summary_ttl_seconds: int = 86_400,
        llm: Any | None = None,
        long_term_memory: LongTermMemory | None = None,
        llm_summary_enabled: bool = False,
        episodic_top_k: int = 3,
        summary_max_chars: int = 800,
    ) -> "ConversationMemory":
        """Create working memory using the project's Redis URL."""

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
            compress_at=compress_at,
            retain_messages=retain_messages,
            summary_ttl_seconds=summary_ttl_seconds,
            llm=llm,
            long_term_memory=long_term_memory,
            llm_summary_enabled=llm_summary_enabled,
            episodic_top_k=episodic_top_k,
            summary_max_chars=summary_max_chars,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        redis_url: str | None = None,
        llm: Any | None = None,
        long_term_memory: LongTermMemory | None = None,
    ) -> "ConversationMemory":
        """Create working memory from environment-based runtime settings."""

        return cls.from_url(
            redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            max_messages=cls._env_int("ARCLUME_MEMORY_MAX_MESSAGES", 20, minimum=1),
            ttl_seconds=cls._env_int(
                "ARCLUME_MEMORY_TTL_SECONDS", 86_400, minimum=1
            ),
            compress_at=cls._env_int(
                "ARCLUME_MEMORY_COMPRESS_AT", 15, minimum=2
            ),
            retain_messages=cls._env_int(
                "ARCLUME_MEMORY_RETAIN_MESSAGES", 5, minimum=1
            ),
            summary_ttl_seconds=cls._env_int(
                "ARCLUME_MEMORY_SUMMARY_TTL_SECONDS", 86_400, minimum=1
            ),
            llm=llm,
            long_term_memory=long_term_memory,
            llm_summary_enabled=cls._env_bool(
                "ARCLUME_MEMORY_LLM_ENABLED", False
            ),
            episodic_top_k=cls._env_int(
                "ARCLUME_MEMORY_EPISODIC_TOP_K", 3, minimum=1, maximum=20
            ),
            summary_max_chars=cls._env_int(
                "ARCLUME_MEMORY_SUMMARY_MAX_CHARS", 800, minimum=100
            ),
        )

    async def add_message(
        self,
        user_id: str,
        conversation_id: str,
        message: ContextMessage,
        *,
        compact: bool = True,
    ) -> None:
        """Append one message and optionally compact working memory."""

        key = self._working_key(user_id, conversation_id)
        payload = json.dumps(
            {
                "role": message.role,
                "content": message.content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )

        try:
            await self._redis.lpush(key, payload)
            await self._redis.ltrim(key, 0, self.max_messages - 1)
            await self._redis.expire(key, self.ttl_seconds)
            if compact:
                await self._maybe_compact(user_id, conversation_id)
        except MemoryStoreError:
            raise
        except Exception as exc:
            raise MemoryStoreError("Failed to save conversation message") from exc

    async def get_messages(
        self,
        user_id: str,
        conversation_id: str,
    ) -> list[ContextMessage]:
        """Return working-memory messages in chronological order."""

        key = self._working_key(user_id, conversation_id)
        try:
            raw_messages = await self._redis.lrange(key, 0, self.max_messages - 1)
        except Exception as exc:
            raise MemoryStoreError("Failed to load conversation messages") from exc
        return self._parse_messages(raw_messages)

    async def get_summary(self, user_id: str, conversation_id: str) -> str:
        """Return the current Redis summary for one conversation."""

        try:
            summary = await self._redis.get(self._summary_key(user_id, conversation_id))
        except Exception as exc:
            raise MemoryStoreError("Failed to load conversation summary") from exc
        if isinstance(summary, bytes):
            summary = summary.decode("utf-8")
        return str(summary or "")

    async def get_context(
        self,
        user_id: str,
        conversation_id: str,
        *,
        query: str = "",
        episodic_top_k: int | None = None,
    ) -> dict[str, Any]:
        """Load working memory, summary, episodic memory, and user profile."""

        recent_messages = await self.get_messages(user_id, conversation_id)
        summary = await self.get_summary(user_id, conversation_id)
        episodic_memories: list[dict[str, Any]] = []
        user_profile: dict[str, Any] = {}

        if self.long_term_memory is not None:
            search_query = query.strip() or (
                recent_messages[-1].content if recent_messages else ""
            )
            if search_query:
                try:
                    episodic_memories = await self.long_term_memory.search_episodic(
                        user_id,
                        search_query,
                        top_k=episodic_top_k or self.episodic_top_k,
                    )
                except MemoryStoreError as exc:
                    # Episodic recall is optional and can fail independently.
                    logger.warning("Episodic memory read skipped: %s", exc)
            try:
                user_profile = await self.long_term_memory.get_user_profile(user_id)
            except MemoryStoreError as exc:
                # User profiles are optional and can fail independently.
                logger.warning("User profile read skipped: %s", exc)

        return {
            "recent_messages": recent_messages,
            "summary": summary,
            "episodic_memories": episodic_memories,
            "user_profile": user_profile,
        }

    async def update_profile(
        self,
        user_id: str,
        conversation_id: str,
        *,
        message: str = "",
        entities: dict[str, Any] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> None:
        """Persist structured profile facts without blocking the chat on failure."""

        if self.long_term_memory is None:
            return

        extracted_preferences: dict[str, Any] = dict(preferences or {})
        extracted_entities: dict[str, Any] = dict(entities or {})
        if self.llm_summary_enabled and self._llm_is_configured() and message.strip():
            try:
                llm_updates = await self._extract_profile_updates(message)
                extracted_preferences.update(llm_updates.get("preferences", {}))
                extracted_entities.update(llm_updates.get("entities", {}))
            except Exception as exc:
                logger.warning("Optional profile extraction skipped: %s", exc)

        try:
            await self.long_term_memory.update_user_profile(
                user_id,
                entities=extracted_entities,
                preferences=extracted_preferences,
            )
        except MemoryStoreError as exc:
            logger.warning(
                "User profile update skipped for %s/%s: %s",
                user_id,
                conversation_id,
                exc,
            )

    async def clear(self, user_id: str, conversation_id: str) -> None:
        """Delete working memory and the current-session summary."""

        try:
            await self._redis.delete(
                self._working_key(user_id, conversation_id),
                self._summary_key(user_id, conversation_id),
            )
        except Exception as exc:
            raise MemoryStoreError("Failed to clear conversation memory") from exc

    async def close(self) -> None:
        """Close the underlying Redis client."""

        await self._redis.aclose()

    async def _maybe_compact(self, user_id: str, conversation_id: str) -> None:
        """Compact old messages after the configured threshold is reached."""

        key = self._working_key(user_id, conversation_id)
        count = await self._redis.llen(key)
        if count < self.compress_at:
            return

        raw_messages = await self._redis.lrange(key, 0, -1)
        messages = self._parse_messages(raw_messages)
        if len(messages) < self.compress_at:
            return

        to_compact = messages[:-self.retain_messages]
        keep = messages[-self.retain_messages:]
        old_summary = await self.get_summary(user_id, conversation_id)
        compacted_summary = await self._summarize(to_compact, old_summary)

        await self._redis.setex(
            self._summary_key(user_id, conversation_id),
            self.summary_ttl_seconds,
            compacted_summary,
        )

        if self.long_term_memory is not None:
            full_text = self._messages_text(to_compact)
            try:
                await self.long_term_memory.add_episodic_summary(
                    user_id,
                    conversation_id,
                    compacted_summary,
                    full_text=full_text,
                )
            except MemoryStoreError as exc:
                # Redis still controls the active conversation when ChromaDB is down.
                logger.warning("Episodic memory write skipped: %s", exc)

        await self._redis.delete(key)
        for message in keep:
            await self._redis.lpush(key, self._message_json(message))
        await self._redis.expire(key, self.ttl_seconds)
        logger.info(
            "Working memory compacted for %s/%s; retained %s messages",
            user_id,
            conversation_id,
            len(keep),
        )

    async def _summarize(
        self,
        messages: list[ContextMessage],
        old_summary: str,
    ) -> str:
        """Create a bounded summary with an optional model and safe local fallback."""

        source_text = self._messages_text(messages)
        if self.summarizer is not None:
            try:
                value = await self.summarizer(source_text, old_summary)
                if value.strip():
                    return value.strip()[: self.summary_max_chars]
            except Exception as exc:
                logger.warning("Injected summary function failed: %s", exc)

        if self.llm_summary_enabled and self._llm_is_configured():
            prompt = (
                "Summarize the support conversation for future turns. Preserve "
                "verified facts, important entities, user preferences, unresolved "
                "issues, and pending next steps. Do not invent facts. Return only "
                f"the summary, under {self.summary_max_chars} characters.\n\n"
                f"Previous summary:\n{old_summary}\n\nMessages to compact:\n{source_text}"
            )
            try:
                result = await self.llm.chat(
                    prompt,
                    system_prompt="You create concise, factual conversation summaries.",
                )
                if result.strip():
                    return result.strip()[: self.summary_max_chars]
            except Exception as exc:
                logger.warning("Model summary failed; using local compaction: %s", exc)

        # This fallback preserves source facts without spending an extra model call.
        pieces = []
        if old_summary.strip():
            pieces.append(f"Previous summary: {old_summary.strip()}")
        pieces.append(source_text)
        return "\n".join(pieces).strip()[-self.summary_max_chars :]

    async def _extract_profile_updates(self, message: str) -> dict[str, dict[str, Any]]:
        """Optionally extract explicit preferences and entities from one message."""

        prompt = (
            "Extract only explicit user preferences and stable entities from the "
            "message below. Return valid JSON with object keys preferences and "
            "entities. Use empty objects when there is no reliable fact. Do not "
            "infer sensitive information.\n\nMessage:\n" + message
        )
        raw = await self.llm.chat(
            prompt,
            system_prompt="You extract conservative, user-provided profile facts as JSON.",
        )
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {"preferences": {}, "entities": {}}
        value = json.loads(raw[start : end + 1])
        if not isinstance(value, dict):
            return {"preferences": {}, "entities": {}}
        return {
            "preferences": value.get("preferences")
            if isinstance(value.get("preferences"), dict)
            else {},
            "entities": value.get("entities")
            if isinstance(value.get("entities"), dict)
            else {},
        }

    def _llm_is_configured(self) -> bool:
        """Check optional model readiness without requiring a concrete client type."""

        return bool(self.llm and getattr(self.llm, "is_configured", False))

    @staticmethod
    def _parse_messages(raw_messages: list[Any]) -> list[ContextMessage]:
        """Decode Redis messages and restore chronological order."""

        messages: list[ContextMessage] = []
        for raw_message in reversed(raw_messages):
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")
            try:
                data = json.loads(raw_message)
                messages.append(
                    ContextMessage(
                        role=data["role"],
                        content=data["content"],
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise MemoryStoreError(
                    "Stored conversation message has an invalid format"
                ) from exc
        return messages

    @staticmethod
    def _message_json(message: ContextMessage) -> str:
        """Serialize a normalized message for Redis list storage."""

        return json.dumps(
            {
                "role": message.role,
                "content": message.content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _messages_text(messages: list[ContextMessage]) -> str:
        """Render messages into bounded plain text for summarization."""

        return "\n".join(
            f"{message.role}: {message.content}" for message in messages
        )

    @staticmethod
    def _working_key(user_id: str, conversation_id: str) -> str:
        """Build a namespaced Redis key for recent working memory."""

        return f"arclume:conversation:{user_id}:{conversation_id}"

    @staticmethod
    def _summary_key(user_id: str, conversation_id: str) -> str:
        """Build a namespaced Redis key for the current conversation summary."""

        return f"arclume:summary:{user_id}:{conversation_id}"

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        """Read a boolean environment setting."""

        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _env_int(
        name: str,
        default: int,
        *,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        """Read and clamp an integer environment setting."""

        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            value = default
        value = max(minimum, value)
        return min(value, maximum) if maximum is not None else value
