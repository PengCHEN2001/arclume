# Arclume

Arclume is a customer-support Agent system designed to grow from a small,
understandable runtime into an industrial-grade orchestration platform.

## Current stage

The first stage establishes a runnable foundation:

- FastAPI provides the HTTP boundary.
- Pydantic validates incoming and outgoing data.
- A small asynchronous LLM client provides model transport.
- Docker Compose reserves Redis and ChromaDB as future infrastructure services.
- No Agent routing, memory workflow, tools, skills, or self-improvement loop is
  implemented yet.

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
- `POST /chat` — direct model request for the first vertical slice.
- `GET /docs` — interactive API documentation.

The service can start without a model key so the HTTP layer can be inspected.
The chat endpoint requires `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL`.

## Run infrastructure and the API with Docker

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f api
```

The first stage starts the API, Redis, and ChromaDB containers. Redis and
ChromaDB are infrastructure reservations; application code will connect to
them after the memory and retrieval stages are designed.
