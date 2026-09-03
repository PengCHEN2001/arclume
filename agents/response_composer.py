"""Deterministic response composition for multi-Agent requests."""

from collections.abc import Sequence
from typing import Any


class ResponseComposer:
    """Keep the primary answer first and add distinct supporting information."""

    def compose(
        self,
        responses: Sequence[Any],
        *,
        primary_agent: str,
    ) -> str:
        """Return one user-facing answer without another model call."""

        successful = [
            response
            for response in responses
            if getattr(response, "success", False)
            and str(getattr(response, "content", "")).strip()
        ]
        if not successful:
            return "The support Agents were unable to complete this request."

        ordered = sorted(
            successful,
            key=lambda response: 0
            if getattr(getattr(response, "agent_type", None), "value", None)
            == primary_agent
            else 1,
        )
        primary_content = str(ordered[0].content).strip()
        supporting = [
            str(response.content).strip()
            for response in ordered[1:]
            if str(response.content).strip() != primary_content
        ]
        if not supporting:
            return primary_content
        return primary_content + "\n\nAdditional information:\n" + "\n\n".join(supporting)
