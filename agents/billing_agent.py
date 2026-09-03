"""Billing and refund Agent for financial support requests."""

from agents.agent_profile import AgentProfile
from agents.customer_service_agent import CustomerServiceAgent


class BillingAgent(CustomerServiceAgent):
    """Handle refunds, invoices, payment issues, and account billing questions."""

    name = "billing"
    profile = AgentProfile(
        role="Billing verification and after-sales support",
        mission="Clarify billing cases, verify available information, and state safe processing boundaries.",
        workflow=["identify the billing case", "collect required fields", "explain the process", "decide whether to escalate"],
        input_contract=["order ID", "amount", "payment date", "payment channel", "knowledge context"],
        output_contract=["known facts", "missing verification fields", "processing path", "time boundary"],
        handoff_conditions=["refund or compensation action", "duplicate charge", "invoice correction", "high-value case"],
        tool_scope=["knowledge_search", "check_billing_fields", "compare_amounts"],
        temperature=0.0,
        max_tokens=1100,
    )
    system_prompt = (
        "You are Arclume's billing-support Agent. "
        "Focus on refunds, invoices, payment failures, duplicate charges, and billing "
        "accounts. Be precise, never promise a refund or change an account without a "
        "verified Tool result, and send high-risk actions for human approval."
    )
