"""Small internal Tool functions and their Harness registrations."""

from typing import Any

from harness.executor import ToolDefinition, ToolExecutor
from harness.policy import ToolRiskLevel


async def knowledge_search(
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Search the existing KnowledgeBase without duplicating retrieval logic."""

    knowledge_base = (context or {}).get("knowledge_base")  # Injected service dependency
    if knowledge_base is None:
        raise RuntimeError("KnowledgeBase is not available")
    return await knowledge_base.search_async(
        arguments["query"],
        top_k=arguments.get("top_k", 3),
    )


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
            allowed_agents={"customer_service"},
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
            allowed_agents={"customer_service"},
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
            allowed_agents={"customer_service"},
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
            allowed_agents={"customer_service"},
        )
    )
    return executor
