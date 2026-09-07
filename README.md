# Arclume

Arclume is a customer-support Agent system designed to grow from a small,
understandable runtime into an industrial-grade orchestration platform.

## Current stage

The fourteenth stage adds metadata-driven Skills and complete request tracing
on top of Hybrid RAG, layered Memory, governed Tool execution, and the
structured multi-Agent runtime:

- FastAPI provides the HTTP boundary.
- Pydantic validates incoming and outgoing data.
- A small asynchronous LLM client provides model transport.
- `schemas/` defines shared API, state, context, and tool models.
- `harness/` separates policy decisions, Tool execution, tracing, and the
  model-independent Agent loop skeleton.
- `harness/trace.py` records request, routing, Skill, RAG, Agent, Tool, Memory,
  and response events with bounded in-memory retention.
- `agents/customer_service_agent.py` provides shared execution logic for domain
  Agents, renders each AgentProfile, and supports a bounded model Tool loop.
- `agents/agent_profile.py` defines each Agent's role, mission, workflow,
  contracts, handoff conditions, and Tool scope.
- `agents/general_agent.py`, `agents/technical_agent.py`, and
  `agents/billing_agent.py` provide the three executable domain Agents.
- `agents/escalation_agent.py` provides a deterministic human-handoff node.
- `agents/response_composer.py` combines primary and supporting Agent results
  without an extra model call.
- `core/intent_recognizer.py` produces fine-grained intent, entities, urgency,
  confidence, domain scores, and the RAG decision. Local recognition is the
  default; an optional refinement LLM call is controlled by
  `ARCLUME_INTENT_LLM_ENABLED`.
- `agents/agent_orchestrator.py` selects the primary Agent, can run a technical
  and billing Agent in parallel for compound requests, handles clarification,
  records basic Agent performance, exposes request-level Tool information, and
  falls back to the General Agent.
- `core/context_builder.py` assembles the temporary model context from the
  current message, recent history, session summary, episodic memory, user
  profile, AgentState, and retrieved evidence.
- `memory/conversation_memory.py` stores Redis working memory and session
  summaries, compacts older messages, and coordinates long-term memory reads.
- `memory/long_term_memory.py` stores episodic summaries and user profiles in
  separate ChromaDB collections.
- `memory/state_store.py` keeps active-case `AgentState` records in Redis; State
  remains separate from conversation memory.
- `tests/test_memory.py` verifies Memory compression, long-term recall, and the
  Redis/ChromaDB failure boundary without external services.
- `knowledge/knowledge_base.py` indexes document chunks in ChromaDB and returns
  semantic search results for one request.
- `knowledge/bm25_index.py` builds a dependency-free lexical index over the same
  knowledge chunks.
- `knowledge/hybrid_retriever.py` runs dense and BM25 recall in parallel and
  combines their ranked results with Reciprocal Rank Fusion.
- `data/demo_docs/` contains small English policy documents for local RAG tests.
- `core/skill_loader.py` loads human-authored Markdown Skills, parses metadata,
  filters by Agent and keywords, supports SKILL.md/Markdown/text/JSON inputs,
  enforces a bounded prompt budget, and supports mtime-aware hot reload.
- `skills/` contains metadata-driven refund, logistics, technical, and
  human-escalation instructions.
- `tools/tool_functions.py` contains the current Tool functions and registers
  them in the shared Harness Executor.
- `tools/tool_manager.py` coordinates query rewriting, parallel recall,
  BM25 and dense retrieval, RRF fusion, deduplication, reranking, TTL caching,
  circuit breaking, fallback, and Tool statistics.
- `core/llm_utils.py` can parse OpenAI-compatible function calls, while the
  Harness remains responsible for Tool authorization and execution.
- The `/chat` endpoint now runs intent recognition and orchestration before the
  selected Agent builds Context. RAG is skipped for greetings, feedback, and
  explicit human handoff requests, and is enabled for business intents.
- The selected Agent receives only the Skill relevant to the detected domain.
- The knowledge retrieval path now passes through the low-risk Harness Tool
  boundary and supports bounded query variants, parallel dense and BM25 recall,
  RRF fusion, deduplication, and local or optional model reranking.
- `/knowledge/search`, `/knowledge/stats`, and `/tools/stats` provide model-free
  retrieval and reliability checks.
- `/skills` lists Skill metadata and `/skills/reload` reloads edited Skill files.
- `/traces/{request_id}` exposes the retained request-level execution trace.
- Order and logistics Tools currently return deterministic mock data. Ticket
  creation is marked high risk and stops for approval.
- The current Agent Tool loop is bounded and only runs when the configured provider
  supports compatible function calling; otherwise the text path remains active.
- Monitor and Evaluation are not implemented yet. Automatic Skill generation,
  modification, publication, and rollback remain intentionally disabled.

## Python environment

The project uses a local Python 3.10 virtual environment:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configuration

Create a local environment file and fill in a model provider that exposes an
OpenAI-compatible chat-completions endpoint:

```bash
cp .env.example .env
```

The `.env` file is ignored by Git. Never place a real API key in
`.env.example`.

## Run locally

```bash
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Useful endpoints:

- `GET /health` — process and configuration status.
- `POST /chat` — single-Agent customer-service request with Redis persistence.
- `GET /knowledge/search` — semantic search without calling the model.
- `GET /knowledge/stats` — indexed knowledge chunk count.
- `GET /docs` — interactive API documentation.

The service can start without a model key so the HTTP layer can be inspected.
The chat endpoint requires `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, and a
reachable Redis instance.

## Run infrastructure and the API with Docker

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f api
```

The current application uses Redis for working memory, session summaries, and
AgentState. ChromaDB stores the knowledge base, episodic summaries, and user
profiles in separate collections. Memory compression uses a local factual
fallback by default; set `ARCLUME_MEMORY_LLM_ENABLED=true` only when the extra
summary and profile-extraction model calls are desired. The application can
continue with Redis-only memory while ChromaDB is unavailable. RAG uses both a
ChromaDB dense branch and an in-process BM25 branch by default; set
`ARCLUME_RAG_BM25_ENABLED=false` to compare dense-only retrieval. Redis is a core
chat dependency: if its working-memory read or write fails, `/chat` returns
`503` instead of silently pretending that no history exists.

Run the dependency-free Memory tests with:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```
