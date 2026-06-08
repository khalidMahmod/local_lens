"""Handoff: notify the business owner via Telegram and reply to the customer."""

from __future__ import annotations


def format_owner_notification(
    *,
    customer_name: str,
    package_name: str | None,
    price_rm: int | None,
    sender_id: str,
) -> str:
    lines = ["New lead from Messenger:", f"Name: {customer_name}"]
    if package_name:
        price_str = f"RM{price_rm}" if price_rm else "N/A"
        lines.append(f"Interested in: {package_name} ({price_str})")
    else:
        lines.append("General inquiry — no specific package selected.")
    lines.append(f"Messenger ID: {sender_id}")
    lines.append("\nReply to them on Messenger.")
    return "\n".join(lines)


def format_customer_reply() -> str:
    return (
        "Great choice! Let me connect you with our team — "
        "they'll reply shortly."
    )
