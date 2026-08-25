"""Arclume's HTTP entry point for the single-Agent memory flow.

This module intentionally implements only the smallest useful vertical slice:

1. Create a FastAPI application.
2. Load configuration from environment variables.
3. Expose a health endpoint for local and container checks.
4. Expose a chat endpoint backed by CustomerServiceAgent.

The API owns application resources while the Agent owns customer-service
behavior. Redis-backed conversation memory and AgentState persistence are now
created at application startup.
"""

from contextlib import asynccontextmanager
import logging
import os
from typing import AsyncIterator
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from agents.customer_service_agent import CustomerServiceAgent
from core.llm_utils import LLMClient, LLMConfigurationError, LLMRequestError
from knowledge import KnowledgeBaseError
from knowledge.knowledge_base import KnowledgeBase
from memory import MemoryStoreError
from memory.conversation_memory import ConversationMemory
from memory.state_store import StateStore
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

    The model client and Redis-backed stores are created once when the service
    starts. Reusing them avoids creating new connections for every request and
    gives the application one clear place to release resources on shutdown.
    """

    app.state.llm = LLMClient.from_environment()
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    app.state.memory = ConversationMemory.from_url(redis_url)
    app.state.state_store = StateStore.from_url(redis_url)
    app.state.knowledge_base = KnowledgeBase.from_environment()
    try:
        await app.state.knowledge_base.initialize_async()
    except KnowledgeBaseError as exc:
        logger.warning("Knowledge base is not ready; chat will continue without RAG: %s", exc)
    app.state.agent = CustomerServiceAgent(
        llm=app.state.llm,
        memory=app.state.memory,
        state_store=app.state.state_store,
        knowledge_base=app.state.knowledge_base,
    )
    logger.info("Arclume API started; LLM configured=%s", app.state.llm.is_configured)
    yield
    await app.state.memory.close()
    await app.state.state_store.close()
    await app.state.knowledge_base.close()
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

    The process is allowed to start without an API key or Redis connection so
    that developers can inspect the HTTP service. The chat endpoint requires
    both configured model access and reachable Redis.
    """

    llm: LLMClient = request.app.state.llm
    return {
        "status": "ok",
        "service": "arclume-api",
        "llm_configured": llm.is_configured,
        "llm_provider": llm.settings.provider,
        "llm_model": llm.settings.model,
        "knowledge_base": {
            "ready": request.app.state.knowledge_base.mode is not None,
            "mode": request.app.state.knowledge_base.mode,
        },
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Send one message through the Agent with Redis-backed persistence.

    The Agent loads recent history and the current AgentState before the model
    call, then saves the new message pair and updated state afterward.
    """

    llm: LLMClient = request.app.state.llm
    agent: CustomerServiceAgent = request.app.state.agent
    conversation_id = payload.conversation_id or str(uuid4())
    try:
        answer = await agent.respond(
            payload.message,
            user_id=payload.user_id,
            conversation_id=conversation_id,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMRequestError as exc:
        logger.exception("LLM request failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except MemoryStoreError as exc:
        logger.exception("Memory store request failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return ChatResponse(
        message=answer,
        model=llm.settings.model,
        conversation_id=conversation_id,
    )


@app.get("/knowledge/search")
async def knowledge_search(
    query: str,
    request: Request,
    top_k: int = 5,
) -> dict[str, object]:
    """Search indexed knowledge without calling the model."""

    knowledge_base: KnowledgeBase = request.app.state.knowledge_base
    try:
        results = await knowledge_base.search_async(query, top_k=top_k)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KnowledgeBaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"query": query, "results": results}


@app.get("/knowledge/stats")
async def knowledge_stats(request: Request) -> dict[str, object]:
    """Return the number of indexed chunks for local verification."""

    knowledge_base: KnowledgeBase = request.app.state.knowledge_base
    try:
        count = await knowledge_base.doc_count_async()
    except KnowledgeBaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"collection": KnowledgeBase.COLLECTION_NAME, "total_chunks": count}
