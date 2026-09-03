"""Arclume's HTTP entry point for the multi-Agent customer-service flow."""

from contextlib import asynccontextmanager
import logging
import os
from typing import AsyncIterator
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from agents.agent_orchestrator import AgentOrchestrator
from agents.billing_agent import BillingAgent
from agents.general_agent import GeneralAgent
from agents.technical_agent import TechnicalAgent
from core.intent_recognizer import IntentRecognizer
from core.llm_utils import LLMClient, LLMConfigurationError, LLMRequestError
from core.skill_loader import SkillLoader
from harness.executor import ToolExecutor
from harness.runtime import HarnessRuntime
from knowledge import KnowledgeBaseError
from knowledge.knowledge_base import KnowledgeBase
from memory import MemoryStoreError
from memory.conversation_memory import ConversationMemory
from memory.state_store import StateStore
from schemas.api import ChatRequest, ChatResponse
from tools.tool_functions import register_tools


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
    app.state.skill_loader = SkillLoader.from_environment()
    app.state.tool_executor = register_tools(ToolExecutor())
    app.state.harness = HarnessRuntime(executor=app.state.tool_executor)
    common_agent_kwargs = {
        "llm": app.state.llm,
        "memory": app.state.memory,
        "state_store": app.state.state_store,
        "knowledge_base": app.state.knowledge_base,
        "skill_loader": app.state.skill_loader,
        "harness": app.state.harness,
    }
    app.state.general_agent = GeneralAgent(**common_agent_kwargs)
    app.state.technical_agent = TechnicalAgent(**common_agent_kwargs)
    app.state.billing_agent = BillingAgent(**common_agent_kwargs)
    intent_llm_enabled = os.getenv(
        "ARCLUME_INTENT_LLM_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes"}
    app.state.intent_recognizer = IntentRecognizer(
        llm=app.state.llm,
        use_llm=intent_llm_enabled,
    )
    app.state.orchestrator = AgentOrchestrator(
        general_agent=app.state.general_agent,
        technical_agent=app.state.technical_agent,
        billing_agent=app.state.billing_agent,
        intent_recognizer=app.state.intent_recognizer,
    )
    # Keep the general Agent available for simple integrations during migration.
    app.state.agent = app.state.general_agent
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
        "skills": request.app.state.skill_loader.list_available(),
        "tools": [tool.name for tool in request.app.state.tool_executor.list_tools()],
        "agents": [
            agent_type.value
            for agent_type in request.app.state.orchestrator.list_agents()
        ],
        "intent_llm_enabled": request.app.state.intent_recognizer.use_llm,
        "agent_stats": request.app.state.orchestrator.get_stats(),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Send one message through intent recognition and Agent orchestration."""

    llm: LLMClient = request.app.state.llm
    orchestrator: AgentOrchestrator = request.app.state.orchestrator
    conversation_id = payload.conversation_id or str(uuid4())
    try:
        stored_history = await request.app.state.memory.get_messages(
            payload.user_id,
            conversation_id,
        )
        history = [message.model_dump() for message in stored_history]
        result = await orchestrator.run(
            payload.message,
            user_id=payload.user_id,
            conversation_id=conversation_id,
            history=history,
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
        message=result.response,
        model=llm.settings.model,
        conversation_id=conversation_id,
        intent=result.intent.intent.value,
        intent_group=result.intent.intent_group,
        primary_agent=result.primary_agent.value,
        supporting_agents=[agent.value for agent in result.supporting_agents],
        routing_reason=result.routing_reason,
        routing_confidence=result.routing_confidence,
        escalated=result.escalated,
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
