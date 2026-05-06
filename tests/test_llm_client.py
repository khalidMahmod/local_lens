"""Tests for bot.llm_client. The OpenAI client is faked end-to-end —
no network calls, no API key required.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from bot.llm_client import generate_free_recommendations
from bot.models import Context, Restaurant, Weather


def _restaurant(
    id_: str,
    *,
    name: str | None = None,
    halal_status: str = "halal_certified",
    meal_tags: list[str] | None = None,
) -> Restaurant:
    return Restaurant(
        id=id_,
        name=name or id_,
        lat=3.1565,
        lng=101.7124,
        area="KLCC",
        cuisine="Test",
        price_tier="$",
        meal_tags=list(meal_tags) if meal_tags is not None else ["lunch"],
        indoor=True,
        vibe_tags=[],
        halal_status=halal_status,
        insider_tip="Order the special.",
        google_maps_link="https://maps.app.goo.gl/test",
    )


def _context(window: str = "lunch") -> Context:
    return Context(
        lat=3.1565,
        lng=101.7124,
        area_name="KLCC",
        weather=Weather(condition="clouds", description="scattered clouds", temp_c=30.0),
        time_of_day_window=window,
    )


# Fake mirrors the OpenAI shape: client.chat.completions.create(...) →
# response.choices[0].message.content
class _FakeCompletions:
    def __init__(self, response_text: str = "Mock response"):
        self.calls: list[dict[str, Any]] = []
        self._response_text = response_text

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self._response_text))
            ]
        )


class _FakeChat:
    def __init__(self, response_text: str = "Mock response"):
        self.completions = _FakeCompletions(response_text)


class _FakeClient:
    def __init__(self, response_text: str = "Mock response"):
        self.chat = _FakeChat(response_text)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.chat.completions.calls


def _user_message_text(call: dict[str, Any]) -> str:
    return call["messages"][-1]["content"]


def _system_message_text(call: dict[str, Any]) -> str:
    msgs = call["messages"]
    assert msgs[0]["role"] == "system", "first message must be the system prompt"
    return msgs[0]["content"]


# ---- model + system prompt -------------------------------------------------

def test_default_model_is_gpt_4o_mini():
    client = _FakeClient()
    generate_free_recommendations(
        _context(),
        [_restaurant("a")],
        [{"role": "user", "text": "hi"}],
        client=client,
    )
    assert client.calls[0]["model"] == "gpt-4o-mini"


def test_model_override_respected():
    client = _FakeClient()
    generate_free_recommendations(
        _context(),
        [_restaurant("a")],
        [{"role": "user", "text": "hi"}],
        client=client,
        model="gpt-4o",
    )
    assert client.calls[0]["model"] == "gpt-4o"


def test_system_prompt_loaded_from_file(tmp_path):
    prompt_path = tmp_path / "sp.txt"
    prompt_path.write_text("YOU ARE LOCALLENS — TEST SENTINEL")
    client = _FakeClient()
    generate_free_recommendations(
        _context(),
        [_restaurant("a")],
        [{"role": "user", "text": "hi"}],
        client=client,
        system_prompt_path=prompt_path,
    )
    assert "YOU ARE LOCALLENS — TEST SENTINEL" in _system_message_text(client.calls[0])


def test_system_prompt_is_first_message():
    client = _FakeClient()
    generate_free_recommendations(
        _context(),
        [_restaurant("a")],
        [{"role": "user", "text": "hi"}],
        client=client,
    )
    msgs = client.calls[0]["messages"]
    assert msgs[0]["role"] == "system"


# ---- restaurant picks in user message --------------------------------------

def test_each_restaurant_pick_serialized_into_user_message():
    picks = [
        _restaurant("nasi-kandar-pelita", name="Nasi Kandar Pelita"),
        _restaurant("yut-kee", name="Yut Kee Restaurant"),
    ]
    client = _FakeClient()
    generate_free_recommendations(
        _context(),
        picks,
        [{"role": "user", "text": "lunch suggestions?"}],
        client=client,
    )
    user_text = _user_message_text(client.calls[0])
    assert "Nasi Kandar Pelita" in user_text
    assert "Yut Kee Restaurant" in user_text


def test_restaurant_maps_link_included():
    pick = _restaurant("a", name="Spot A")
    client = _FakeClient()
    generate_free_recommendations(
        _context(),
        [pick],
        [{"role": "user", "text": "hi"}],
        client=client,
    )
    assert "https://maps.app.goo.gl/test" in _user_message_text(client.calls[0])


def test_restaurant_halal_status_included():
    pick = _restaurant("a", halal_status="muslim_friendly")
    client = _FakeClient()
    generate_free_recommendations(
        _context(),
        [pick],
        [{"role": "user", "text": "hi"}],
        client=client,
    )
    assert "muslim_friendly" in _user_message_text(client.calls[0])


# ---- context fields in user message ----------------------------------------

def test_context_fields_present_in_user_message():
    client = _FakeClient()
    generate_free_recommendations(
        _context(window="lunch"),
        [_restaurant("a")],
        [{"role": "user", "text": "where to eat?"}],
        client=client,
    )
    user_text = _user_message_text(client.calls[0])
    assert "KLCC" in user_text
    assert "lunch" in user_text
    assert "clouds" in user_text


def test_user_latest_text_present_in_user_message():
    client = _FakeClient()
    generate_free_recommendations(
        _context(),
        [_restaurant("a")],
        [{"role": "user", "text": "almost lunch time, hungry"}],
        client=client,
    )
    assert "almost lunch time, hungry" in _user_message_text(client.calls[0])


# ---- history capping -------------------------------------------------------

def test_session_history_capped_at_last_five_turns():
    # Build 8 turns; only last 5 should be sent (plus the system prompt = 6 total).
    history: list[dict[str, Any]] = []
    for i in range(7):
        role = "user" if i % 2 == 0 else "assistant"
        history.append({"role": role, "text": f"turn {i}"})
    history.append({"role": "user", "text": "latest"})  # 8 total

    client = _FakeClient()
    generate_free_recommendations(_context(), [_restaurant("a")], history, client=client)
    sent = client.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    assert len(sent) == 1 + 5  # system + last 5 turns


def test_history_role_alternation_preserved():
    history = [
        {"role": "user", "text": "u1"},
        {"role": "assistant", "text": "a1"},
        {"role": "user", "text": "u2"},
        {"role": "assistant", "text": "a2"},
        {"role": "user", "text": "latest"},
    ]
    client = _FakeClient()
    generate_free_recommendations(_context(), [_restaurant("a")], history, client=client)
    msgs = client.calls[0]["messages"]
    # msgs[0] is system; user turns then alternate u/a/u/a/u
    assert msgs[0]["role"] == "system"
    convo = msgs[1:]
    for i, m in enumerate(convo):
        assert m["role"] == ("user" if i % 2 == 0 else "assistant")


# ---- empty / invalid input -------------------------------------------------

def test_empty_history_raises():
    with pytest.raises(ValueError):
        generate_free_recommendations(
            _context(),
            [_restaurant("a")],
            [],
            client=_FakeClient(),
        )


def test_returns_text_from_response():
    client = _FakeClient(response_text="Try the nasi kandar — wok hei is unbeatable.")
    out = generate_free_recommendations(
        _context(),
        [_restaurant("a")],
        [{"role": "user", "text": "hi"}],
        client=client,
    )
    assert out == "Try the nasi kandar — wok hei is unbeatable."
