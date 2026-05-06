"""Pure-logic onboarding state machine.

`transition(session, event) -> Session` returns a new Session for each event.
The handlers in `bot.handlers` translate Telegram updates into events here, then
persist the result via `bot.data_loader.save_session`.

Events (each is a dict with a `"type"` key):
    {"type": "start"}
    {"type": "location", "lat": float, "lng": float}
    {"type": "dietary",  "halal_only": bool}
    {"type": "intent",   "intent": str}

Use `set_dietary_preference` for the `/diet` command (changes pref without
moving through the state machine).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from bot.models import DietaryPref, Session


class InvalidTransition(Exception):
    """Raised when an event arrives in a state that doesn't accept it."""


def transition(session: Session, event: dict[str, Any]) -> Session:
    event_type = event.get("type")
    if event_type == "start":
        return _on_start(session)
    if event_type == "location":
        return _on_location(session, float(event["lat"]), float(event["lng"]))
    if event_type == "dietary":
        return _on_dietary(session, bool(event["halal_only"]))
    if event_type == "intent":
        return _on_intent(session, str(event["intent"]))
    raise ValueError(f"Unknown event type: {event_type!r}")


def set_dietary_preference(
    session: Session, halal_only: bool, source: str = "asked"
) -> Session:
    """Update dietary preference without changing state. Used by /diet."""
    return replace(
        session,
        dietary=DietaryPref(halal_only=halal_only, source=source),
    )


def offer_premium_package(session: Session, package_id: str) -> Session:
    """Move into `package_offered` after the tease is shown.

    Allowed from `chatting` (fresh tease) or `package_offered` (re-tease, e.g.
    user sent a new query before accepting the previous one).
    """
    if session.current_state not in {"chatting", "package_offered"}:
        raise InvalidTransition(
            f"premium tease not accepted in state {session.current_state!r}"
        )
    return replace(
        session,
        current_state="package_offered",
        active_package_id=package_id,
        dietary=replace(session.dietary),
    )


def mark_follow_up_sent(session: Session, sent_at_iso: str) -> Session:
    """Record the follow-up DM timestamp and move into `follow_up_pending`.

    Idempotent in spirit: callers should check `follow_up_sent_at` before
    invoking. This helper raises if state isn't `accepted`, so a
    double-fire still becomes visible at the boundary.
    """
    if session.current_state != "accepted":
        raise InvalidTransition(
            f"follow-up not allowed in state {session.current_state!r}"
        )
    return replace(
        session,
        current_state="follow_up_pending",
        follow_up_sent_at=sent_at_iso,
        dietary=replace(session.dietary),
    )


def accept_premium_package(
    session: Session, package_id: str, price_rm: int, accepted_at_iso: str
) -> Session:
    """Record the soft commitment after the user taps "Want full plan?"."""
    if session.current_state != "package_offered":
        raise InvalidTransition(
            f"premium accept not allowed in state {session.current_state!r}"
        )
    if session.active_package_id != package_id:
        raise InvalidTransition(
            f"accepting {package_id!r} but active package is {session.active_package_id!r}"
        )
    return replace(
        session,
        current_state="accepted",
        commitment_price=int(price_rm),
        accepted_at=accepted_at_iso,
        dietary=replace(session.dietary),
    )


def _on_start(session: Session) -> Session:
    return replace(
        session,
        current_state="awaiting_location",
        dietary=replace(session.dietary),
    )


def _on_location(session: Session, lat: float, lng: float) -> Session:
    location = {"lat": lat, "lng": lng}
    if session.current_state == "awaiting_location":
        return replace(
            session,
            current_state="awaiting_dietary",
            location=location,
            dietary=replace(session.dietary),
        )
    if session.current_state == "chatting":
        return replace(
            session,
            location=location,
            dietary=replace(session.dietary),
        )
    raise InvalidTransition(
        f"location event not accepted in state {session.current_state!r}"
    )


def _on_dietary(session: Session, halal_only: bool) -> Session:
    if session.current_state != "awaiting_dietary":
        raise InvalidTransition(
            f"dietary event not accepted in state {session.current_state!r}"
        )
    return replace(
        session,
        current_state="awaiting_intent",
        dietary=DietaryPref(halal_only=halal_only, source="asked"),
    )


def _on_intent(session: Session, intent: str) -> Session:
    if session.current_state != "awaiting_intent":
        raise InvalidTransition(
            f"intent event not accepted in state {session.current_state!r}"
        )
    if not intent:
        raise ValueError("intent must be a non-empty string")
    return replace(
        session,
        current_state="chatting",
        dietary=replace(session.dietary),
    )
