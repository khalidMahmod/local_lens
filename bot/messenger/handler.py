"""Route incoming Messenger events to actions."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    kind: str  # welcome, package_list, pricing_table, package_detail, handoff
    sender_id: str
    package_id: str | None = None


_GREETINGS = re.compile(r"^(hi|hello|hey|assalamualaikum|salam)\b", re.IGNORECASE)
_PRICE_KEYWORDS = re.compile(r"(price|cost|how much|berapa|harga)", re.IGNORECASE)
_PACKAGE_KEYWORDS = re.compile(r"(package|trip|tour|itinerary|plan)", re.IGNORECASE)


def route_event(event: dict) -> Action:
    sender_id = event["sender_id"]
    event_type = event.get("type")
    payload = event.get("payload", "")

    if event_type == "postback":
        if payload == "GET_STARTED":
            return Action(kind="welcome", sender_id=sender_id)
        return Action(kind="handoff", sender_id=sender_id)

    if event_type == "quick_reply":
        if payload == "VIEW_PACKAGES":
            return Action(kind="package_list", sender_id=sender_id)
        if payload == "GET_PRICING":
            return Action(kind="pricing_table", sender_id=sender_id)
        if payload == "TALK_TO_HUMAN":
            return Action(kind="handoff", sender_id=sender_id)
        if payload == "BACK_TO_PACKAGES":
            return Action(kind="package_list", sender_id=sender_id)
        if payload.startswith("PKG:"):
            pkg_id = payload.split(":", 1)[1]
            return Action(kind="package_detail", sender_id=sender_id, package_id=pkg_id)
        if payload.startswith("BOOK:") or payload.startswith("ASK_QUESTION:"):
            pkg_id = payload.split(":", 1)[1]
            return Action(kind="handoff", sender_id=sender_id, package_id=pkg_id)
        return Action(kind="handoff", sender_id=sender_id)

    if event_type == "text":
        text = event.get("text", "")
        if _GREETINGS.search(text):
            return Action(kind="welcome", sender_id=sender_id)
        if _PRICE_KEYWORDS.search(text):
            return Action(kind="pricing_table", sender_id=sender_id)
        if _PACKAGE_KEYWORDS.search(text):
            return Action(kind="package_list", sender_id=sender_id)
        return Action(kind="handoff", sender_id=sender_id)

    return Action(kind="handoff", sender_id=sender_id)
