# Arclume

Arclume is a customer-support Agent system designed to grow from a small,
understandable runtime into an industrial-grade orchestration platform.

## Current stage

The fifth stage adds Redis-backed short-term memory and AgentState persistence
to the single-Agent customer-service flow:

- FastAPI provides the HTTP boundary.
- Pydantic validates incoming and outgoing data.
- A small asynchronous LLM client provides model transport.
- `schemas/` defines shared API, state, context, and tool models.
- `harness/` separates policy decisions, Tool execution, tracing, and the
  model-independent Agent loop skeleton.
- `agents/customer_service_agent.py` provides the first single-Agent behavior
  and sends a stable system prompt through `LLMClient`.
- `memory/` stores recent conversation messages and active-case `AgentState`
  records in Redis.
- Docker Compose provides Redis for current memory and reserves ChromaDB for
  future retrieval and long-term memory.
- No business Tool, Agent routing, context builder, skills, or self-improvement
  loop is implemented yet.
- The `/chat` endpoint now loads and saves short-term memory and AgentState for
  each conversation before and after one model request.

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
remains reserved for the later retrieval and long-term memory stages.
