"""Persistence adapters for conversation memory and Agent state."""


class MemoryStoreError(RuntimeError):
    """Raised when the configured memory backend cannot complete an operation."""
