"""Knowledge retrieval adapters for Arclume."""


class KnowledgeBaseError(RuntimeError):
    """Raised when the knowledge base cannot complete an operation."""


class KnowledgeBaseUnavailable(KnowledgeBaseError):
    """Raised when the configured ChromaDB service cannot be reached."""
