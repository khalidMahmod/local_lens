"""Post-experience follow-up scheduler. Spec lines 245–249.

`find_due` is pure-logic (testable). `tick` is the scheduler entry point — it
loads sessions from disk, sends Telegram DMs for due ones, and marks
`follow_up_sent_at` so a re-run won't double-DM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from bot import analytics, data_loader
from bot.conversation import InvalidTransition, mark_follow_up_sent
from bot.keyboards import follow_up_keyboard
from bot.models import Session

logger = logging.getLogger(__name__)

DEFAULT_DELAY_HOURS = 2

FOLLOW_UP_TEXT = "How was the plan? Did you enjoy it?"


def find_due(
    sessions: Iterable[Session],
    now: datetime,
    *,
    after_hours: int = DEFAULT_DELAY_HOURS,
) -> list[Session]:
    """Return sessions that should receive a follow-up DM right now.

    A session is due iff:
      - `current_state == "accepted"`
      - `accepted_at` is a parseable ISO timestamp
      - `now >= accepted_at + after_hours`
      - `follow_up_sent_at` is not yet set (idempotency)
    """
    due: list[Session] = []
    threshold = timedelta(hours=after_hours)
    for s in sessions:
        if s.current_state != "accepted":
            continue
        if s.follow_up_sent_at is not None:
            continue
        if not s.accepted_at:
            continue
        try:
            accepted = datetime.fromisoformat(s.accepted_at)
        except ValueError:
            logger.warning(
                "Session %s has unparseable accepted_at=%r — skipping",
                s.telegram_user_id,
                s.accepted_at,
            )
            continue
        # Naive timestamps are treated as UTC — sessions saved before tz-aware
        # writes existed shouldn't crash the scheduler.
        if accepted.tzinfo is None:
            accepted = accepted.replace(tzinfo=timezone.utc)
        if now - accepted >= threshold:
            due.append(s)
    return due


async def tick(
    now: datetime,
    *,
    bot,
    sessions_dir: Path | None = None,
    after_hours: int = DEFAULT_DELAY_HOURS,
) -> list[str]:
    """Scan sessions, DM each due user, mark `follow_up_sent_at`.

    Returns the list of user_ids that were DM'd this tick.
    """
    sessions = data_loader.iter_sessions(sessions_dir)
    due = find_due(sessions, now, after_hours=after_hours)
    sent: list[str] = []
    for session in due:
        try:
            await bot.send_message(
                chat_id=int(session.telegram_user_id),
                text=FOLLOW_UP_TEXT,
                reply_markup=follow_up_keyboard(),
            )
        except Exception:
            logger.exception(
                "Follow-up DM failed for user %s; will retry next tick",
                session.telegram_user_id,
            )
            continue
        try:
            updated = mark_follow_up_sent(session, now.isoformat())
        except InvalidTransition:
            logger.exception(
                "mark_follow_up_sent rejected for user %s in state %s",
                session.telegram_user_id,
                session.current_state,
            )
            continue
        data_loader.save_session(updated, sessions_dir)
        sent.append(session.telegram_user_id)
    return sent
