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
        chunk_overlap: int | None = None,
        client: Any | None = None,
        collection: Any | None = None,
    ) -> None:
        if chunk_size < 20:
            raise ValueError("Knowledge chunk size must be at least 20 characters")
        if chunk_overlap is not None and not 0 <= chunk_overlap < chunk_size:
            raise ValueError("Knowledge chunk overlap must be smaller than chunk size")
        self.chroma_host = chroma_host              # ChromaDB server hostname
        self.chroma_port = chroma_port              # ChromaDB server port
        self.local_path = local_path                # Optional local persistence path
        self.allow_local_fallback = allow_local_fallback  # Whether local mode is allowed
        self.chunk_size = chunk_size                # Maximum characters per chunk
        self.chunk_overlap = min(50, chunk_size // 5) if chunk_overlap is None else chunk_overlap
        self._client = client                       # Injected or lazily created client
        self._collection = collection               # Injected or lazily opened collection
        self._mode: str | None = "injected" if collection is not None else None
        self._revision = 0                          # Changes since the dense corpus was loaded

    @classmethod
    def from_environment(cls) -> "KnowledgeBase":
        """Create a knowledge base from the current process environment."""

        overlap = os.getenv("CHROMA_CHUNK_OVERLAP")
        return cls(
            chroma_host=os.getenv("CHROMA_HOST", "localhost").strip(),
            chroma_port=int(os.getenv("CHROMA_PORT", "8001")),
            local_path=os.getenv("CHROMA_PERSIST_DIRECTORY", "./data/chroma").strip(),
            allow_local_fallback=os.getenv(
                "CHROMA_ALLOW_LOCAL_FALLBACK", "false"
            ).strip().lower() in {"1", "true", "yes"},
            chunk_size=int(os.getenv("CHROMA_CHUNK_SIZE", "500")),
            chunk_overlap=int(overlap) if overlap is not None else None,
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
        self._revision += 1
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
        ids = results.get("ids") or [[]]
        first_ids = ids[0] if ids and isinstance(ids[0], list) else ids
        items: list[dict[str, Any]] = []

        for index, document in enumerate(documents[0] or []):
            metadata = (metadatas[0] or [{}])[index] or {}
            distance = (distances[0] or [None])[index]
            chunk_id = first_ids[index] if index < len(first_ids) else None
            score = None if distance is None else max(0.0, min(1.0, 1.0 - float(distance)))
            items.append(
                {
                    "chunk_id": chunk_id,
                    "title": metadata.get("title", ""),
                    "source": metadata.get("source", ""),
                    "content": document,
                    "score": None if score is None else round(score, 4),
                    "chunk": metadata.get("chunk_index", 0),
                }
            )
        return items

    def get_indexed_chunks(self) -> list[dict[str, Any]]:
        """Return the complete chunk corpus used to build the BM25 index."""

        collection = self._ensure_collection()
        try:
            raw = collection.get(include=["documents", "metadatas"])
        except Exception as exc:
            raise KnowledgeBaseError("Failed to load indexed knowledge chunks") from exc

        documents = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []
        ids = raw.get("ids") or []
        chunks: list[dict[str, Any]] = []
        for index, content in enumerate(documents):
            if not isinstance(content, str) or not content.strip():
                continue
            metadata = metadatas[index] if index < len(metadatas) else {}
            metadata = metadata if isinstance(metadata, dict) else {}
            chunk_id = ids[index] if index < len(ids) else None
            if not chunk_id:
                chunk_id = self._chunk_id(
                    str(metadata.get("source", "")),
                    int(metadata.get("chunk_index", 0)),
                    content,
                )
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "title": metadata.get("title", ""),
                    "source": metadata.get("source", ""),
                    "content": content,
                    "chunk": metadata.get("chunk_index", 0),
                    "total_chunks": metadata.get("total_chunks", 1),
                }
            )
        return chunks

    async def get_indexed_chunks_async(self) -> list[dict[str, Any]]:
        """Load the complete chunk corpus without blocking the event loop."""

        return await asyncio.to_thread(self.get_indexed_chunks)

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

    @property
    def revision(self) -> int:
        """Expose the local corpus revision for dependent lexical indexes."""

        return self._revision

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
                    raise KnowledgeBaseUnavailable(
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
        """Chunk English support documents by headings and paragraphs first.

        A size limit only splits oversized paragraphs. Adjacent chunks in the
        same section share a short word-aligned tail; section boundaries never
        overlap, so a refund paragraph cannot leak into an unrelated section.
        """

        sections: list[tuple[list[str], list[str]]] = []
        headings: list[tuple[int, str]] = []
        paragraphs: list[str] = []
        paragraph_lines: list[str] = []

        def finish_paragraph() -> None:
            if paragraph_lines:
                paragraphs.append("\n".join(paragraph_lines))
                paragraph_lines.clear()

        def finish_section() -> None:
            finish_paragraph()
            if paragraphs:
                sections.append(([heading for _, heading in headings], list(paragraphs)))
                paragraphs.clear()

        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = re.sub(r"[ \t]+", " ", raw_line).strip()
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                finish_section()
                level = len(heading_match.group(1))
                headings = [(depth, heading) for depth, heading in headings if depth < level]
                headings.append((level, line))
            elif line:
                paragraph_lines.append(line)
            else:
                finish_paragraph()
        finish_section()

        if not sections:
            heading_text = "\n".join(heading for _, heading in headings)
            return [heading_text[: self.chunk_size]] if heading_text else []

        chunks: list[str] = []
        for section_headings, section_paragraphs in sections:
            prefix = "\n".join(section_headings)
            if len(prefix) > self.chunk_size // 3:
                prefix = section_headings[-1][: self.chunk_size // 3]
            separator = "\n\n" if prefix else ""
            body_limit = self.chunk_size - len(prefix) - len(separator)
            body = ""

            for paragraph in section_paragraphs:
                fragment_limit = max(1, body_limit - self.chunk_overlap - 2)
                fragments = (
                    [paragraph]
                    if len(paragraph) <= body_limit
                    else self._split_long_paragraph(paragraph, fragment_limit)
                )
                for fragment in fragments:
                    candidate = f"{body}\n\n{fragment}" if body else fragment
                    if len(candidate) <= body_limit:
                        body = candidate
                        continue
                    if body:
                        chunks.append(prefix + separator + body)
                    overlap = self._overlap_tail(body, self.chunk_overlap)
                    with_overlap = f"{overlap}\n\n{fragment}" if overlap else fragment
                    body = with_overlap if len(with_overlap) <= body_limit else fragment

            if body:
                chunks.append(prefix + separator + body)
        return chunks

    @staticmethod
    def _split_long_paragraph(text: str, limit: int) -> list[str]:
        """Prefer an English sentence end, then a word boundary, then a hard cut."""

        fragments: list[str] = []
        remaining = text.strip()
        while len(remaining) > limit:
            window = remaining[: limit + 1]
            sentence_ends = [
                match.end()
                for match in re.finditer(r"[.!?][\"')\]]?\s+", window)
                if match.end() >= limit // 2
            ]
            cut = sentence_ends[-1] if sentence_ends else window.rfind(" ", 0, limit + 1)
            if cut <= 0:
                cut = limit
            fragments.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            fragments.append(remaining)
        return fragments

    @staticmethod
    def _overlap_tail(text: str, max_chars: int) -> str:
        """Carry a bounded, word-aligned suffix into the next chunk."""

        if not text or max_chars <= 0:
            return ""
        tail = text[-max_chars:]
        if len(text) > max_chars:
            first_space = tail.find(" ")
            if first_space < 0:
                return ""
            tail = tail[first_space + 1 :]
        return tail.strip()

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
