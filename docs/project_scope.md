# Arclume Project Scope

## Purpose of this document

This document is the stable project context for future conversations and
implementation steps. Read it before proposing changes. It describes the
current project state, the working rules, and the expected learning process.

Detailed line-by-line code teaching may happen in a separate conversation. This
document only preserves the project-level context so that a new conversation can
continue without reconstructing the entire history.

## Project goal

Arclume is a customer-support Agent system that should grow gradually from a
small, understandable Python service into an industrial-quality system.

The project must be developed incrementally. Every new subsystem should have a
clear purpose, a defined boundary, a small testable interface, and a reason for
being introduced at that stage.

## Current implementation state

Step 1 has established the smallest runnable foundation:

- Python 3.10 virtual environment.
- FastAPI application in `api/main.py`.
- Pydantic request and response models.
- Provider-neutral LLM configuration in `.env.example`.
- A small asynchronous LLM client in `core/llm_utils.py`.
- `/health` endpoint.
- `/chat` endpoint for the initial direct model transport test.
- `requirements.txt`, `README.md`, and basic project configuration.
- Docker files are reserved but Docker is not installed, started, or tested yet.

The current `/chat` endpoint is not a complete Agent workflow. It directly
passes one user message to the LLM client.

The following are intentionally not implemented yet:

- Agent routing or multi-Agent orchestration.
- Persistent memory.
- A unified conversation state.
- Context engineering beyond the direct message.
- Skills.
- Tools and actions.
- Knowledge-base retrieval.
- Monitoring and evaluation.
- Sidecar self-improvement.
- Frontend integration.

## Technical direction

- Use ordinary Python modules and clear interfaces first.
- Use Pydantic for data validation and explicit data models.
- Do not introduce an Agent framework unless a later requirement proves that it
  is necessary.
- Keep model access behind an internal client boundary so the provider can be
  changed without rewriting API or Agent logic.
- Do not hardcode one model vendor into the project architecture.
- Add Redis, ChromaDB, Docker, and other infrastructure only when the related
  application capability is ready to use them.
- Prefer the smallest design that can be extended safely.

## Project language rules

- Source code and code comments use English.
- Normal project Markdown files use English.
- `docs/step1.md` is the exception and uses Chinese for the learning plan.
- New documentation must not replace useful existing context. Add detailed
  explanations after the overall project summary unless a change is explicitly
  requested.

## Documentation structure

Each step document should have two layers:

1. An overall plan: goal, scope, main files, broad flow, execution order, and
   acceptance criteria.
2. Detailed descriptions only for the important code files in that step.

For an important code file, describe:

- File responsibility.
- Classes in the file.
- Core attributes of each important class.
- Core methods of each important class.
- Module-level functions next to the classes.
- Dependencies.
- Callers and files that it calls.
- The main data or request flow.

Do not expand trivial package-marker files, ignore files, or configuration files
into unnecessary class-by-class explanations. Mention their role briefly.

## Working and teaching process

For every future step:

1. State the step goal before changing code.
2. Explain why the step is needed.
3. List the files to create or modify.
4. Explain the responsibility and relationships of those files.
5. Identify important classes, attributes, methods, dependencies, and callers.
6. Implement only that step.
7. Provide a small local test that does not call a paid model unless explicitly
   requested.
8. State what is complete, what is deferred, and what the next step could be.

Do not implement several future steps in one turn. Do not refactor working code
only for style. If a design decision is uncertain, explain the options and mark
the decision as pending instead of silently committing to a large change.

## Testing and cost rules

- Local tests such as import checks, health checks, validation checks, and mock
  or test-client requests should be preferred first.
- Do not call a real LLM API during a test unless the user explicitly asks for
  it.
- Treat API calls as potentially paid operations.
- Docker verification is deferred until the project needs it or the user asks
  to install and test it.

## Current next-step rule

Step 1 is the current completed foundation. Step 2 has not been started.

Before implementing Step 2, first propose its goal, files, learning objective,
and acceptance criteria. Wait for confirmation if the proposed step would add a
new subsystem or materially change the current architecture.
