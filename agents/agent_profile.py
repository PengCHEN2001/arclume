"""Structured role contracts for executable Agents."""

from pydantic import BaseModel, Field


class AgentProfile(BaseModel):
    """Describe one Agent's responsibility, workflow, and allowed Tool scope."""

    role: str = Field(min_length=1)                         # Human-readable role
    mission: str = Field(min_length=1)                      # Main responsibility
    workflow: list[str] = Field(default_factory=list)      # Ordered work stages
    input_contract: list[str] = Field(default_factory=list) # Accepted context fields
    output_contract: list[str] = Field(default_factory=list) # Required answer elements
    handoff_conditions: list[str] = Field(default_factory=list) # Escalation triggers
    tool_scope: list[str] = Field(default_factory=list)    # Allowed Tool names
    model: str | None = None                               # Optional per-Agent model
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
