"""ChromaDB-backed document ingestion and semantic retrieval."""

import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

from knowledge import KnowledgeBaseError, KnowledgeBaseUnavailable


logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Manage the document collection used by the RAG stage."""

    COLLECTION_NAME = "knowledge_base"
    SUPPORTED_SUFFIXES = {".md", ".txt", ".json"}

    def __init__(
        self,
        *,
        chroma_host: str = "localhost",
        chroma_port: int = 8001,
        local_path: str = "./data/chroma",
        allow_local_fallback: bool = False,
        chunk_size: int = 500,
        client: Any | None = None,
        collection: Any | None = None,
    ) -> None:
        self.chroma_host = chroma_host              # ChromaDB server hostname
        self.chroma_port = chroma_port              # ChromaDB server port
        self.local_path = local_path                # Optional local persistence path
        self.allow_local_fallback = allow_local_fallback  # Whether local mode is allowed
        self.chunk_size = chunk_size                # Approximate characters per chunk
        self._client = client                       # Injected or lazily created client
        self._collection = collection               # Injected or lazily opened collection
        self._mode: str | None = "injected" if collection is not None else None

    @classmethod
    def from_environment(cls) -> "KnowledgeBase":
        """Create a knowledge base from the current process environment."""

        return cls(
            chroma_host=os.getenv("CHROMA_HOST", "localhost").strip(),
            chroma_port=int(os.getenv("CHROMA_PORT", "8001")),
            local_path=os.getenv("CHROMA_PERSIST_DIRECTORY", "./data/chroma").strip(),
            allow_local_fallback=os.getenv(
                "CHROMA_ALLOW_LOCAL_FALLBACK", "false"
            ).strip().lower() in {"1", "true", "yes"},
            chunk_size=int(os.getenv("CHROMA_CHUNK_SIZE", "500")),
        )

    async def initialize_async(self) -> None:
        """Connect to ChromaDB and import bundled documents when the collection is empty."""

        await asyncio.to_thread(self._initialize)

    async def close(self) -> None:
        """Release client resources when the application shuts down."""

        # The ChromaDB client currently does not require an async close call.
        return None

    def add_documents(self, documents: Iterable[dict[str, str]]) -> int:
        """Chunk and idempotently upsert documents into the collection."""

        collection = self._ensure_collection()
        ids: list[str] = []
        texts: list[str] = []
        metadata: list[dict[str, str | int]] = []

        for document in documents:
            title = document.get("title", "").strip()
            content = document.get("content", "").strip()
            source = document.get("source", title).strip()
            if not content:
                continue

            chunks = self._chunk_text(content)
            for index, chunk in enumerate(chunks):
                chunk_id = self._chunk_id(source, index, chunk)
                ids.append(chunk_id)
                texts.append(chunk)
                metadata.append(
                    {
                        "title": title,
                        "source": source,
                        "chunk_index": index,
                        "total_chunks": len(chunks),
                    }
                )

        if not ids:
            return 0

        # Upsert makes re-indexing safe when the same source is loaded again.
        collection.upsert(ids=ids, documents=texts, metadatas=metadata)
        logger.info("Indexed %s knowledge chunks", len(ids))
        return len(ids)

    async def add_documents_async(self, documents: Iterable[dict[str, str]]) -> int:
        """Run synchronous ChromaDB writes outside the event loop."""

        return await asyncio.to_thread(self.add_documents, list(documents))

    def add_directory(self, directory: str | Path) -> int:
        """Read supported text files from a directory and index their contents."""

        path = Path(directory)
        if not path.exists():
            raise KnowledgeBaseError(f"Knowledge directory does not exist: {path}")
        if not path.is_dir():
            raise KnowledgeBaseError(f"Knowledge path is not a directory: {path}")

        documents: list[dict[str, str]] = []
        for file_path in sorted(path.iterdir()):
            if not file_path.is_file() or file_path.suffix.lower() not in self.SUPPORTED_SUFFIXES:
                continue
            documents.append(
                {
                    "title": file_path.stem.replace("_", " ").title(),
                    "source": str(file_path),
                    "content": self._read_document(file_path),
                }
            )
        return self.add_documents(documents)

    async def add_directory_async(self, directory: str | Path) -> int:
        """Run directory ingestion outside the event loop."""

        return await asyncio.to_thread(self.add_directory, directory)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Return the most similar knowledge chunks for one user query."""

        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("Knowledge query cannot be empty")

        collection = self._ensure_collection()
        safe_top_k = max(1, min(top_k, 20))  # Keep retrieval cost bounded
        results = collection.query(query_texts=[cleaned_query], n_results=safe_top_k)

        documents = results.get("documents") or [[]]
        metadatas = results.get("metadatas") or [[]]
        distances = results.get("distances") or [[]]
        items: list[dict[str, Any]] = []

        for index, document in enumerate(documents[0] or []):
            metadata = (metadatas[0] or [{}])[index] or {}
            distance = (distances[0] or [None])[index]
            score = None if distance is None else max(0.0, min(1.0, 1.0 - float(distance)))
            items.append(
                {
                    "title": metadata.get("title", ""),
                    "source": metadata.get("source", ""),
                    "content": document,
                    "score": None if score is None else round(score, 4),
                    "chunk": metadata.get("chunk_index", 0),
                }
            )
        return items

    async def search_async(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Run synchronous ChromaDB retrieval outside the event loop."""

        return await asyncio.to_thread(self.search, query, top_k)

    @property
    def doc_count(self) -> int:
        """Return the number of indexed document chunks."""

        return self._ensure_collection().count()

    async def doc_count_async(self) -> int:
        """Return the chunk count without blocking the event loop."""

        return await asyncio.to_thread(lambda: self.doc_count)

    @property
    def mode(self) -> str | None:
        """Expose whether the backend uses the server or local mode."""

        return self._mode

    def _initialize(self) -> None:
        """Open the collection and load demo documents only when it is empty."""

        collection = self._ensure_collection()
        if collection.count() == 0:
            demo_directory = Path("data/demo_docs")
            if demo_directory.exists():
                self.add_directory(demo_directory)

    def _ensure_collection(self) -> Any:
        """Create the ChromaDB client and collection on first use."""

        if self._collection is not None:
            return self._collection

        try:
            import chromadb

            settings = chromadb.Settings(anonymized_telemetry=False)
            try:
                self._client = chromadb.HttpClient(
                    host=self.chroma_host,
                    port=self.chroma_port,
                    settings=settings,
                )
                self._client.heartbeat()
                self._mode = "server"
            except Exception as server_error:
                if not self.allow_local_fallback:
                    raise KnowledgeBaseUnavailable(
                        f"ChromaDB server is unavailable at "
                        f"{self.chroma_host}:{self.chroma_port}"
                    ) from server_error
                self._client = chromadb.PersistentClient(
                    path=self.local_path,
                    settings=settings,
                )
                self._mode = "local"
                logger.warning("Using local ChromaDB persistence at %s", self.local_path)

            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "Arclume customer-support knowledge"},
            )
            return self._collection
        except KnowledgeBaseUnavailable:
            raise
        except Exception as exc:
            raise KnowledgeBaseError(f"Failed to initialize ChromaDB: {exc}") from exc

    @staticmethod
    def _chunk_id(source: str, index: int, content: str) -> str:
        """Create a stable ID so repeated indexing does not duplicate chunks."""

        raw = f"{source}:{index}:{content}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _chunk_text(self, text: str) -> list[str]:
        """Split text near sentence boundaries and hard-wrap oversized sentences."""

        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        if len(normalized) <= self.chunk_size:
            return [normalized]

        sentences = re.split(r"(?<=[。！？.!?])\s+", normalized)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > self.chunk_size:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(
                    sentence[start : start + self.chunk_size]
                    for start in range(0, len(sentence), self.chunk_size)
                )
                continue

            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > self.chunk_size:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _read_document(path: Path) -> str:
        """Read text and flatten JSON documents into searchable text."""

        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() != ".json":
            return text
        try:
            return json.dumps(json.loads(text), ensure_ascii=False)
        except json.JSONDecodeError:
            return text
