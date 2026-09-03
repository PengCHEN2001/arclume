"""Billing and refund Agent for financial support requests."""

from agents.customer_service_agent import CustomerServiceAgent


class BillingAgent(CustomerServiceAgent):
    """Handle refunds, invoices, payment issues, and account billing questions."""

    name = "billing"
    system_prompt = (
        "You are Arclume's billing-support Agent. "
        "Focus on refunds, invoices, payment failures, duplicate charges, and billing "
        "accounts. Be precise, never promise a refund or change an account without a "
        "verified Tool result, and send high-risk actions for human approval."
    )
