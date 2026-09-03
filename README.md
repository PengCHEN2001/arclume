# Arclume

Arclume is a customer-support Agent system designed to grow from a small,
understandable runtime into an industrial-grade orchestration platform.

## Current stage

The tenth stage adds intent recognition, structured Agent roles, and a central
multi-Agent orchestrator:

- FastAPI provides the HTTP boundary.
- Pydantic validates incoming and outgoing data.
- A small asynchronous LLM client provides model transport.
- `schemas/` defines shared API, state, context, and tool models.
- `harness/` separates policy decisions, Tool execution, tracing, and the
  model-independent Agent loop skeleton.
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
  current message, conversation history, AgentState, and retrieved evidence.
- `memory/` stores recent conversation messages and active-case `AgentState`
  records in Redis.
- `knowledge/knowledge_base.py` indexes document chunks in ChromaDB and returns
  semantic search results for one request.
- `data/demo_docs/` contains small English policy documents for local RAG tests.
- `core/skill_loader.py` loads human-authored Markdown Skill instructions without
  allowing the Agent to modify them.
- `skills/` contains refund, logistics, technical, and human-escalation instructions.
- `tools/tool_functions.py` contains the current Tool functions and registers
  them in the shared Harness Executor.
- `core/llm_utils.py` can parse OpenAI-compatible function calls, while the
  Harness remains responsible for Tool authorization and execution.
- The `/chat` endpoint now runs intent recognition and orchestration before the
  selected Agent builds Context. RAG is skipped for greetings, feedback, and
  explicit human handoff requests, and is enabled for business intents.
- The selected Agent receives only the Skill relevant to the detected domain.
- The current basic knowledge retrieval still passes through the low-risk
  Harness Tool boundary; enhanced query rewriting, multi-recall, deduplication,
  and reranking remain a later retrieval upgrade.
- `/knowledge/search` and `/knowledge/stats` provide model-free retrieval checks.
- Order and logistics Tools currently return deterministic mock data. Ticket
  creation is marked high risk and stops for approval.
- The current Tool loop is bounded and only runs when the configured provider
  supports compatible function calling; otherwise the text path remains active.
- Advanced retrieval, Tool caching, circuit breaking, three-tier long-term
  memory, context compression, monitoring, evaluation, and automatic Skill
  evolution are not implemented yet.

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

The current application uses Redis for short-term memory and AgentState. ChromaDB
stores the current knowledge collection. The application can start while ChromaDB
is unavailable; RAG is skipped until the service becomes available.
