# Arclume: understand, gather evidence, then answer

**English** · [Français](docs/fr/README_fr.md) · [中文](docs/zh/README_zh.md)

Arclume is a multi-agent backend prototype for **English-language customer support**. A real customer may mention several independent issues in one message, then use a short follow-up that depends on the earlier context. The system therefore does more than generate fluent text: it identifies the issues, decides who should handle them, gathers evidence when needed, controls tool use, and keeps the request observable.

```text
understand the request
→ make a handling plan
→ retrieve evidence when needed
→ let Agents cooperate
→ generate a reply
→ save and trace the final result
```

> Arclume is a personal learning and engineering project. The current version deliberately does not use high-level Agent frameworks such as LangChain or LangGraph. These frameworks can speed up prototyping, but they can also hide state flow, orchestration, tool calls, and failure handling.
>
> This version implements intent recognition, routing, Context building, the Tool Call Loop, Memory, and Trace explicitly in Python. A later LangChain / LangGraph version will compare development speed, observability, debugging, and maintenance cost.
>
> AI coding tools assisted implementation, refactoring, and tests. The project is still a prototype and is not presented as a production support system.

## Repository layout

```text
arclume/
├── api/                 FastAPI routes, startup, and shared component setup
├── agents/              Agent routing, profiles, execution, and reply composition
├── core/                intent recognition, LLM client, Skills, and Context building
├── memory/              Redis conversation memory, ChromaDB long-term memory, state
├── knowledge/           document chunking, vector retrieval, and BM25 retrieval
├── tools/               concrete tool capabilities
├── harness/             tool permissions, validation, risk checks, execution, Trace
├── frontend/            optional Vue/Vite chat interface
├── data/                demo knowledge documents and generated local data
├── docs/                project, design, code, and evaluation documentation
├── evaluation/          offline cases, metrics, and reports
├── tests/               regression tests without real external services
├── config/              Prometheus and Nginx configuration
├── requirements.txt     Python dependencies
├── docker-compose.yml   local API, Redis, ChromaDB, and Prometheus setup
└── Dockerfile           API image build instructions
```
## Other Documentation

*(English versions are not available yet.Here are the french versions)*

- [Product Requirements Document (PRD)](docs/fr/PRD_fr.md): target users, problem definition, scope of the first version, key requirements, acceptance criteria, and assumptions to validate.
- [Project Design and End-to-End Request Flow](docs/fr/project_design_and_request_flow_fr.md): request flow, design of each layer, and the main technical trade-offs.
- [Code Structure and Implementation Guide](docs/fr/code_guide_fr.md): directory structure, main files, classes and functions, configuration, and entry points for modifications.
- [Evaluation Framework and Running Guide](docs/fr/evaluation_protocol_fr.md): datasets, metrics, execution commands, and limitations of the evaluation results.
- [Roadmap](docs/fr/roadmap_fr.md): validation checklist before publicly presenting the project and directions for future iterations.

## What it handles

For `I cannot log in and I was charged twice.`, Arclume finds two independent issues. It can select Technical and Billing Agents, give each one its own subtask, then merge their replies. The next turn reads the final merged answer, not only one Agent's draft.

A policy or product question can retrieve support knowledge first. An order or tracking request with an identifier may use an allowed read-only business tool. When required information is missing, the system asks the user to provide it. A direct request for a human follows a deterministic handoff path.

These mechanisms do **not** mean the prototype can verify a real payment record or contact a real support team.

| Concern | Arclume approach |
| --- | --- |
| Several issues in one message | Identifies domains and creates subtasks; primary and supporting Agents only answer their assigned part before results are merged. |
| Evidence for an answer | Separates policy/troubleshooting knowledge from current business data; retrieved chunks are added to Agent Context. |
| Follow-up messages | Redis stores recent messages, summaries, and processing state; ChromaDB stores long-term summaries and user profiles. |
| Model tool calls | AgentProfile limits roles and tool scope; the Harness checks parameters and risk, executes calls, and records Trace. |
| Diagnosis | `request_id` links intent, routing, retrieval, and tool events; offline evaluation checks layers separately. |

## Request flow

```text
POST /chat
  → read conversation memory
  → recognize intent and evidence needs
  → route to one Agent, multiple Agents, a request for missing information, or handoff
  → retrieve knowledge or call an allowed tool when needed
  → generate and merge replies
  → save the final user-visible turn and return ChatResponse
```

The main implementation is in `api/`, `core/`, `agents/`, `memory/`, `knowledge/`, `tools/`, and `harness/`. FastAPI exposes an interactive API reference at `/docs` once the service is running.

## Quick start

Arclume needs a Chat model endpoint, Redis, ChromaDB, and the API. The Vue web interface is optional. Runtime secrets belong in a local `.env` file in the repository root. Do not commit `.env`, even after removing personal values; the repository only includes `.env.example` with placeholder values.

Copy the template, then edit `.env` with your own provider and API key:

```bash
cp .env.example .env
```

At minimum, check these values:

```dotenv
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-chat-model
REDIS_PASSWORD=arclume123
ARCLUME_INTENT_LLM_ENABLED=false
ARCLUME_RAG_LLM_ENABLED=false
ARCLUME_MEMORY_LLM_ENABLED=false
```

The optional switches avoid extra LLM calls for intent review, RAG rewrite/rerank, and memory extraction. A normal Agent reply still calls the configured Chat model. Never commit a real API key.

### Docker Compose

With Docker Desktop running, start the complete local stack:

```bash
docker compose up -d --build api
docker compose ps
```

Compose starts Redis and ChromaDB before the API. Inspect failures with `docker compose logs api`.

### Without Docker

Install Python dependencies and run Redis locally:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
brew install redis  # macOS, if Redis is not installed
redis-server --port 6379 --requirepass arclume123 --save '' --appendonly no
```

In another terminal, add these values to `.env` and start the API:

```dotenv
REDIS_URL=redis://:arclume123@127.0.0.1:6379/0
CHROMA_HOST=127.0.0.1
CHROMA_PORT=8001
CHROMA_ALLOW_LOCAL_FALLBACK=true
CHROMA_PERSIST_DIRECTORY=./data/chroma
```

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

If no ChromaDB server is available, the API uses local persistent mode in `data/chroma/`. When the knowledge collection is empty, startup imports `data/demo_docs/`, creates chunks and embeddings, writes ChromaDB, and builds BM25. The first embedding-model download may require internet access but does not consume Chat-model tokens.

## Check the service

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/knowledge/stats
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is the refund policy?","user_id":"demo-user"}'
```

Reuse the returned `conversation_id` for follow-up turns. Use `request_id` to inspect Trace:

```bash
curl http://127.0.0.1:8000/traces/your-request-id
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for all API endpoints. For the web UI:

```bash
cd frontend
npm ci
npm run dev
```

Then open `http://127.0.0.1:5173`.

## Verification and limits

These checks do **not** call a Chat model:

```bash
python -m unittest discover -s tests -q
python -m evaluation --smoke
python -m evaluation
```

They test code behavior and intent/routing behavior on an LLM-generated synthetic English dataset. They do not prove real customer-support quality. Order and logistics tools use demo data; handoff does not contact a real human team; high-risk tool policy has no complete approval-and-resume workflow in `/chat`; Traces are stored in process memory; production authentication, privacy, and data-governance controls are not implemented.

