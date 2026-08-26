# Arclume

Arclume is a customer-support Agent system designed to grow from a small,
understandable runtime into an industrial-grade orchestration platform.

## Current stage

The ninth stage adds a small set of internal Tools governed by the Harness:

- FastAPI provides the HTTP boundary.
- Pydantic validates incoming and outgoing data.
- A small asynchronous LLM client provides model transport.
- `schemas/` defines shared API, state, context, and tool models.
- `harness/` separates policy decisions, Tool execution, tracing, and the
  model-independent Agent loop skeleton.
- `agents/customer_service_agent.py` provides the first single-Agent behavior
  and sends a stable system prompt through `LLMClient`.
- `core/context_builder.py` assembles the temporary model context from the
  current message, conversation history, AgentState, and retrieved evidence.
- `memory/` stores recent conversation messages and active-case `AgentState`
  records in Redis.
- `knowledge/knowledge_base.py` indexes document chunks in ChromaDB and returns
  semantic search results for one request.
- `data/demo_docs/` contains small English policy documents for local RAG tests.
- `core/skill_loader.py` loads human-authored Markdown Skill instructions without
  allowing the Agent to modify them.
- `skills/` contains refund, logistics, and human-escalation instructions.
- `tools/tool_functions.py` contains the current Tool functions and registers
  them in the shared Harness Executor.
- The `/chat` endpoint retrieves up to three relevant knowledge chunks before
  building a temporary Context. The knowledge lookup now passes through the
  low-risk Harness Tool boundary, and retrieval failure does not stop chat.
- The Agent accepts explicitly selected Skill names, but automatic Skill
  selection waits for the later intent and routing stage.
- `/knowledge/search` and `/knowledge/stats` provide model-free retrieval checks.
- Order and logistics Tools currently return deterministic mock data. Ticket
  creation is marked high risk and stops for approval.
- No Agent routing, context compression, Skill evolution, or
  self-improvement loop is implemented yet.

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
