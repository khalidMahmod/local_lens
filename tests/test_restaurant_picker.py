"""Tests for bot.restaurant_picker — pure logic; no data files or network."""

from __future__ import annotations

import pytest

from bot.models import Context, DietaryPref, Restaurant, Session, Weather
from bot.restaurant_picker import pick_restaurants

# ----- builders -------------------------------------------------------------

# Reference KLCC point used as the "user" location.
USER_LAT, USER_LNG = 3.1565, 101.7124


def _restaurant(
    id_: str,
    *,
    lat: float = USER_LAT,
    lng: float = USER_LNG,
    meal_tags: list[str] | None = None,
    indoor: bool = True,
    halal_status: str = "halal_certified",
) -> Restaurant:
    return Restaurant(
        id=id_,
        name=id_,
        lat=lat,
        lng=lng,
        area="KLCC",
        cuisine="Test",
        price_tier="$",
        meal_tags=list(meal_tags) if meal_tags is not None else ["lunch"],
        indoor=indoor,
        vibe_tags=[],
        halal_status=halal_status,
        insider_tip="",
        google_maps_link="",
    )


def _context(
    *,
    window: str = "lunch",
    condition: str = "clear",
    lat: float = USER_LAT,
    lng: float = USER_LNG,
) -> Context:
    return Context(
        lat=lat,
        lng=lng,
        area_name="KLCC",
        weather=Weather(condition=condition, description=condition, temp_c=30.0),
        time_of_day_window=window,
    )


def _session(*, halal_only: bool = False) -> Session:
    return Session(
        telegram_user_id="42",
        current_state="chatting",
        location={"lat": USER_LAT, "lng": USER_LNG},
        dietary=DietaryPref(halal_only=halal_only, source="asked"),
    )


# ----- meal-window filter ---------------------------------------------------

def test_lunch_window_returns_lunch_tagged_only():
    restaurants = [
        _restaurant("lunch_a", meal_tags=["lunch"]),
        _restaurant("breakfast_only", meal_tags=["breakfast"]),
        _restaurant("dinner_only", meal_tags=["dinner"]),
    ]
    out = pick_restaurants(_context(window="lunch"), _session(), restaurants=restaurants)
    ids = [r.id for r in out]
    assert "lunch_a" in ids
    assert "breakfast_only" not in ids
    assert "dinner_only" not in ids


def test_between_window_returns_empty():
    restaurants = [_restaurant("any", meal_tags=["lunch"])]
    out = pick_restaurants(_context(window="between"), _session(), restaurants=restaurants)
    assert out == []


# ----- halal preference -----------------------------------------------------

def test_halal_only_excludes_non_halal_and_unknown():
    restaurants = [
        _restaurant("certified", halal_status="halal_certified"),
        _restaurant("friendly", halal_status="muslim_friendly"),
        _restaurant("non_halal", halal_status="non_halal"),
        _restaurant("unknown", halal_status="unknown"),
    ]
    out = pick_restaurants(
        _context(), _session(halal_only=True), restaurants=restaurants, max_results=10
    )
    statuses = {r.halal_status for r in out}
    assert statuses.issubset({"halal_certified", "muslim_friendly"})
    assert "non_halal" not in statuses
    assert "unknown" not in statuses


def test_halal_only_prefers_certified_over_friendly():
    restaurants = [
        # Friendly is closer; certified is slightly farther but should still rank first.
        _restaurant("friendly_close", lat=USER_LAT, lng=USER_LNG, halal_status="muslim_friendly"),
        _restaurant("certified_farther", lat=USER_LAT + 0.005, lng=USER_LNG, halal_status="halal_certified"),
    ]
    out = pick_restaurants(
        _context(), _session(halal_only=True), restaurants=restaurants, max_results=2
    )
    assert out[0].id == "certified_farther"


def test_no_halal_pref_includes_all_statuses():
    restaurants = [
        _restaurant("certified", halal_status="halal_certified"),
        _restaurant("non_halal", halal_status="non_halal", lat=USER_LAT + 0.0001),
        _restaurant("unknown", halal_status="unknown", lat=USER_LAT + 0.0002),
    ]
    out = pick_restaurants(
        _context(), _session(halal_only=False), restaurants=restaurants, max_results=10
    )
    statuses = {r.halal_status for r in out}
    assert {"halal_certified", "non_halal", "unknown"}.issubset(statuses)


# ----- proximity ------------------------------------------------------------

def test_outside_radius_is_excluded():
    # ~5km north of user
    far = _restaurant("far", lat=USER_LAT + 0.05, lng=USER_LNG)
    near = _restaurant("near", lat=USER_LAT, lng=USER_LNG)
    out = pick_restaurants(_context(), _session(), restaurants=[far, near])
    ids = [r.id for r in out]
    assert "near" in ids
    assert "far" not in ids


# ----- weather --------------------------------------------------------------

def test_rain_prefers_indoor_over_outdoor():
    indoor = _restaurant("indoor_far", lat=USER_LAT + 0.005, indoor=True)
    outdoor = _restaurant("outdoor_close", lat=USER_LAT, indoor=False)
    out = pick_restaurants(
        _context(condition="rain"),
        _session(),
        restaurants=[outdoor, indoor],
        max_results=2,
    )
    assert out[0].id == "indoor_far"


def test_clear_weather_does_not_force_indoor():
    indoor_far = _restaurant("indoor_far", lat=USER_LAT + 0.005, indoor=True)
    outdoor_close = _restaurant("outdoor_close", lat=USER_LAT, indoor=False)
    out = pick_restaurants(
        _context(condition="clear"),
        _session(),
        restaurants=[indoor_far, outdoor_close],
        max_results=2,
    )
    assert out[0].id == "outdoor_close"


# ----- exclusion + capping --------------------------------------------------

def test_exclude_meal_window_matching_current_returns_empty():
    restaurants = [_restaurant("lunch_a", meal_tags=["lunch"])]
    out = pick_restaurants(
        _context(window="lunch"),
        _session(),
        restaurants=restaurants,
        exclude_meal_window="lunch",
    )
    assert out == []


def test_exclude_meal_window_for_other_window_does_not_suppress():
    restaurants = [_restaurant("lunch_a", meal_tags=["lunch"])]
    out = pick_restaurants(
        _context(window="lunch"),
        _session(),
        restaurants=restaurants,
        exclude_meal_window="dinner",
    )
    assert [r.id for r in out] == ["lunch_a"]


def test_max_results_caps_at_two_by_default():
    restaurants = [
        _restaurant(f"r{i}", lat=USER_LAT + i * 0.0005, meal_tags=["lunch"])
        for i in range(5)
    ]
    out = pick_restaurants(_context(window="lunch"), _session(), restaurants=restaurants)
    assert len(out) == 2
