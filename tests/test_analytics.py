"""Tests for bot.analytics — the JSONL event log."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bot import analytics


def test_log_event_appends_one_jsonl_line(tmp_path: Path):
    log = tmp_path / "analytics.jsonl"
    fixed = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
    analytics.log_event(
        "query",
        "42",
        {"text_length": 12},
        path=log,
        now=fixed,
    )
    [line] = log.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record == {
        "ts": fixed.isoformat(),
        "event": "query",
        "user_id": "42",
        "payload": {"text_length": 12},
    }


def test_log_event_appends_subsequent_calls(tmp_path: Path):
    log = tmp_path / "analytics.jsonl"
    analytics.log_event("query", "1", path=log)
    analytics.log_event("package_offered", "1", {"package_id": "p"}, path=log)
    analytics.log_event("package_accepted", "1", {"package_id": "p"}, path=log)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == [
        "query",
        "package_offered",
        "package_accepted",
    ]


def test_log_event_rejects_unknown_event_type(tmp_path: Path):
    log = tmp_path / "analytics.jsonl"
    with pytest.raises(ValueError):
        analytics.log_event("bogus_event", "1", path=log)
    assert not log.exists()


def test_log_event_creates_parent_dir(tmp_path: Path):
    log = tmp_path / "subdir" / "analytics.jsonl"
    analytics.log_event("query", "1", path=log)
    assert log.exists()


def test_log_event_omits_payload_when_empty(tmp_path: Path):
    log = tmp_path / "analytics.jsonl"
    analytics.log_event("feedback", "1", path=log)
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert record["payload"] == {}


def test_log_event_coerces_user_id_to_string(tmp_path: Path):
    log = tmp_path / "analytics.jsonl"
    analytics.log_event("query", 42, path=log)  # type: ignore[arg-type]
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert record["user_id"] == "42"


@pytest.mark.parametrize(
    "event",
    ["query", "package_offered", "package_accepted", "payment_sent", "payment_paid", "feedback"],
)
def test_all_documented_event_types_accepted(tmp_path: Path, event: str):
    log = tmp_path / "analytics.jsonl"
    analytics.log_event(event, "1", path=log)
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == event
