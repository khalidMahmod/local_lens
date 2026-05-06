"""Pure-logic tests for the onboarding state machine in bot.conversation.

No Telegram objects are used here — handlers are exercised manually per the plan.
"""

from __future__ import annotations

import pytest

from bot.conversation import (
    InvalidTransition,
    accept_premium_package,
    offer_premium_package,
    set_dietary_preference,
    transition,
)
from bot.models import DietaryPref, Session


def _session(state: str = "new", **kwargs) -> Session:
    return Session(telegram_user_id="42", current_state=state, **kwargs)


# ---- start ---------------------------------------------------------------

def test_start_from_new_moves_to_awaiting_location():
    s = _session(state="new")
    out = transition(s, {"type": "start"})
    assert out.current_state == "awaiting_location"


def test_start_does_not_mutate_input():
    s = _session(state="new")
    transition(s, {"type": "start"})
    assert s.current_state == "new"


def test_start_from_chatting_restarts_onboarding():
    s = _session(state="chatting")
    out = transition(s, {"type": "start"})
    assert out.current_state == "awaiting_location"


def test_start_preserves_dietary_when_previously_asked():
    s = _session(
        state="chatting",
        dietary=DietaryPref(halal_only=True, source="asked"),
    )
    out = transition(s, {"type": "start"})
    assert out.dietary.halal_only is True
    assert out.dietary.source == "asked"


# ---- location ------------------------------------------------------------

def test_location_in_awaiting_location_advances_to_awaiting_dietary():
    s = _session(state="awaiting_location")
    out = transition(s, {"type": "location", "lat": 3.1578, "lng": 101.7117})
    assert out.current_state == "awaiting_dietary"
    assert out.location == {"lat": 3.1578, "lng": 101.7117}


def test_location_in_chatting_updates_coords_without_state_change():
    s = _session(state="chatting", location={"lat": 1.0, "lng": 1.0})
    out = transition(s, {"type": "location", "lat": 2.5, "lng": 3.5})
    assert out.current_state == "chatting"
    assert out.location == {"lat": 2.5, "lng": 3.5}


def test_location_in_new_raises():
    s = _session(state="new")
    with pytest.raises(InvalidTransition):
        transition(s, {"type": "location", "lat": 1.0, "lng": 2.0})


# ---- dietary -------------------------------------------------------------

def test_dietary_in_awaiting_dietary_advances_to_awaiting_intent():
    s = _session(state="awaiting_dietary")
    out = transition(s, {"type": "dietary", "halal_only": True})
    assert out.current_state == "awaiting_intent"
    assert out.dietary.halal_only is True
    assert out.dietary.source == "asked"


def test_dietary_no_pref_in_awaiting_dietary():
    s = _session(state="awaiting_dietary")
    out = transition(s, {"type": "dietary", "halal_only": False})
    assert out.current_state == "awaiting_intent"
    assert out.dietary.halal_only is False
    assert out.dietary.source == "asked"


def test_dietary_in_wrong_state_raises():
    s = _session(state="chatting")
    with pytest.raises(InvalidTransition):
        transition(s, {"type": "dietary", "halal_only": False})


# ---- intent --------------------------------------------------------------

def test_intent_in_awaiting_intent_advances_to_chatting():
    s = _session(state="awaiting_intent")
    out = transition(s, {"type": "intent", "intent": "food"})
    assert out.current_state == "chatting"


def test_intent_in_wrong_state_raises():
    s = _session(state="awaiting_dietary")
    with pytest.raises(InvalidTransition):
        transition(s, {"type": "intent", "intent": "chill"})


# ---- unknown event -------------------------------------------------------

def test_unknown_event_type_raises():
    s = _session()
    with pytest.raises(ValueError):
        transition(s, {"type": "bogus"})


# ---- /diet helper --------------------------------------------------------

def test_set_dietary_preference_updates_without_state_change():
    s = _session(state="chatting", dietary=DietaryPref(halal_only=False, source="default"))
    out = set_dietary_preference(s, halal_only=True)
    assert out.current_state == "chatting"
    assert out.dietary.halal_only is True
    assert out.dietary.source == "asked"


def test_set_dietary_preference_does_not_mutate_input():
    s = _session(state="chatting", dietary=DietaryPref(halal_only=False, source="default"))
    set_dietary_preference(s, halal_only=True)
    assert s.dietary.halal_only is False
    assert s.dietary.source == "default"


# ---- premium offer / accept ---------------------------------------------

def test_offer_premium_from_chatting_advances_to_package_offered():
    s = _session(state="chatting")
    out = offer_premium_package(s, "pkg-123")
    assert out.current_state == "package_offered"
    assert out.active_package_id == "pkg-123"


def test_offer_premium_overwrites_active_package_when_re_teasing():
    s = _session(state="package_offered", active_package_id="old-pkg")
    out = offer_premium_package(s, "new-pkg")
    assert out.current_state == "package_offered"
    assert out.active_package_id == "new-pkg"


def test_offer_premium_in_wrong_state_raises():
    s = _session(state="awaiting_intent")
    with pytest.raises(InvalidTransition):
        offer_premium_package(s, "pkg-123")


def test_accept_premium_records_commitment_and_transitions():
    s = _session(state="package_offered", active_package_id="pkg-123")
    out = accept_premium_package(s, "pkg-123", price_rm=15, accepted_at_iso="2026-05-06T10:00:00+00:00")
    assert out.current_state == "accepted"
    assert out.commitment_price == 15
    assert out.accepted_at == "2026-05-06T10:00:00+00:00"
    assert out.active_package_id == "pkg-123"


def test_accept_premium_in_wrong_state_raises():
    s = _session(state="chatting", active_package_id="pkg-123")
    with pytest.raises(InvalidTransition):
        accept_premium_package(s, "pkg-123", price_rm=15, accepted_at_iso="2026-05-06T10:00:00+00:00")


def test_accept_premium_id_mismatch_raises():
    s = _session(state="package_offered", active_package_id="pkg-123")
    with pytest.raises(InvalidTransition):
        accept_premium_package(s, "other-pkg", price_rm=15, accepted_at_iso="2026-05-06T10:00:00+00:00")


def test_offer_premium_does_not_mutate_input():
    s = _session(state="chatting")
    offer_premium_package(s, "pkg-123")
    assert s.current_state == "chatting"
    assert s.active_package_id is None


# ---- full happy path -----------------------------------------------------

def test_full_onboarding_flow():
    s = _session(state="new")
    s = transition(s, {"type": "start"})
    s = transition(s, {"type": "location", "lat": 3.15, "lng": 101.71})
    s = transition(s, {"type": "dietary", "halal_only": True})
    s = transition(s, {"type": "intent", "intent": "food"})
    assert s.current_state == "chatting"
    assert s.location == {"lat": 3.15, "lng": 101.71}
    assert s.dietary.halal_only is True
    assert s.dietary.source == "asked"
