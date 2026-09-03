"""Technical-support Agent for login, error, and product failures."""

from agents.customer_service_agent import CustomerServiceAgent


class TechnicalAgent(CustomerServiceAgent):
    """Handle technical diagnosis and step-by-step troubleshooting."""

    name = "technical"
    system_prompt = (
        "You are Arclume's technical-support Agent. "
        "Focus on login failures, error codes, crashes, and configuration problems. "
        "Give safe, ordered troubleshooting steps, request missing diagnostic details, "
        "and never claim that a backend fix was completed without a verified Tool result."
    )
