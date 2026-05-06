"""Tests for ingest.extractor — vision call to OpenAI, mocked end-to-end."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from openai import APIStatusError, RateLimitError

from ingest import extractor
from ingest.models import RawItem


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "thumbnails" / "sample_dish.jpg"


def _raw_item(thumbnail_path: Path | None = None) -> RawItem:
    return RawItem(
        reel_id="DCxAbc123",
        candidate_id="ig_DCxAbc123",
        source_url="https://www.instagram.com/reel/DCxAbc123/",
        thumbnail_path=thumbnail_path or _FIXTURE_PATH,
        caption="Best char kuey teow at Restoran Win Heng Seng, Jalan Imbi. Closes 1pm. #KLfoodie",
        play_count=12000,
        like_count=400,
        posted_at="2026-05-01T18:00:00+08:00",
        scraped_at="2026-05-06T14:30:00+08:00",
    )


# ---- a fake OpenAI client (records calls, returns canned responses) ------

@dataclass
class _FakeResponse:
    content: str

    @property
    def choices(self):
        return [type("Choice", (), {"message": type("Msg", (), {"content": self.content})()})()]


@dataclass
class _FakeCompletions:
    canned_responses: list[Any]
    calls: list[dict] = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.canned_responses:
            raise AssertionError("FakeCompletions: no more canned responses")
        next_value = self.canned_responses.pop(0)
        if isinstance(next_value, Exception):
            raise next_value
        return _FakeResponse(content=next_value)


@dataclass
class _FakeChat:
    completions: _FakeCompletions


@dataclass
class _FakeOpenAI:
    chat: _FakeChat
    @classmethod
    def with_responses(cls, *responses) -> "_FakeOpenAI":
        return cls(chat=_FakeChat(completions=_FakeCompletions(list(responses))))


def _valid_extraction_json() -> str:
    return json.dumps(
        {
            "stall_name": "Restoran Win Heng Seng",
            "stall_name_confidence": "high",
            "dish_featured": "Char kuey teow",
            "viral_hook": "Wok hei shot at 0:08, queue out the door",
            "claimed_must_order": "Char kuey teow with extra duck egg",
            "halal_signals": "no_pork_visible",
            "operating_hours_mentioned": "Closes 1pm",
            "google_maps_search_query": "Restoran Win Heng Seng Jalan Imbi",
            "candidate_quality_score": 8,
            "extractor_notes": None,
        }
    )


# ---- happy path ----------------------------------------------------------

def test_happy_path_populates_full_extraction_block():
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    candidate = extractor.extract(_raw_item(), client=client)

    assert candidate.id == "ig_DCxAbc123"
    assert candidate.status == "pending"
    assert candidate.source_url == "https://www.instagram.com/reel/DCxAbc123/"
    assert candidate.source_platform == "instagram"
    assert candidate.thumbnail_path == str(_FIXTURE_PATH)

    assert candidate.stall_name == "Restoran Win Heng Seng"
    assert candidate.stall_name_confidence == "high"
    assert candidate.dish_featured == "Char kuey teow"
    assert candidate.viral_hook == "Wok hei shot at 0:08, queue out the door"
    assert candidate.halal_signals == "no_pork_visible"
    assert candidate.candidate_quality_score == 8
    assert candidate.extractor_notes is None

    # Manual-fill block stays null.
    assert candidate.lat is None
    assert candidate.halal_status is None
    assert candidate.insider_tip is None


def test_request_is_a_single_chat_completions_call():
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client)
    assert len(client.chat.completions.calls) == 1


def test_request_uses_json_object_response_format():
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client)
    [call] = client.chat.completions.calls
    assert call["response_format"] == {"type": "json_object"}


def test_request_includes_system_prompt_from_file():
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client)
    [call] = client.chat.completions.calls
    [system_msg, _user_msg] = call["messages"]
    assert system_msg["role"] == "system"
    # A line from the actual prompt file:
    assert "structured Candidate JSON" in system_msg["content"]


def test_request_uses_custom_prompt_path_when_provided(tmp_path: Path):
    prompt = tmp_path / "custom_prompt.txt"
    prompt.write_text("CUSTOM SYSTEM PROMPT", encoding="utf-8")
    client = _FakeOpenAI.with_responses(_valid_extraction_json())

    extractor.extract(_raw_item(), client=client, prompt_path=prompt)

    [call] = client.chat.completions.calls
    assert call["messages"][0]["content"] == "CUSTOM SYSTEM PROMPT"


def test_user_message_includes_caption_and_source_url():
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client)
    [call] = client.chat.completions.calls
    user_msg = call["messages"][1]
    assert user_msg["role"] == "user"
    text_part = next(p for p in user_msg["content"] if p["type"] == "text")
    assert "https://www.instagram.com/reel/DCxAbc123/" in text_part["text"]
    assert "Restoran Win Heng Seng" in text_part["text"]  # from caption


def test_image_is_base64_encoded_under_image_url_part():
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client)
    [call] = client.chat.completions.calls
    user_msg = call["messages"][1]
    image_part = next(p for p in user_msg["content"] if p["type"] == "image_url")
    url = image_part["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    payload = url.split(",", 1)[1]
    # Must be valid base64 of the fixture file's bytes.
    decoded = base64.b64decode(payload)
    assert decoded == _FIXTURE_PATH.read_bytes()


def test_image_uses_low_detail_to_cap_token_cost():
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client)
    [call] = client.chat.completions.calls
    image_part = next(p for p in call["messages"][1]["content"] if p["type"] == "image_url")
    assert image_part["image_url"]["detail"] == "low"


def test_uses_default_model_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INGEST_OPENAI_MODEL", raising=False)
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client)
    assert client.chat.completions.calls[0]["model"] == "gpt-4o-mini"


def test_respects_INGEST_OPENAI_MODEL_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INGEST_OPENAI_MODEL", "gpt-4o")
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client)
    assert client.chat.completions.calls[0]["model"] == "gpt-4o"


def test_explicit_model_arg_overrides_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INGEST_OPENAI_MODEL", "gpt-4o")
    client = _FakeOpenAI.with_responses(_valid_extraction_json())
    extractor.extract(_raw_item(), client=client, model="gpt-4.1-preview")
    assert client.chat.completions.calls[0]["model"] == "gpt-4.1-preview"


# ---- failure paths -------------------------------------------------------

def test_malformed_json_records_extractor_notes():
    client = _FakeOpenAI.with_responses("this is not JSON at all")
    candidate = extractor.extract(_raw_item(), client=client)

    assert candidate.id == "ig_DCxAbc123"
    assert candidate.status == "pending"
    assert candidate.stall_name is None
    assert candidate.extractor_notes is not None
    assert "extraction failed" in candidate.extractor_notes
    assert "malformed JSON" in candidate.extractor_notes


def test_non_object_json_records_failure():
    client = _FakeOpenAI.with_responses(json.dumps(["not", "an", "object"]))
    candidate = extractor.extract(_raw_item(), client=client)
    assert "extraction failed" in (candidate.extractor_notes or "")
    assert candidate.stall_name is None


def test_invalid_halal_signals_coerced_with_note():
    bad = json.dumps(
        {
            "stall_name": "X",
            "stall_name_confidence": "high",
            "halal_signals": "definitely_halal",  # not in HALAL_SIGNALS
            "candidate_quality_score": 5,
        }
    )
    client = _FakeOpenAI.with_responses(bad)
    candidate = extractor.extract(_raw_item(), client=client)
    assert candidate.halal_signals == "unclear"
    assert "invalid halal_signals" in (candidate.extractor_notes or "")


def test_invalid_stall_name_confidence_coerced_with_note():
    bad = json.dumps(
        {
            "stall_name": "X",
            "stall_name_confidence": "very_sure",  # not in STALL_NAME_CONFIDENCE
            "halal_signals": "unclear",
            "candidate_quality_score": 5,
        }
    )
    client = _FakeOpenAI.with_responses(bad)
    candidate = extractor.extract(_raw_item(), client=client)
    assert candidate.stall_name_confidence == "low"
    assert "invalid stall_name_confidence" in (candidate.extractor_notes or "")


def test_invalid_quality_score_dropped_with_note():
    bad = json.dumps(
        {
            "stall_name": "X",
            "stall_name_confidence": "high",
            "halal_signals": "unclear",
            "candidate_quality_score": "not-a-number",
        }
    )
    client = _FakeOpenAI.with_responses(bad)
    candidate = extractor.extract(_raw_item(), client=client)
    assert candidate.candidate_quality_score is None
    assert "invalid candidate_quality_score" in (candidate.extractor_notes or "")


# ---- retry logic ---------------------------------------------------------

def _make_rate_limit_error() -> RateLimitError:
    # RateLimitError takes message + response + body. We don't care about
    # internals — the extractor's `except RateLimitError` is what matters.
    response = type("R", (), {"status_code": 429, "headers": {}, "request": None})()
    return RateLimitError(message="rate limited", response=response, body=None)


def _make_5xx_error() -> APIStatusError:
    response = type("R", (), {"status_code": 503, "headers": {}, "request": None})()
    return APIStatusError(message="upstream blip", response=response, body=None)


def test_rate_limit_retries_once_and_succeeds():
    sleep_calls: list[float] = []
    client = _FakeOpenAI.with_responses(_make_rate_limit_error(), _valid_extraction_json())
    candidate = extractor.extract(_raw_item(), client=client, sleep=sleep_calls.append)
    assert candidate.stall_name == "Restoran Win Heng Seng"
    assert sleep_calls == [5]  # one backoff between attempts


def test_rate_limit_twice_yields_failed_candidate():
    sleep_calls: list[float] = []
    client = _FakeOpenAI.with_responses(
        _make_rate_limit_error(), _make_rate_limit_error()
    )
    candidate = extractor.extract(_raw_item(), client=client, sleep=sleep_calls.append)
    assert candidate.stall_name is None
    assert "rate limit after retry" in (candidate.extractor_notes or "")
    assert sleep_calls == [5]


def test_5xx_retries_once_and_succeeds():
    sleep_calls: list[float] = []
    client = _FakeOpenAI.with_responses(_make_5xx_error(), _valid_extraction_json())
    candidate = extractor.extract(_raw_item(), client=client, sleep=sleep_calls.append)
    assert candidate.stall_name == "Restoran Win Heng Seng"
    assert sleep_calls == [5]


def test_unknown_exception_does_not_retry():
    sleep_calls: list[float] = []
    client = _FakeOpenAI.with_responses(RuntimeError("network down"))
    candidate = extractor.extract(_raw_item(), client=client, sleep=sleep_calls.append)
    assert candidate.stall_name is None
    assert "openai call failed" in (candidate.extractor_notes or "")
    assert sleep_calls == []  # no backoff for unknown errors
