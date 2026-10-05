"""Public HTTP request and response models.

These models define the boundary between external clients and the application.
They intentionally contain only transport-level data. Agent state, prompt
context, and tool execution data live in their own schema modules.
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Payload accepted by the public chat endpoint."""

    message: str = Field(min_length=1, description="The user's message")
    user_id: str = Field(
        default="anonymous",
        min_length=1,
        description="Stable identifier for the end user",
    )
    conversation_id: str | None = Field(
        default=None,
        description="Optional identifier for a continuing conversation",
    )


class ChatResponse(BaseModel):
    """Stable response shape returned by the public chat endpoint."""

    message: str
    model: str
    conversation_id: str | None = None
    intent: str | None = None
    intent_group: str | None = None
    primary_agent: str | None = None
    supporting_agents: list[str] = Field(default_factory=list)
    routing_reason: str | None = None
    routing_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    escalated: bool = False
    escalation_reason: str | None = None
    escalation_source: str | None = None
    request_id: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    tool_traces: list[dict[str, object]] = Field(default_factory=list)


class KnowledgeDocumentInput(BaseModel):
    """One document accepted by the knowledge ingestion endpoint."""

    title: str = Field(min_length=1, description="Human-readable document title")
    content: str = Field(min_length=1, description="Document text to index")
    source: str | None = Field(
        default=None,
        description="Optional stable source label used in retrieval metadata",
    )


class KnowledgeBatchInput(BaseModel):
    """Batch of documents accepted by ``POST /knowledge/add``."""

    documents: list[KnowledgeDocumentInput] = Field(min_length=1)


class EvalIntentCaseInput(BaseModel):
    """One optional custom Intent case for the Evaluation endpoint."""

    message: str = Field(min_length=1)
    expected_intent: str = Field(min_length=1)
    context: dict[str, object] | None = None


class EvalDialogCaseInput(BaseModel):
    """One single-turn or multi-turn dialog Evaluation case."""

    question: str | None = None
    turns: list[str] | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    reference_answer: str | None = None


class EvalRetrievalCaseInput(BaseModel):
    """One labeled query used to evaluate live RAG retrieval."""

    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    relevant_chunk_ids: list[str] = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class EvalRunInput(BaseModel):
    """Optional custom cases accepted by ``POST /eval/run``."""

    intent_cases: list[EvalIntentCaseInput] | None = None
    dialog_cases: list[EvalDialogCaseInput] | None = None
    retrieval_cases: list[EvalRetrievalCaseInput] | None = None
