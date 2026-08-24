"""Small, provider-agnostic transport for OpenAI-compatible chat APIs.

The project does not couple its business logic to one model vendor. The client
reads a provider label, API key, base URL, and model name from the environment.
Any provider that exposes an OpenAI-compatible ``/chat/completions`` endpoint
can therefore be selected without changing the API layer.

This module is deliberately a transport layer, not an Agent framework. It does
not decide when to call tools, how to route requests, or how to store memory.
Those decisions belong to higher-level modules introduced in later steps.
"""

from dataclasses import dataclass
import os
from typing import Any

import httpx


class LLMConfigurationError(RuntimeError):
    """Raised when a model request cannot be made because configuration is missing."""


class LLMRequestError(RuntimeError):
    """Raised when a configured provider rejects or cannot answer a request."""


@dataclass(frozen=True)
class LLMSettings:
    """Runtime configuration for one OpenAI-compatible model endpoint."""

    provider: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "LLMSettings":
        """Build settings from environment variables without hardcoding a vendor."""

        return cls(
            provider=os.getenv("LLM_PROVIDER", "openai_compatible").strip(),
            api_key=os.getenv("LLM_API_KEY", "").strip(),
            base_url=os.getenv("LLM_BASE_URL", "").strip().rstrip("/"),
            model=os.getenv("LLM_MODEL", "").strip(),
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        )

    @property
    def is_configured(self) -> bool:
        """Return whether all values required for a real request are present."""

        return bool(self.api_key and self.base_url and self.model)


class LLMClient:
    """Reusable asynchronous client for one configured model endpoint."""

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=settings.timeout_seconds)

    @classmethod
    def from_environment(cls) -> "LLMClient":
        """Create a client using the current process environment."""

        return cls(LLMSettings.from_environment())

    @property
    def is_configured(self) -> bool:
        """Expose configuration state without revealing the API key."""

        return self.settings.is_configured

    async def close(self) -> None:
        """Close the underlying connection pool during application shutdown."""

        await self._http.aclose()

    async def chat(self, message: str, system_prompt: str | None = None) -> str:
        """Send one user message and return the provider's text response.

        The payload follows the common OpenAI-compatible chat-completions shape.
        Providers with a different protocol can be supported later by adding a
        separate transport implementation behind the same higher-level client
        contract.
        """

        if not self.is_configured:
            raise LLMConfigurationError(
                "LLM is not configured. Set LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL."
            )

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._http.post(
                f"{self.settings.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMRequestError(f"LLM request failed: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMRequestError("LLM response did not contain message content") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMRequestError("LLM response contained empty message content")
        return content.strip()
