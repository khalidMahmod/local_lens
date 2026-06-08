"""Round-trip + validation tests for bot.models dataclasses."""

from __future__ import annotations

import pytest

from bot.models import (
    Context,
    DietaryPref,
    Location,
    Package,
    PackageStep,
    Restaurant,
    Session,
    Weather,
)


def _restaurant_dict() -> dict:
    return {
        "id": "lot10-hutong-hokkien-mee",
        "name": "Kim Lian Kee — Lot 10 Hutong",
        "lat": 3.1466,
        "lng": 101.7106,
        "area": "Bukit Bintang",
        "cuisine": "Chinese / Hokkien",
        "price_tier": "$",
        "meal_tags": ["lunch", "dinner"],
        "indoor": True,
        "vibe_tags": ["hawker", "iconic", "quick"],
        "halal_status": "non_halal",
        "insider_tip": "Order the Hokkien mee.",
        "google_maps_link": "https://maps.app.goo.gl/...",
    }


def _location_dict() -> dict:
    return {
        "id": "klcc-park",
        "name": "KLCC Park",
        "lat": 3.1565,
        "lng": 101.7124,
        "area": "KLCC",
        "type": "park",
        "tags": ["scenic", "free"],
        "best_time": ["morning", "evening"],
        "avg_time_minutes": 45,
    }


def _package_dict() -> dict:
    return {
        "id": "klcc-chill-2hr",
        "name": "2-Hour KLCC Chill Plan",
        "tier": "free",
        "price_rm": None,
        "duration_minutes": 120,
        "location_center": {"lat": 3.1578, "lng": 101.7117, "name": "KLCC"},
        "radius_km": 1.5,
        "intent_tags": ["chill", "explore"],
        "weather_tags": {
            "ideal": ["clear", "clouds"],
            "ok": ["drizzle"],
            "avoid": ["rain", "thunderstorm"],
        },
        "indoor_percentage": 40,
        "time_of_day": ["morning", "afternoon"],
        "steps": [
            {
                "order": 1,
                "place_name": "KLCC Park",
                "place_location": {"lat": 3.1565, "lng": 101.7124},
                "duration_minutes": 45,
                "description": "Walk through the park.",
                "insider_tip": "Enter from the Traders Hotel side.",
                "google_maps_link": "https://maps.app.goo.gl/...",
            }
        ],
        "why_it_works": "Minimal walking.",
        "upsells": ["coffee recommendation"],
        "audience_tags": ["family", "couples"],
    }


def test_restaurant_roundtrip() -> None:
    raw = _restaurant_dict()
    r = Restaurant.from_dict(raw)
    assert r.id == raw["id"]
    assert r.halal_status == "non_halal"
    assert r.to_dict() == raw


def test_restaurant_rejects_bad_halal_status() -> None:
    raw = _restaurant_dict()
    raw["halal_status"] = "definitely_halal"
    with pytest.raises(ValueError, match="halal_status"):
        Restaurant.from_dict(raw)


def test_restaurant_rejects_bad_meal_tag() -> None:
    raw = _restaurant_dict()
    raw["meal_tags"] = ["brunch"]
    with pytest.raises(ValueError, match="meal_tags"):
        Restaurant.from_dict(raw)


def test_location_roundtrip() -> None:
    raw = _location_dict()
    loc = Location.from_dict(raw)
    assert loc.name == "KLCC Park"
    assert loc.to_dict() == raw


def test_package_step_roundtrip() -> None:
    raw = _package_dict()["steps"][0]
    step = PackageStep.from_dict(raw)
    assert step.order == 1
    assert step.place_location == {"lat": 3.1565, "lng": 101.7124}
    assert step.to_dict() == raw


def test_package_roundtrip() -> None:
    raw = _package_dict()
    pkg = Package.from_dict(raw)
    assert pkg.tier == "free"
    assert pkg.price_rm is None
    assert pkg.weather_tags["avoid"] == ["rain", "thunderstorm"]
    assert len(pkg.steps) == 1

    serialized = pkg.to_dict()
    assert serialized["id"] == raw["id"]
    assert serialized["steps"][0]["place_name"] == "KLCC Park"


def test_package_rejects_bad_tier() -> None:
    raw = _package_dict()
    raw["tier"] = "vip"
    with pytest.raises(ValueError, match="tier"):
        Package.from_dict(raw)


def test_dietary_pref_defaults_and_roundtrip() -> None:
    pref = DietaryPref()
    assert pref.halal_only is False
    assert pref.source == "default"

    pref2 = DietaryPref.from_dict({"halal_only": True, "source": "asked"})
    assert pref2.halal_only is True
    assert pref2.to_dict() == {"halal_only": True, "source": "asked"}


def test_dietary_pref_rejects_bad_source() -> None:
    with pytest.raises(ValueError, match="dietary.source"):
        DietaryPref.from_dict({"halal_only": True, "source": "guessed"})


def test_session_roundtrip_with_defaults() -> None:
    s = Session(telegram_user_id="123")
    assert s.current_state == "new"
    assert s.dietary.halal_only is False

    d = s.to_dict()
    s2 = Session.from_dict(d)
    assert s2.telegram_user_id == "123"
    assert s2.current_state == "new"
    assert s2.location is None


def test_session_roundtrip_full() -> None:
    raw = {
        "telegram_user_id": "789",
        "current_state": "accepted",
        "location": {"lat": 3.15, "lng": 101.71},
        "dietary": {"halal_only": True, "source": "asked"},
        "active_package_id": "klcc-chill-2hr",
        "commitment_price": 15,
        "accepted_at": "2026-05-04T12:30:00+08:00",
        "follow_up_at": "2026-05-04T14:30:00+08:00",
        "follow_up_sent_at": None,
        "history": [{"role": "user", "text": "hi"}],
    }
    s = Session.from_dict(raw)
    assert s.commitment_price == 15
    assert s.dietary.halal_only is True
    assert s.history == [{"role": "user", "text": "hi"}]
    assert s.to_dict() == raw


def test_session_rejects_bad_state() -> None:
    with pytest.raises(ValueError, match="current_state"):
        Session(telegram_user_id="1", current_state="vibing")


def test_weather_roundtrip() -> None:
    raw = {"condition": "Clear", "description": "clear sky", "temp_c": 30.5}
    w = Weather.from_dict(raw)
    assert w.condition == "clear"
    assert w.temp_c == pytest.approx(30.5)
    assert w.to_dict() == {"condition": "clear", "description": "clear sky", "temp_c": 30.5}


def test_context_roundtrip_and_validation() -> None:
    raw = {
        "lat": 3.15,
        "lng": 101.71,
        "area_name": "KLCC",
        "weather": {"condition": "clouds", "description": "few clouds", "temp_c": 29.0},
        "time_of_day_window": "lunch",
    }
    ctx = Context.from_dict(raw)
    assert ctx.area_name == "KLCC"
    assert ctx.weather.condition == "clouds"
    assert ctx.to_dict() == raw

    with pytest.raises(ValueError, match="time_of_day_window"):
        Context.from_dict({**raw, "time_of_day_window": "brunch"})
