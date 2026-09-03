"""General customer-service Agent for broad and mixed requests."""

from agents.customer_service_agent import CustomerServiceAgent


class GeneralAgent(CustomerServiceAgent):
    """Handle greetings, general questions, orders, logistics, and fallback work."""

    name = "general"
    system_prompt = (
        "You are Arclume's general customer-service Agent. "
        "Answer clearly and politely, use the supplied evidence, and ask a focused "
        "clarifying question when the request is ambiguous. Do not invent order, "
        "delivery, refund, or account facts. Escalate requests that require human judgment."
    )
