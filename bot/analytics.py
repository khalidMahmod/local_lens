"""Append-only JSONL event log.

One JSON line per event. No reads, no rotation — Phase 9 only needs to capture
events for after-the-fact inspection. A future analytics pipeline can tail or
batch-load the file.

Events (per spec § "Basic analytics" + plan Phase 9):
    query              — user sent a message in `chatting`
    package_offered    — a package (free or premium) was shown to the user
    package_accepted   — user tapped "Want full plan?" on a premium tease
    payment_sent       — user tapped "Loved it"; payment link delivered
    payment_paid       — out-of-band confirmation from ToyyibPay (deferred)
    feedback           — user tapped "Was meh"; free-text follow-up captured
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.data_loader import DATA_DIR

logger = logging.getLogger(__name__)

EVENT_TYPES = frozenset(
    {
        "query",
        "package_offered",
        "package_accepted",
        "payment_sent",
        "payment_paid",
        "feedback",
    }
)

ANALYTICS_PATH = DATA_DIR / "analytics.jsonl"


def log_event(
    event_type: str,
    user_id: str,
    payload: dict[str, Any] | None = None,
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> None:
    """Append one event line. Never raises — failures log a warning so analytics
    can't break a user-facing flow."""
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"Unknown event_type: {event_type!r}. Expected one of {sorted(EVENT_TYPES)}."
        )
    target = path or ANALYTICS_PATH
    record = {
        "ts": (now or datetime.now(timezone.utc)).isoformat(),
        "event": event_type,
        "user_id": str(user_id),
        "payload": dict(payload or {}),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Failed to write analytics event %s for user %s", event_type, user_id)
