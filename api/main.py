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
from harness.runtime import HarnessRuntime
from knowledge import KnowledgeBaseError
from knowledge.knowledge_base import KnowledgeBase
from memory import MemoryStoreError
from memory.conversation_memory import ConversationMemory
from memory.long_term_memory import LongTermMemory
from memory.state_store import StateStore
from schemas.api import ChatRequest, ChatResponse
from schemas.tool import ToolCall
from tools.tool_manager import ToolManager
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
    app.state.long_term_memory = LongTermMemory.from_environment()
    try:
        await app.state.long_term_memory.initialize_async()
    except MemoryStoreError as exc:
        logger.warning("Long-term memory is not ready; chat will continue with Redis: %s", exc)
        app.state.long_term_memory = None
    app.state.memory = ConversationMemory.from_environment(
        redis_url=redis_url,
        llm=app.state.llm,
        long_term_memory=app.state.long_term_memory,
    )
    app.state.state_store = StateStore.from_url(redis_url)
    app.state.knowledge_base = KnowledgeBase.from_environment()
    try:
        await app.state.knowledge_base.initialize_async()
    except KnowledgeBaseError as exc:
        logger.warning("Knowledge base is not ready; chat will continue without RAG: %s", exc)
    app.state.skill_loader = SkillLoader.from_environment()
    app.state.tool_manager = register_tools(
        ToolManager(
            llm=app.state.llm,
            knowledge_base=app.state.knowledge_base,
        )
    )
    app.state.tool_executor = app.state.tool_manager
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
    if app.state.long_term_memory is not None:
        await app.state.long_term_memory.close()
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
        "memory": {
            "working_memory_ttl_seconds": request.app.state.memory.ttl_seconds,
            "compress_at": request.app.state.memory.compress_at,
            "retain_messages": request.app.state.memory.retain_messages,
            "summary_ttl_seconds": request.app.state.memory.summary_ttl_seconds,
            "long_term_mode": (
                request.app.state.long_term_memory.mode
                if request.app.state.long_term_memory is not None
                else None
            ),
        },
        "skills": request.app.state.skill_loader.list_available(),
        "tools": [tool.name for tool in request.app.state.tool_executor.list_tools()],
        "tool_stats": request.app.state.harness.tool_stats(),
        "rag_llm_enabled": request.app.state.tool_manager.rag_llm_enabled,
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
        memory_context = await request.app.state.memory.get_context(
            payload.user_id,
            conversation_id,
            query=payload.message,
        )
        history = [
            message.model_dump()
            for message in memory_context["recent_messages"]
        ]
        result = await orchestrator.run(
            payload.message,
            user_id=payload.user_id,
            conversation_id=conversation_id,
            history=history,
            memory_context=memory_context,
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
        request_id=result.request_id,
        intent=result.intent.intent.value,
        intent_group=result.intent.intent_group,
        primary_agent=result.primary_agent.value,
        supporting_agents=[agent.value for agent in result.supporting_agents],
        routing_reason=result.routing_reason,
        routing_confidence=result.routing_confidence,
        escalated=result.escalated,
        tools_used=result.tools_used,
        tool_traces=result.tool_traces,
    )


@app.get("/knowledge/search")
async def knowledge_search(
    query: str,
    request: Request,
    top_k: int = 5,
) -> dict[str, object]:
    """Search indexed knowledge without calling the model."""

    harness: HarnessRuntime = request.app.state.harness
    try:
        result = await harness.handle_tool_call(
            ToolCall(
                call_id=str(uuid4()),
                tool_name="knowledge_search",
                arguments={"query": query, "top_k": top_k},
                requested_by="general",
            ),
            context={
                "knowledge_base": request.app.state.knowledge_base,
                "tool_manager": request.app.state.tool_manager,
                "request_id": str(uuid4()),
            },
            allowed_tools={"knowledge_search"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KnowledgeBaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.success and not result.fallback_used:
        raise HTTPException(status_code=503, detail=result.error or "Knowledge retrieval failed")
    data = result.data if isinstance(result.data, dict) else {"results": result.data or []}
    return {
        "query": query,
        "queries": data.get("queries", [query]),
        "results": data.get("results", []),
        "reranked": result.reranked or bool(data.get("reranked")),
        "rerank_method": data.get("rerank_method", "none"),
        "cached": result.cached,
        "fallback_used": result.fallback_used,
        "degraded": bool(data.get("degraded")) or result.fallback_used,
    }


@app.get("/knowledge/stats")
async def knowledge_stats(request: Request) -> dict[str, object]:
    """Return the number of indexed chunks for local verification."""

    knowledge_base: KnowledgeBase = request.app.state.knowledge_base
    try:
        count = await knowledge_base.doc_count_async()
    except KnowledgeBaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"collection": KnowledgeBase.COLLECTION_NAME, "total_chunks": count}


@app.get("/tools/stats")
async def tool_stats(request: Request) -> dict[str, object]:
    """Return internal Tool reliability metrics for local verification."""

    return {"tools": request.app.state.harness.tool_stats()}
