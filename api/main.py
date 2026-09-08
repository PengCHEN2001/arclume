"""Arclume's HTTP entry point for the multi-Agent customer-service flow."""

from contextlib import asynccontextmanager
import asyncio
import json
import logging
import os
from typing import AsyncIterator
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import File, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from agents.agent_orchestrator import AgentOrchestrator
from agents.billing_agent import BillingAgent
from agents.general_agent import GeneralAgent
from agents.technical_agent import TechnicalAgent
from core.intent_recognizer import IntentRecognizer
from core.llm_utils import LLMClient, LLMConfigurationError, LLMRequestError
from core.skill_loader import SkillError, SkillLoader
from evaluation.evaluator import (
    DEFAULT_DIALOG_CASES,
    DEFAULT_INTENT_CASES,
    EndToEndEvaluator,
    IntentTestCase,
)
from harness.runtime import HarnessRuntime
from harness.trace import TraceRecorder
from knowledge import KnowledgeBaseError
from knowledge.knowledge_base import KnowledgeBase
from memory import MemoryStoreError
from memory.conversation_memory import ConversationMemory
from memory.long_term_memory import LongTermMemory
from memory.state_store import StateStore
from monitor import PerformanceMonitor
from schemas.api import (
    ChatRequest,
    ChatResponse,
    EvalRunInput,
    KnowledgeBatchInput,
    KnowledgeDocumentInput,
)
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
    try:
        await app.state.tool_manager.initialize_async()
    except KnowledgeBaseError as exc:
        logger.warning("Hybrid lexical index is not ready; dense retrieval may continue: %s", exc)
    app.state.tool_executor = app.state.tool_manager
    try:
        trace_limit = max(100, int(os.getenv("ARCLUME_TRACE_MAX_EVENTS", "10000")))
    except ValueError:
        trace_limit = 10000
    app.state.harness = HarnessRuntime(
        executor=app.state.tool_executor,
        tracer=TraceRecorder(max_events=trace_limit),
    )
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
    app.state.evaluator = EndToEndEvaluator(
        orchestrator=app.state.orchestrator,
        recognizer=app.state.intent_recognizer,
        llm=app.state.llm,
        baseline_path=os.getenv(
            "ARCLUME_EVAL_BASELINE_PATH",
            "evaluation/baselines/baseline.json",
        ),
    )
    monitor_enabled = os.getenv("ARCLUME_MONITOR_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        monitor_interval = max(
            1.0,
            float(os.getenv("ARCLUME_MONITOR_INTERVAL_SECONDS", "10")),
        )
    except ValueError:
        monitor_interval = 10.0
    try:
        prometheus_port_value = int(os.getenv("PROMETHEUS_PORT", "0"))
    except ValueError:
        prometheus_port_value = 0
    app.state.monitor = PerformanceMonitor(
        orchestrator=app.state.orchestrator,
        tool_manager=app.state.tool_manager,
        interval_seconds=monitor_interval,
        webhook_url=os.getenv("ARCLUME_MONITOR_WEBHOOK_URL") or None,
        prometheus_port=prometheus_port_value or None,
    )
    if monitor_enabled:
        await app.state.monitor.start()
    # Keep the general Agent available for simple integrations during migration.
    app.state.agent = app.state.general_agent
    logger.info("Arclume API started; LLM configured=%s", app.state.llm.is_configured)
    yield
    await app.state.monitor.stop()
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


def _cors_origins() -> list[str]:
    """Read the development CORS policy from one comma-separated setting."""

    raw = os.getenv("ARCLUME_CORS_ORIGINS", "*")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
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
        "rag_bm25_enabled": request.app.state.tool_manager.bm25_enabled,
        "rag_bm25_documents": (
            request.app.state.tool_manager.hybrid_retriever.document_count
            if request.app.state.tool_manager.hybrid_retriever is not None
            else 0
        ),
        "agents": [
            agent_type.value
            for agent_type in request.app.state.orchestrator.list_agents()
        ],
        "intent_llm_enabled": request.app.state.intent_recognizer.use_llm,
        "agent_stats": request.app.state.orchestrator.get_stats(),
        "monitor": {
            "active": request.app.state.monitor.active,
            "prometheus_available": request.app.state.monitor.summary()[
                "prometheus_available"
            ],
        },
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


@app.get("/skills")
async def skills(request: Request) -> dict[str, object]:
    """List loaded Skill metadata without exposing instruction content."""

    try:
        summary = await asyncio.to_thread(request.app.state.skill_loader.summary)
    except SkillError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return summary


@app.post("/skills/reload")
async def reload_skills(request: Request) -> dict[str, object]:
    """Clear the Skill cache so edited Markdown files are used immediately."""

    names = await asyncio.to_thread(request.app.state.skill_loader.reload)
    return {"reloaded": True, "skills": names}


@app.get("/traces/{request_id}")
async def trace(request_id: str, request: Request) -> dict[str, object]:
    """Return the retained in-memory execution events for one request."""

    events = request.app.state.harness.trace_events(request_id)
    if not events:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {
        "request_id": request_id,
        "events": [event.model_dump(mode="json") for event in events],
    }


@app.get("/trace/tool/{request_id}")
async def tool_trace(request_id: str, request: Request) -> dict[str, object]:
    """Return the Tool-focused trace for one completed request."""

    trace_data = request.app.state.harness.tool_trace(request_id)
    return {
        "request_id": request_id,
        "found": trace_data is not None,
        "trace": trace_data or {},
    }


@app.get("/trace/tools")
async def recent_tool_traces(
    request: Request,
    limit: int = 20,
) -> dict[str, object]:
    """Return Tool traces for the most recent requests."""

    return {
        "items": request.app.state.harness.recent_tool_traces(limit),
    }


