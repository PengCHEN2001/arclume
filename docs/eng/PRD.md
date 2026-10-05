# Arclume Product Requirements Document (PRD)

| Item | Content |
| --- | --- |
| Status | Draft; some product decisions are still open |
| Version | 0.2 |
| Updated | 2026-10-03 |
| Product owner | cxp |
| Target release and date | To be defined |
| Current stage | A working prototype exists; it is not a live support service |

This document defines the problem Arclume should solve, target users, product scope, key experience, and acceptance criteria. Technical implementation and current completion are marked separately. “Implemented in the prototype” does not mean “ready for release”.

## 1. Product overview

Arclume is a multi-agent AI-assisted system for e-commerce customer support. The first version focuses on English support conversations. Later versions may support more languages.

Customers do not follow predefined categories. One message can include a product question, login failure, refund, or delivery issue, and it can depend on earlier turns. Arclume does not send the whole message directly to one model. It first identifies domains, needed information, and risk. It then creates a handling plan: one or more focused Agents cooperate; the system retrieves knowledge or uses controlled business tools when needed; and it returns one complete, traceable reply.

The product goal is to handle complex support messages with evidence and control, rather than letting a model freely generate text or execute actions. When information is missing, the system should ask for it. When an action is risky or the user asks for a human, the system should explain the limit and follow an escalation path.

Multilingual support is not only user-interface translation. Intent recognition, retrieval, terminology, Agent routing, and evaluation also need validation in every language.

## 2. Background, problem, and assumptions

A support message can cover more than one domain. A customer may report both a login failure and duplicate charge. A refund-policy question needs policy evidence, while an order-status question needs current business data. A single flow without clear evidence boundaries can answer the wrong question, invent policy, treat old knowledge as live data, or call a tool incorrectly.

The product currently assumes that:

1. Domain-specific handling and merged results can improve completeness for compound requests.
2. Separating knowledge questions from live-data requests can reduce unsupported answers and unnecessary tool calls.
3. Request-level records can help find errors, reproduce issues, and compare improvements.

These are product assumptions. Real customer distribution, pain level, and adoption have not been validated by user research or production data. The validation plan and owner are still to be defined.

## 3. Target users and use cases

| User | Main need | Current priority |
| --- | --- | --- |
| Customer | Clear and accurate help; a visible next step when self-service fails | Primary |
| Support or operations staff | Review human-needed requests and maintain knowledge content | Secondary; workflow to be defined |
| Product and technical operations | Inspect request processing, find errors, and evaluate quality | Secondary |

The first version prioritizes general questions; refund, delivery, and product knowledge; account or billing issues; multiple independent issues in one message; read-only current-status requests; and explicit requests for human help.

The first-version language is English. The actual channel, customer group, service region, and other languages are to be defined.

## 4. Product goals and success metrics

| Goal | Measurement | Current baseline | Target |
| --- | --- | --- | --- |
| Choose the correct handling path | Intent accuracy, routing accuracy, scenario error rate | 92.2% intent accuracy and 96.6% simplified primary-route accuracy on 500 LLM-generated English synthetic cases; not representative of real traffic | To be defined |
| Find appropriate knowledge evidence | Recall@K, MRR, nDCG, and no-answer behavior | 18 labelled retrieval questions; no confirmed current retrieval result | To be defined |
| Give accurate, complete replies | Human review of correctness, completeness, and evidence support | No confirmed end-to-end answer-quality baseline | To be defined |
| Handle complex requests safely | Compound-request coverage, unnecessary-tool rate, high-risk-operation blocking | Mechanisms exist in the prototype; scenario acceptance is incomplete | To be defined |
| Remain stable | Request success rate, response time, dependency failure, escalation rate | No production baseline | To be defined |

Final targets must use human-reviewed data and a defined usage scale. Prototype offline scores are not customer-service promises.

## 5. First-version scope and non-goals

### 5.1 In scope

- Receive customer messages and retain relevant context in one conversation.
- Identify the problem domain, key information, and needed evidence.
- Route one-domain or multi-domain requests to suitable flows and produce one complete reply.
- Retrieve policy and product knowledge; consider permission-controlled read-only business queries for current-status requests.
- Return an appropriate request for missing information, refusal, or escalation for uncertain, human-requested, or high-risk cases.
- Retain key processing records for diagnosis and repeatable evaluation.
- Provide basic entry points for knowledge maintenance and quality evaluation.

### 5.2 Current non-goals

- Automatically perform refunds, payments, or other high-risk write operations.
- Provide a real handoff to a live support team.
- Connect to real order, logistics, payment, or ticket systems.
- Promise production availability, performance, privacy compliance, or multi-tenancy before the operating environment is defined.
- Support non-English support conversations in the first version.

These boundaries define the current version; they do not reject future work.

## 6. Key user flows

### 6.1 Policy or product knowledge question

For “What is the refund policy?”, the system should recognize that knowledge evidence is required, retrieve relevant content, then answer from that content. Without reliable evidence, it should say that it cannot verify the policy and give a next step instead of inventing dates or conditions. Whether citations are shown to customers is to be defined.

### 6.2 Compound request across domains

For “I cannot log in and I was charged twice,” the system should identify two independent problems, handle them separately, and return one coherent answer. It must not omit one issue or claim that a real charge was checked when no payment record was retrieved. The next turn should be able to use the final merged reply.

### 6.3 Current business-status request

