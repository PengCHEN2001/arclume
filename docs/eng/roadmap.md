# Arclume Roadmap

This document separates prototype capabilities that already exist, checks still needed before public presentation, and later work. It is not a change log and does not promise dates. “Implemented” does not mean “validated with real business data” or “ready for production”.

## Current state

The customer-support backend has an integrated main flow and a first web interface. The project is suitable for local runs, demonstrations, learning, and further development. It does not yet provide the security, data governance, or operations required in production.

### Main capabilities already implemented

| Area | Current state |
| --- | --- |
| API and application | FastAPI endpoints for health, chat, knowledge retrieval/import, Skills, Trace, Monitor, and Evaluation. |
| Multi-Agent flow | General, Technical, Billing, and handoff flows; Agent profiles, routing, compound-request cooperation, and result composition. |
| RAG | ChromaDB Dense retrieval and BM25 lexical retrieval, parallel search, RRF fusion, deduplication, reranking, query variants, cache, timeout, retry, circuit breaker, and fallback. |
| Memory | Redis for working memory, summaries, and AgentState; ChromaDB for episodic memory and user profiles. |
| Tool governance | Harness-controlled tools with permission and risk checks, normalized results, loop limits, statistics, and Trace. High-risk operations do not bypass approval boundaries. |
| Skills | Human-maintained metadata, Agent/keyword selection, length limits, and hot reload. |
| Trace and Monitor | Request Trace, Agent/Tool statistics, limited routing signals, and Prometheus-format metrics. |
| Evaluation | Intent/routing metrics, retrieval metrics, dialogue evaluation, optional LLM Judge, and regression comparison. The repository has LLM-generated synthetic intent cases and 18 English RAG retrieval cases. Confirmed live RAG and real-model answer scores are still missing. |
| Web interface | An AI-generated Vue/Vite first interface for chat, knowledge, and evaluation. The backend flow remains the main focus. |
| Local infrastructure | Compose configuration for Redis, ChromaDB, API, Prometheus, and Nginx. |

Important limits: order, logistics, and ticket tools are Mock or deterministic; Trace is mainly stored in process memory; the demo knowledge base has nine fictional English documents and about eighteen default chunks; the 500 intent cases are LLM-generated and have not been independently reviewed.

## Minimum checks before public presentation

These checks make the repository reproducible. They are not a requirement to finish every production feature first.

1. **Run real retrieval.** Create an isolated empty ChromaDB for the nine English demo documents. Check `/health` and `/knowledge/stats`, then run the 18 `rag-smoke-v3` retrieval cases. Record configuration, metrics, and failures. Do not delete an existing knowledge base simply to retest.
2. **Run a few real `/chat` demonstrations.** Test a normal message, refund policy, login failure plus duplicate charge, and handoff. Check the reply, `primary_agent`, `supporting_agents`, `tools_used`, and Trace. Keep optional Intent/RAG/Memory LLM switches off first. Only publish behavior that has been actually reproduced.
3. **Clean the public repository.** Ensure private study notes, experimental versions, and keys are not uploaded. Check that README commands, documentation links, and implemented/not-implemented statements match the public code. Run unit tests and cite only reproducible results with clear limits.

## Later directions

### 1. RAG: manage knowledge first, then compare retrieval options

- Add source, product model, scope, and version metadata. Define how updates and deletion remove old chunks, refresh BM25, and update evaluation labels.
- Add a small human-reviewed English set for similar products, exact models, policy exceptions, cross-document questions, no-answer cases, and outdated information. Compare Dense, BM25, hybrid search, query rewriting, and reranking with Recall@K, MRR, nDCG, and latency.
- Check whether the final reply is supported by retrieved chunks and whether it admits uncertainty without evidence. Only then test a dedicated reranker, other embedding models, or a more complex index. Rebuild the vector index after changing embeddings.

### 2. Agents: validate routing and cooperation before adding roles

- Add labelled cases for primary/supporting Agents, RAG triggering, Tool choice, refusal, and escalation. Focus on multiple topics, negation, history-dependent requests, and similar-keyword errors.
- Check repeated or conflicting multi-Agent replies. Improve composition and fallback if needed. Keep testing whether the merged final reply supports the next conversation turn.
- Improve short follow-ups such as `yes`, `no`, `it`, or `that`. The current safe fallback may ask a general classification question when the new message has no reliable topic. Later versions can use the previous Assistant question and AgentState to ask a focused follow-up instead of guessing.
- Design a real human approval, rejection, timeout, and resume workflow for high-risk operations. Until then, write tools remain unavailable to `/chat` Agents.

### 3. LangChain / LangGraph: build a comparable second implementation

- After learning the frameworks, build a separate version with the same scope: intent/routing, Memory, RAG, Tool policy, handoff, and Trace. It is not the public main implementation and should not be described as equivalent without checking.
- Use the same requests and evaluation cases to compare readability, state management, failure recovery, latency, and model-call count. Keep the current implementation if a framework change has no clear benefit.

### 4. Real business integration and production safeguards

- Replace Mock order, logistics, and ticket tools with configurable business adapters. Real write operations need authentication, idempotency, duplicate-submission protection, and audit.
- Define authentication, permission, tenant isolation, rate limits, CORS, secret management, and rules to retain/delete conversation, profile, and Trace data.
- Evaluate persistent Trace, alerts, resource limits, and deployment recovery using real scenarios.
- Keep the frontend as a demonstration entry point until API connection, loading, and error states are validated.

## Not current commitments

- Automatically creating, modifying, publishing, or rolling back Skills.
- Adding Agents only to increase their number.
- Integrating external MCP protocols before internal Tool boundaries and governance are stable.
- Claiming that current evaluation scores represent production accuracy or production readiness.

## Maintenance rule

When a verification is completed or a direction changes, update its status and evidence. Do not present an unimplemented idea as a current capability. README explains the project and its limits; this roadmap records the next steps, not every code change.
