"""Small internal Tool functions and their Harness registrations."""

from typing import Any

from harness.executor import ToolDefinition, ToolExecutor
from harness.policy import ToolRiskLevel


ALLOWED_AGENT_NAMES = {"customer_service", "general", "technical", "billing", "escalation"}


async def knowledge_search(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Search the existing KnowledgeBase without duplicating retrieval logic."""

    data = context or {}
    tool_manager = data.get("tool_manager")
    if tool_manager is not None and hasattr(tool_manager, "search_with_rewrite"):
        return await tool_manager.search_with_rewrite(
            arguments["query"],
            top_k=arguments.get("top_k", 3),
        )

    knowledge_base = data.get("knowledge_base")  # Injected service dependency
    if knowledge_base is None:
        raise RuntimeError("KnowledgeBase is not available")
    results = await knowledge_base.search_async(arguments["query"], top_k=arguments.get("top_k", 3))
    return {
        "query": arguments["query"],
        "queries": [arguments["query"]],
        "results": results,
        "reranked": False,
        "rerank_method": "none",
        "degraded": False,
    }


def knowledge_search_fallback(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return an explicit empty retrieval result when the knowledge service fails."""

    return {
        "query": str(arguments.get("query", "")),
        "queries": [],
        "results": [],
        "reranked": False,
        "rerank_method": "none",
        "degraded": True,
        "message": "Knowledge retrieval is temporarily unavailable.",
    }


def suggest_required_fields(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Suggest only the missing fields needed for the current support intent."""

    intent = str((context or {}).get("intent") or "other")
    entities = (context or {}).get("entities") or {}
    required_by_intent = {
        "order_status": ["order_id"],
        "logistics": ["order_id or tracking_id"],
        "refund": ["order_id", "amount"],
        "payment_issue": ["order_id", "amount", "date"],
        "technical_login": ["error message", "environment"],
        "technical_crash": ["error message", "app version", "environment"],
    }
    required = required_by_intent.get(intent, ["a clear description of the issue"])
    missing = [
        field
        for field in required
        if not any(entities.get(option) for option in field.split(" or "))
    ]
    return {"intent": intent, "missing_fields": missing, "known_entities": entities}


def inspect_request_context(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the non-sensitive structured information already available to an Agent."""

    data = context or {}
    return {
        "intent": data.get("intent"),
        "entities": data.get("entities") or {},
        "agent_name": data.get("agent_name"),
        "requested_focus": str(arguments.get("focus", "general"))[:40],
    }


def lookup_error_code(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Explain common error codes without claiming access to backend logs."""

    code = str(arguments.get("error_code", "")).upper().strip()
    mapping = {
        "401": ("Authentication failed", ["Check session or credentials", "Try a safe sign-in reset"]),
        "403": ("Permission denied", ["Check account permissions", "Confirm the requested resource"]),
        "404": ("Resource not found", ["Check the resource identifier", "Confirm the service environment"]),
        "500": ("Server-side failure", ["Retry later", "Record the time and request details for support"]),
    }
    meaning, next_steps = mapping.get(
        code,
        ("Unknown error code", ["Provide the full error message and the environment"]),
    )
    return {"error_code": code, "meaning": meaning, "next_steps": next_steps, "backend_logs_checked": False}


def build_diagnostic_plan(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create a low-risk troubleshooting order without changing external systems."""

    environment = str(arguments.get("environment", "unknown"))[:80]
    reproduced = bool(arguments.get("reproduced", False))
    steps = [
        "Capture the complete error message",
        "Check network, permissions, and configuration",
        "Confirm the version and the latest change",
    ]
    if reproduced:
        steps.append("Reproduce with the smallest safe request and record the result")
    return {"environment": environment, "reproduced": reproduced, "diagnostic_steps": steps}


def check_billing_fields(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Check billing information without connecting to a payment system."""

    data = context or {}
    entities = data.get("entities") or {}
    fields = {
        "order_id": bool(entities.get("order_id")),
        "amount": bool(entities.get("amount")),
        "date": bool(entities.get("date")),
        "payment_channel": bool(arguments.get("payment_channel")),
    }
    return {
        "fields": fields,
        "missing_fields": [name for name, present in fields.items() if not present],
        "can_confirm_refund": False,
    }


def compare_amounts(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Calculate a difference between two user-provided amounts only."""

    first = float(arguments["amount_a"])
    second = float(arguments["amount_b"])
    return {
        "amount_a": first,
        "amount_b": second,
        "difference": round(first - second, 2),
        "interpretation": "This is arithmetic only; it does not confirm a duplicate charge.",
    }


def create_handoff_summary(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create a safe handoff summary without creating a real ticket."""

    data = context or {}
    return {
        "request_id": data.get("request_id"),
        "reason": str(arguments.get("reason", "Further human review is required"))[:120],
        "intent": data.get("intent"),
        "entities": data.get("entities") or {},
        "ticket_created": False,
    }


def order_query(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return deterministic mock order data for Harness tests."""

    order_id = arguments["order_id"].strip()  # Business identifier from the request
    return {
        "order_id": order_id,
        "status": "shipped",
        "updated_at": "2026-08-26T09:00:00Z",
        "message": "Mock order data; no external order system is connected yet.",
    }


def logistics_query(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return deterministic mock logistics data for Harness tests."""

    tracking_id = arguments["tracking_id"].strip()  # Shipment identifier from the request
    return {
        "tracking_id": tracking_id,
        "status": "in_transit",
        "estimated_delivery": "2026-08-29",
        "message": "Mock logistics data; no external carrier is connected yet.",
    }


def ticket_create(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a mock ticket result when a later policy allows execution."""

    return {
        "ticket_id": "TICKET-MOCK-001",
        "customer_id": arguments["customer_id"].strip(),
        "summary": arguments["summary"].strip(),
        "status": "pending_creation",
        "message": "Mock ticket data; no ticketing system is connected yet.",
    }


def register_tools(executor: ToolExecutor) -> ToolExecutor:
    """Register all current internal Tools in the shared Harness Executor."""

    executor.register(
        ToolDefinition(
            name="knowledge_search",
            description="Search the customer-support knowledge base.",
            handler=knowledge_search,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=10.0,
            max_retries=1,
            cache_ttl_seconds=300.0,
            supports_rerank=True,
            fallback=knowledge_search_fallback,
            allowed_agents=set(ALLOWED_AGENT_NAMES),
        )
    )
    executor.register(
        ToolDefinition(
            name="suggest_required_fields",
            description="Suggest the missing fields needed to continue a support request.",
            handler=suggest_required_fields,
            input_schema={"type": "object", "properties": {}},
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            allowed_agents={"general"},
        )
    )
    executor.register(
        ToolDefinition(
            name="inspect_request_context",
            description="Inspect the structured, non-sensitive context already available for this request.",
            handler=inspect_request_context,
            input_schema={
                "type": "object",
                "properties": {"focus": {"type": "string"}},
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            allowed_agents={"general"},
        )
    )
    executor.register(
        ToolDefinition(
            name="lookup_error_code",
            description="Explain a common error code and safe next checks.",
            handler=lookup_error_code,
            input_schema={
                "type": "object",
                "required": ["error_code"],
                "properties": {"error_code": {"type": "string"}},
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            allowed_agents={"technical"},
        )
    )
    executor.register(
        ToolDefinition(
            name="build_diagnostic_plan",
            description="Build a low-risk troubleshooting plan from the environment and reproduction status.",
            handler=build_diagnostic_plan,
            input_schema={
                "type": "object",
                "required": ["environment", "reproduced"],
                "properties": {
                    "environment": {"type": "string"},
                    "reproduced": {"type": "boolean"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            allowed_agents={"technical"},
        )
    )
    executor.register(
        ToolDefinition(
            name="check_billing_fields",
            description="Check whether the known billing fields are sufficient for verification.",
            handler=check_billing_fields,
            input_schema={
                "type": "object",
                "properties": {"payment_channel": {"type": "string"}},
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            allowed_agents={"billing"},
        )
    )
    executor.register(
        ToolDefinition(
            name="compare_amounts",
            description="Calculate the difference between two explicitly provided amounts.",
            handler=compare_amounts,
            input_schema={
                "type": "object",
                "required": ["amount_a", "amount_b"],
                "properties": {
                    "amount_a": {"type": "number"},
                    "amount_b": {"type": "number"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            allowed_agents={"billing"},
        )
    )
    executor.register(
        ToolDefinition(
            name="create_handoff_summary",
            description="Create a structured human-support handoff summary without creating a ticket.",
            handler=create_handoff_summary,
            input_schema={
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            allowed_agents={"escalation"},
        )
    )
    executor.register(
        ToolDefinition(
            name="order_query",
            description="Query mock order information by order ID.",
            handler=order_query,
            input_schema={
                "type": "object",
                "required": ["order_id"],
                "properties": {"order_id": {"type": "string"}},
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            cache_ttl_seconds=30.0,
            allowed_agents=set(ALLOWED_AGENT_NAMES),
        )
    )
    executor.register(
        ToolDefinition(
            name="logistics_query",
            description="Query mock logistics information by tracking ID.",
            handler=logistics_query,
            input_schema={
                "type": "object",
                "required": ["tracking_id"],
                "properties": {"tracking_id": {"type": "string"}},
            },
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=5.0,
            cache_ttl_seconds=30.0,
            allowed_agents=set(ALLOWED_AGENT_NAMES),
        )
    )
    executor.register(
        ToolDefinition(
            name="ticket_create",
            description="Create a customer-support ticket after human approval.",
            handler=ticket_create,
            input_schema={
                "type": "object",
                "required": ["customer_id", "summary"],
                "properties": {
                    "customer_id": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
            risk_level=ToolRiskLevel.HIGH,
            timeout_seconds=5.0,
            allowed_agents=set(ALLOWED_AGENT_NAMES),
        )
    )
    return executor