@app.get("/monitor")
async def monitor_summary(request: Request) -> dict[str, object]:
    """Return Agent/Tool health, active alerts, and optimization suggestions."""

    return request.app.state.monitor.summary()


@app.get("/metrics")
async def prometheus_metrics(request: Request) -> Response:
    """Expose Prometheus-compatible metrics for local or platform scraping."""

    body, media_type = request.app.state.monitor.metrics_payload()
    return Response(content=body, media_type=media_type)


async def _search_knowledge(
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
        "retrieval_mode": data.get("retrieval_mode", "dense"),
        "fusion_method": data.get("fusion_method", "none"),
        "dense_count": data.get("dense_count", 0),
        "bm25_count": data.get("bm25_count", 0),
        "fused_count": data.get("fused_count", 0),
        "cached": result.cached,
        "fallback_used": result.fallback_used,
        "degraded": bool(data.get("degraded")) or result.fallback_used,
    }


@app.get("/knowledge/search")
async def knowledge_search(
    query: str,
    request: Request,
    top_k: int = 5,
) -> dict[str, object]:
    """Search the knowledge base without calling the model."""

    return await _search_knowledge(query, request, top_k)


@app.post("/search")
async def search_knowledge(
    query: str,
    request: Request,
    top_k: int = 5,
) -> dict[str, object]:
    """Compatibility entry point for the complete retrieval pipeline."""

    return await _search_knowledge(query, request, top_k)


def _document_payload(document: KnowledgeDocumentInput) -> dict[str, str]:
    """Convert a validated transport model into the KnowledgeBase payload."""

    payload = {
        "title": document.title.strip(),
        "content": document.content.strip(),
    }
    if document.source and document.source.strip():
        payload["source"] = document.source.strip()
    return payload


async def _refresh_knowledge_index(request: Request) -> bool:
    """Refresh BM25 after ingestion while allowing dense retrieval to degrade safely."""

    try:
        await request.app.state.tool_manager.refresh_hybrid_index()
        return True
    except Exception as exc:
        logger.warning("Hybrid index refresh failed after ingestion: %s", exc)
        return False


@app.post("/knowledge/add")
async def add_knowledge(
    body: KnowledgeBatchInput,
    request: Request,
) -> dict[str, object]:
    """Add validated documents, chunk them, and refresh the lexical index."""

    knowledge_base: KnowledgeBase = request.app.state.knowledge_base
    try:
        added_chunks = await knowledge_base.add_documents_async(
            [_document_payload(document) for document in body.documents]
        )
        total_chunks = await knowledge_base.doc_count_async()
    except (KnowledgeBaseError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "message": f"Indexed {added_chunks} document chunks",
        "added_chunks": added_chunks,
        "total_chunks": total_chunks,
        "hybrid_index_refreshed": await _refresh_knowledge_index(request),
    }


@app.post("/knowledge/upload")
async def upload_knowledge(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, object]:
    """Upload one Markdown, text, or JSON knowledge file up to 10 MB."""

    knowledge_base: KnowledgeBase = request.app.state.knowledge_base
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File size exceeds the 10 MB limit")

    filename = file.filename or "uploaded_document"
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"md", "txt", "json"}:
        raise HTTPException(status_code=415, detail="Only .md, .txt, and .json files are supported")

    text = content.decode("utf-8", errors="ignore")
    documents: list[dict[str, str]] = []
    if suffix == "json":
        try:
            raw_documents = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
        if not isinstance(raw_documents, list):
            raise HTTPException(
                status_code=400,
                detail="JSON uploads must be an array of {title, content} objects",
            )
        try:
            documents = [
                _document_payload(KnowledgeDocumentInput.model_validate(item))
                for item in raw_documents
            ]
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
    else:
        title = filename.rsplit(".", 1)[0] or filename
        documents = [{"title": title, "content": text, "source": filename}]

    if not documents:
        raise HTTPException(status_code=422, detail="The uploaded file contains no documents")

    try:
        added_chunks = await knowledge_base.add_documents_async(documents)
        total_chunks = await knowledge_base.doc_count_async()
    except (KnowledgeBaseError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "message": f"Indexed {added_chunks} chunks from {filename}",
        "filename": filename,
        "added_chunks": added_chunks,
        "total_chunks": total_chunks,
        "hybrid_index_refreshed": await _refresh_knowledge_index(request),
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


@app.post("/eval/run")
async def run_evaluation(
    request: Request,
    body: EvalRunInput | None = None,
) -> dict[str, object]:
    """Run the Intent and end-to-end Evaluation suite."""

    evaluator: EndToEndEvaluator | None = getattr(
        request.app.state,
        "evaluator",
        None,
    )
    if evaluator is None:
        raise HTTPException(status_code=503, detail="Evaluation is not ready")

    if body and body.intent_cases is not None:
        intent_cases = [
            IntentTestCase(
                message=item.message,
                expected_intent=item.expected_intent,
                context=item.context,
            )
            for item in body.intent_cases
        ]
    else:
        intent_cases = DEFAULT_INTENT_CASES

    if body and body.dialog_cases is not None:
        dialog_cases: list[dict[str, object]] = []
        for item in body.dialog_cases:
            value = item.model_dump(exclude_none=True)
            if "conversation_id" in value:
                value["conv_id"] = value.pop("conversation_id")
            dialog_cases.append(value)
    else:
        dialog_cases = DEFAULT_DIALOG_CASES

    report = await evaluator.run(
        intent_cases=intent_cases,
        dialog_cases=dialog_cases,
    )
    return report.to_dict()


@app.get("/tools/stats")
async def tool_stats(request: Request) -> dict[str, object]:
    """Return internal Tool reliability metrics for local verification."""

    return {"tools": request.app.state.harness.tool_stats()}
