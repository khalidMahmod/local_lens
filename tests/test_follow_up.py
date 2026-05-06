"""Pure-logic + light async-IO tests for bot.follow_up."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot import data_loader, follow_up
from bot.models import Session


def _accepted_session(
    user_id: str = "42",
    *,
    accepted_at: datetime | None = None,
    follow_up_sent_at: str | None = None,
    state: str = "accepted",
) -> Session:
    return Session(
        telegram_user_id=user_id,
        current_state=state,
        accepted_at=accepted_at.isoformat() if accepted_at else None,
        follow_up_sent_at=follow_up_sent_at,
        commitment_price=15,
        active_package_id="pkg-x",
    )


# ---- find_due (pure) ------------------------------------------------------

def test_session_due_when_two_hours_have_passed():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = _accepted_session(accepted_at=now - timedelta(hours=2, minutes=1))
    assert follow_up.find_due([s], now) == [s]


def test_session_not_due_when_less_than_two_hours():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = _accepted_session(accepted_at=now - timedelta(hours=1, minutes=30))
    assert follow_up.find_due([s], now) == []


def test_session_at_exact_threshold_is_due():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = _accepted_session(accepted_at=now - timedelta(hours=2))
    assert follow_up.find_due([s], now) == [s]


def test_already_sent_session_is_skipped():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = _accepted_session(
        accepted_at=now - timedelta(hours=3),
        follow_up_sent_at=(now - timedelta(hours=1)).isoformat(),
    )
    assert follow_up.find_due([s], now) == []


def test_non_accepted_state_is_skipped():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = _accepted_session(
        accepted_at=now - timedelta(hours=3),
        state="chatting",
    )
    assert follow_up.find_due([s], now) == []


def test_follow_up_pending_state_is_skipped():
    """A session that already moved past `accepted` doesn't get a second DM."""
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = _accepted_session(
        accepted_at=now - timedelta(hours=3),
        state="follow_up_pending",
    )
    assert follow_up.find_due([s], now) == []


def test_session_with_no_accepted_at_is_skipped():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = _accepted_session(accepted_at=None)
    assert follow_up.find_due([s], now) == []


def test_session_with_unparseable_accepted_at_is_skipped():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = Session(
        telegram_user_id="42",
        current_state="accepted",
        accepted_at="not-a-timestamp",
    )
    assert follow_up.find_due([s], now) == []


def test_naive_accepted_at_is_treated_as_utc():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    naive = (now - timedelta(hours=3)).replace(tzinfo=None).isoformat()
    s = Session(
        telegram_user_id="42",
        current_state="accepted",
        accepted_at=naive,
    )
    assert follow_up.find_due([s], now) == [s]


def test_after_hours_param_is_honoured():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    s = _accepted_session(accepted_at=now - timedelta(hours=4))
    # Default 2h: due. With 6h threshold: not yet.
    assert follow_up.find_due([s], now) == [s]
    assert follow_up.find_due([s], now, after_hours=6) == []


def test_find_due_returns_only_eligible_from_mixed_list():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    due = _accepted_session("1", accepted_at=now - timedelta(hours=3))
    too_recent = _accepted_session("2", accepted_at=now - timedelta(hours=1))
    already_sent = _accepted_session(
        "3",
        accepted_at=now - timedelta(hours=3),
        follow_up_sent_at=(now - timedelta(hours=1)).isoformat(),
    )
    out = follow_up.find_due([due, too_recent, already_sent], now)
    assert [s.telegram_user_id for s in out] == ["1"]


# ---- tick (async, with disk + fake bot) ----------------------------------

class _FakeBot:
    """Minimal stand-in for telegram.Bot — records sends, never raises."""

    def __init__(self, *, fail_for: set[int] | None = None) -> None:
        self.sent: list[dict] = []
        self.fail_for = fail_for or set()

    async def send_message(self, *, chat_id, text, reply_markup=None) -> None:
        if chat_id in self.fail_for:
            raise RuntimeError(f"simulated send failure for {chat_id}")
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})


@pytest.mark.asyncio
async def test_tick_sends_dm_and_marks_follow_up_sent(tmp_path: Path):
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    s = _accepted_session("99", accepted_at=now - timedelta(hours=3))
    data_loader.save_session(s, sessions_dir)

    bot = _FakeBot()
    sent = await follow_up.tick(now, bot=bot, sessions_dir=sessions_dir)

    assert sent == ["99"]
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == 99
    assert "How was the plan" in bot.sent[0]["text"]

    persisted = data_loader.load_session("99", sessions_dir)
    assert persisted is not None
    assert persisted.follow_up_sent_at is not None
    assert persisted.current_state == "follow_up_pending"


@pytest.mark.asyncio
async def test_tick_is_idempotent(tmp_path: Path):
    """Second tick after a send must not re-DM."""
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    s = _accepted_session("99", accepted_at=now - timedelta(hours=3))
    data_loader.save_session(s, sessions_dir)

    bot = _FakeBot()
    await follow_up.tick(now, bot=bot, sessions_dir=sessions_dir)
    second_run = await follow_up.tick(now + timedelta(minutes=15), bot=bot, sessions_dir=sessions_dir)

    assert second_run == []
    assert len(bot.sent) == 1


@pytest.mark.asyncio
async def test_tick_skips_when_send_fails_so_retry_is_possible(tmp_path: Path):
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    s = _accepted_session("99", accepted_at=now - timedelta(hours=3))
    data_loader.save_session(s, sessions_dir)

    bot = _FakeBot(fail_for={99})
    sent = await follow_up.tick(now, bot=bot, sessions_dir=sessions_dir)

    assert sent == []
    persisted = data_loader.load_session("99", sessions_dir)
    assert persisted is not None
    # No state change → next tick gets to retry.
    assert persisted.follow_up_sent_at is None
    assert persisted.current_state == "accepted"


@pytest.mark.asyncio
async def test_tick_handles_empty_dir(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    bot = _FakeBot()
    assert await follow_up.tick(now, bot=bot, sessions_dir=sessions_dir) == []
    assert bot.sent == []
