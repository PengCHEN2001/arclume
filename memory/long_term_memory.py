"""ChromaDB-backed episodic memory and user-profile storage."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from memory import MemoryStoreError


logger = logging.getLogger(__name__)


class LongTermMemory:
    """Store durable conversation summaries and user profiles in ChromaDB."""

    EPISODIC_COLLECTION = "episodic"
    PROFILE_COLLECTION = "user_profile"

    def __init__(
        self,
        *,
        chroma_host: str = "localhost",
        chroma_port: int = 8001,
        local_path: str = "./data/chroma",
        allow_local_fallback: bool = False,
        client: Any | None = None,
        episodic_collection: Any | None = None,
        profile_collection: Any | None = None,
    ) -> None:
        self.chroma_host = chroma_host                  # ChromaDB server hostname
        self.chroma_port = chroma_port                  # ChromaDB server port
        self.local_path = local_path                    # Optional local persistence path
        self.allow_local_fallback = allow_local_fallback  # Whether local mode is allowed
        self._client = client                            # Injected or lazily created client
        self._episodic = episodic_collection             # Historical summary collection
        self._profile = profile_collection               # User profile collection
        self._mode: str | None = (
            "injected"
            if self._episodic is not None and self._profile is not None
            else None
        )

    @classmethod
    def from_environment(cls) -> "LongTermMemory":
        """Create a long-term memory adapter from the shared Chroma settings."""

        return cls(
            chroma_host=os.getenv("CHROMA_HOST", "localhost").strip(),
            chroma_port=int(os.getenv("CHROMA_PORT", "8001")),
            local_path=os.getenv("CHROMA_PERSIST_DIRECTORY", "./data/chroma").strip(),
            allow_local_fallback=os.getenv(
                "CHROMA_ALLOW_LOCAL_FALLBACK", "false"
            ).strip().lower() in {"1", "true", "yes"},
        )

    async def initialize_async(self) -> None:
        """Connect to ChromaDB and create the two long-term collections."""

        await asyncio.to_thread(self._ensure_collections)

    async def close(self) -> None:
        """Release resources when the application shuts down."""

        # ChromaDB's current clients do not expose a required async close call.
        return None

    @property
    def mode(self) -> str | None:
        """Expose the active ChromaDB mode for readiness reporting."""

        return self._mode

    async def add_episodic_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: str,
        *,
        full_text: str = "",
    ) -> str:
        """Persist one compressed conversation summary for later semantic recall."""

        clean_summary = self._clean_text(summary).strip()
        if not clean_summary:
            raise ValueError("Episodic summary cannot be empty")

        clean_user_id = self._clean_text(user_id).strip()
        clean_conversation_id = self._clean_text(conversation_id).strip()
        timestamp = datetime.now(timezone.utc).isoformat()
        document_id = "episodic:" + hashlib.sha256(
            f"{clean_user_id}:{clean_conversation_id}:{timestamp}:{clean_summary}".encode(
                "utf-8"
            )
        ).hexdigest()
        metadata = {
            "user_id": clean_user_id,
            "conversation_id": clean_conversation_id,
            "created_at": timestamp,
            "full_text": self._clean_text(full_text)[:500],
        }

        collection, _ = self._ensure_collections()
        try:
            await asyncio.to_thread(
                collection.upsert,
                ids=[document_id],
                documents=[clean_summary],
                metadatas=[metadata],
            )
        except Exception as exc:
            raise MemoryStoreError("Failed to save episodic memory") from exc
        return document_id

    async def search_episodic(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Retrieve semantically related historical summaries for one user."""

        clean_query = self._clean_text(query).strip()
        if not clean_query:
            return []

        safe_top_k = max(1, min(top_k, 20))
        collection, _ = self._ensure_collections()
        try:
            raw_results = await asyncio.to_thread(
                collection.query,
                query_texts=[clean_query],
                n_results=safe_top_k,
                where={"user_id": self._clean_text(user_id)},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise MemoryStoreError("Failed to search episodic memory") from exc

        return self._format_query_results(raw_results)

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """Load one stable user profile, or return an empty profile."""

        _, collection = self._ensure_collections()
        try:
            raw_result = await asyncio.to_thread(
                collection.get,
                ids=[self._profile_id(user_id)],
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            raise MemoryStoreError("Failed to load user profile") from exc

        documents = raw_result.get("documents") or []
        if not documents or not documents[0]:
            return {}
        try:
            value = json.loads(documents[0])
        except (TypeError, ValueError) as exc:
            raise MemoryStoreError("Stored user profile has an invalid format") from exc
        return value if isinstance(value, dict) else {}

    async def update_user_profile(
        self,
        user_id: str,
        *,
        entities: dict[str, Any] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> None:
        """Merge structured profile updates and upsert one profile document."""

        clean_user_id = self._clean_text(user_id).strip()
        current = await self.get_user_profile(clean_user_id)
        current_entities = current.get("entities")
        current_preferences = current.get("preferences")
        merged_entities = dict(current_entities) if isinstance(current_entities, dict) else {}
        merged_preferences = (
            dict(current_preferences)
            if isinstance(current_preferences, dict)
            else {}
        )
        if entities:
            merged_entities.update(self._clean_mapping(entities))
        if preferences:
            merged_preferences.update(self._clean_mapping(preferences))

        profile = {
            "user_id": clean_user_id,
            "entities": merged_entities,
            "preferences": merged_preferences,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        document = json.dumps(profile, ensure_ascii=False, default=str)
        _, collection = self._ensure_collections()
        try:
            await asyncio.to_thread(
                collection.upsert,
                ids=[self._profile_id(clean_user_id)],
                documents=[document],
                metadatas=[
                    {
                        "user_id": clean_user_id,
                        "updated_at": profile["updated_at"],
                    }
                ],
            )
        except Exception as exc:
            raise MemoryStoreError("Failed to save user profile") from exc

    def _ensure_collections(self) -> tuple[Any, Any]:
        """Create the ChromaDB client and long-term collections on first use."""

        if self._episodic is not None and self._profile is not None:
            return self._episodic, self._profile

        try:
            import chromadb

            if self._client is None:
                try:
                    self._client = chromadb.HttpClient(
                        host=self.chroma_host,
                        port=self.chroma_port,
                        settings=chromadb.Settings(anonymized_telemetry=False),
                    )
                    self._client.heartbeat()
                    self._mode = "server"
                except Exception as server_error:
                    if not self.allow_local_fallback:
                        raise MemoryStoreError(
                            f"ChromaDB server is unavailable at "
                            f"{self.chroma_host}:{self.chroma_port}"
                        ) from server_error
                    self._client = chromadb.PersistentClient(
                        path=self.local_path,
                        # HttpClient mutates its Settings instance into a server
                        # configuration. Local fallback needs a fresh instance.
                        settings=chromadb.Settings(anonymized_telemetry=False),
                    )
                    self._mode = "local"
                    logger.warning(
                        "Using local ChromaDB persistence for long-term memory at %s",
                        self.local_path,
                    )

            self._episodic = self._client.get_or_create_collection(
                name=self.EPISODIC_COLLECTION,
                metadata={"description": "Arclume compressed conversation memory"},
            )
            self._profile = self._client.get_or_create_collection(
                name=self.PROFILE_COLLECTION,
                metadata={"description": "Arclume user profile memory"},
            )
            return self._episodic, self._profile
        except MemoryStoreError:
            raise
        except Exception as exc:
            raise MemoryStoreError(f"Failed to initialize long-term memory: {exc}") from exc

    @staticmethod
    def _format_query_results(raw_results: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize one ChromaDB query response for ContextBuilder."""

        documents = raw_results.get("documents") or [[]]
        metadatas = raw_results.get("metadatas") or [[]]
        distances = raw_results.get("distances") or [[]]
        first_documents = documents[0] if isinstance(documents[0], list) else documents
        first_metadatas = metadatas[0] if isinstance(metadatas[0], list) else metadatas
        first_distances = distances[0] if isinstance(distances[0], list) else distances

        items: list[dict[str, Any]] = []
        for index, document in enumerate(first_documents or []):
            if not isinstance(document, str) or not document.strip():
                continue
            metadata = (
                first_metadatas[index]
                if index < len(first_metadatas) and isinstance(first_metadatas[index], dict)
                else {}
            )
            distance = first_distances[index] if index < len(first_distances) else None
            score = None
            if distance is not None:
                score = round(max(0.0, min(1.0, 1.0 - float(distance))), 4)
            items.append(
                {
                    "content": document,
                    "summary": document,
                    "score": score,
                    "metadata": metadata,
                    "source": "episodic",
                }
            )
        return items

    @classmethod
    def _profile_id(cls, user_id: str) -> str:
        """Build a stable ChromaDB document ID without exposing raw user input."""

        digest = hashlib.sha256(cls._clean_text(user_id).encode("utf-8")).hexdigest()
        return f"profile:{digest}"

    @classmethod
    def _clean_mapping(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Keep profile values JSON-safe and remove invalid text characters."""

        return {
            cls._clean_text(key): cls._clean_value(item)
            for key, item in value.items()
        }

    @classmethod
    def _clean_value(cls, value: Any) -> Any:
        """Recursively normalize values before they enter persistent storage."""

        if isinstance(value, str):
            return cls._clean_text(value)
        if isinstance(value, dict):
            return cls._clean_mapping(value)
        if isinstance(value, list):
            return [cls._clean_value(item) for item in value]
        return value

    @staticmethod
    def _clean_text(value: Any) -> str:
        """Normalize text to valid UTF-8 without changing its meaning."""

        if value is None:
            return ""
        return str(value).encode("utf-8", errors="ignore").decode("utf-8")
