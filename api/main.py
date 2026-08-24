"""Arclume's first HTTP entry point.

This module intentionally implements only the smallest useful vertical slice:

1. Create a FastAPI application.
2. Load configuration from environment variables.
3. Expose a health endpoint for local and container checks.
4. Expose a direct chat endpoint backed by a provider-agnostic LLM client.

Agent routing, memory, tools, skills, retrieval, and evaluation are deliberately
outside this first step. Keeping the entry point small makes the first runtime
failure easy to understand before those subsystems are introduced.
"""

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from core.llm_utils import LLMClient, LLMConfigurationError, LLMRequestError
from schemas.api import ChatRequest, ChatResponse


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("arclume.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create and close shared process-level resources.

    The HTTP client is created once when the service starts and reused across
    requests. This avoids opening a new network connection for every message
    and gives the application one clear place to release resources on shutdown.
    """

    app.state.llm = LLMClient.from_environment()
    logger.info("Arclume API started; LLM configured=%s", app.state.llm.is_configured)
    yield
    await app.state.llm.close()
    logger.info("Arclume API stopped")


app = FastAPI(
    title="Arclume API",
    version="0.1.0",
    description="Initial HTTP foundation for the Arclume customer-support agent.",
    lifespan=lifespan,
)


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    """Return a lightweight readiness report.

    The process is allowed to start without an API key so that developers can
    inspect the HTTP service before configuring a paid model provider. The
    chat endpoint will return a clear error until the key is supplied.
    """

    llm: LLMClient = request.app.state.llm
    return {
        "status": "ok",
        "service": "arclume-api",
        "llm_configured": llm.is_configured,
        "llm_provider": llm.settings.provider,
        "llm_model": llm.settings.model,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Send one message directly to the configured LLM.

    This endpoint is intentionally not an Agent loop yet. It proves that the
    API boundary, request validation, configuration, and model transport work
    before orchestration logic is added.
    """

    llm: LLMClient = request.app.state.llm
    try:
        answer = await llm.chat(payload.message)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMRequestError as exc:
        logger.exception("LLM request failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(
        message=answer,
        model=llm.settings.model,
        conversation_id=payload.conversation_id,
    )