For an order-status question, the system should distinguish current status from general delivery policy. Only an authorized business-query result can support a live-status statement. If the dependency is unavailable, the system must say that it cannot verify the status. The prototype uses demo business data and must not present it as a real customer record.

### 6.4 Human assistance or high-risk operation

When a customer explicitly requests a human, the system should acknowledge the request and explain the available next step. A high-risk operation must not run without required approval. Before a real human-service integration exists, the system must not claim to have created a real ticket or contacted an agent. Receiving team, channel, hours, SLA, and approval flow are to be defined.

## 7. Functional requirements and acceptance criteria

P0 is required for the core customer flow. P1 supports operations and continuous improvement. These are product requirements, not claims about current code completion.

| ID | Priority | Requirement | Observable acceptance criterion |
| --- | --- | --- | --- |
| FR-01 | P0 | Receive messages and continue a conversation | Return a reply, conversation ID, and request ID; later turns use relevant history. |
| FR-02 | P0 | Recognize problems and needed information | Distinguish chat, knowledge, live-data, compound, and explicit-human requests; have a path for uncertainty or review. |
| FR-03 | P0 | Choose a suitable flow | Send the request to one or more suitable domain flows; allow later inspection of the choice. |
| FR-04 | P0 | Answer from knowledge | Retrieve relevant material when knowledge is needed; do not claim evidence when no reliable result exists. |
| FR-05 | P0 | Govern business tools | Respect role, parameter, and risk constraints; do not execute unapproved high-risk actions. |
| FR-06 | P0 | Form one complete reply | Cover each part of a multi-domain request; save the final reply for later turns. |
| FR-07 | P0 | Ask for information or escalate | Give an accurate next step when reliable handling is impossible or a human is requested; do not invent a completed handoff. |
| FR-08 | P1 | Maintain knowledge | Staff can add/view knowledge and verify retrieval; review, publishing, versioning, and rollback are to be defined. |
| FR-09 | P1 | Observe and evaluate | Inspect key decisions by request and rerun routing, retrieval, and answer evaluation; separate execution failure from valid scores. |
| FR-10 | P1 | Provide an interface | The core customer flow works in an interface; final channel, design, and accessibility requirements are to be defined. |

## 8. Interaction and content requirements

- Use language that a customer can understand and answer the issues they actually raised.
- Distinguish an action already performed, an action suggested to the customer, and information the system cannot verify.
- Without evidence, limit the claim, ask for missing information, or escalate. Do not invent policy, order, or payment facts.
- Visibility of sources, processing state, and tool results is to be defined.
- Tone, length, mobile behavior, accessibility, and the staff interface for escalations and knowledge correction are to be defined.

## 9. Non-functional requirements and constraints

| Area | Requirement or open decision |
| --- | --- |
| Security | Before real business integration, define authentication, role permissions, tool authorization, and write-operation approval. |
| Privacy | Define personal-data processing, retention/deletion, access records, and applicable legal requirements. |
| Reliability | Define behavior when the model, knowledge base, conversation store, or business tool is unavailable; define availability and recovery targets. |
| Performance and cost | Define response-time, concurrency, and acceptable model/tool cost per request. |
| Traceability | Retain enough request record for diagnosis; define persistence, access rights, and retention period. |
| Knowledge lifecycle | Define content owner, review/publish, versioning, deletion propagation, and index refresh. |

## 10. Validation and release conditions

Before considering the first version ready, validate normal questions, knowledge questions, compound requests, status queries, missing-information flows, and human requests end to end. Freeze English knowledge, chunking, and retrieval configuration; measure recall/ranking with reviewed examples; inspect no-answer and outdated-information cases. Human reviewers should check correctness, completeness, and evidence support. High-risk actions must be blocked without approval, and demo results must not be mistaken for real data. An independent test set, metric thresholds, release approver, and rollback conditions are still to be completed.

## 11. Prototype status and unmet requirements

The prototype has chat, intent/routing, multi-domain handling, conversation memory, knowledge retrieval, controlled tools, request records, and evaluation entry points. This does not prove the product goals above.

- The demo knowledge base is small; the labelled retrieval set has no confirmed current execution score.
- Order, logistics, and ticket tools are Mock or deterministic, not real records.
- Handoff is not connected to a real support process; `/chat` has no complete approval-and-resume workflow for high-risk actions.
- Request records are mainly in process memory; production authentication, governance, and persistence are unfinished.
- The web interface, real-model answer quality, and full dependency-failure experience still need end-to-end validation.

## 12. Risks and open decisions

| Topic | Current issue |
| --- | --- |
| User needs | No real customer research or issue-distribution data; validation plan and owner are open. |
| Human handoff | Receiving team, ticket system, service time, and customer promise are open. |
| Real business integration | Data source, operation permission, idempotency, and audit are open. |
| Data governance | Retention, deletion, isolation, and sensitive-data handling are open. |
| Quality threshold | Independent test set, targets, and release approval standard are open. |
| Knowledge operations | Content ownership, review, update, and old-index cleanup are open. |

## 13. References

These guides only informed the PRD structure. They do not prove Arclume requirements or results.

- [Atlassian: How to create a product requirements document](https://www.atlassian.com/agile/product-management/requirements/)
- [Atlassian: Product requirements template](https://www.atlassian.com/software/confluence/templates/product-requirements/)
- [Productboard: Product Requirements Document overview](https://www.productboard.com/glossary/product-requirements-document/)
