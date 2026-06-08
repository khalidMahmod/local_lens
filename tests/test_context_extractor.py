"""Tests for bot.context_extractor — pure-logic time bucketing + nearest-area lookup."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from bot.context_extractor import (
    KL_TZ,
    build_context,
    nearest_area,
    time_of_day_window,
)
from bot.models import DietaryPref, Location, Session, Weather


def _kl(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KL_TZ)


# ---- time_of_day_window ----------------------------------------------------

@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (7, 0, "breakfast"),
        (9, 30, "breakfast"),
        (10, 30, "breakfast"),
        (10, 59, "breakfast"),
        (11, 0, "lunch"),
        (12, 0, "lunch"),
        (14, 29, "lunch"),
        (14, 59, "lunch"),
        (15, 0, "afternoon_snack"),
        (16, 30, "afternoon_snack"),
        (17, 30, "afternoon_snack"),
        (17, 59, "afternoon_snack"),
        (18, 0, "dinner"),
        (20, 0, "dinner"),
        (21, 59, "dinner"),
        (22, 0, "late_night"),
        (23, 30, "late_night"),
        (0, 30, "late_night"),   # past midnight
        (1, 59, "late_night"),
        (2, 0, "between"),       # post late_night
        (5, 0, "between"),
        (6, 59, "between"),
    ],
)
def test_time_of_day_window(hour, minute, expected):
    now = _kl(2026, 5, 6, hour, minute)
    assert time_of_day_window(now) == expected


def test_time_of_day_window_converts_from_other_timezone():
    # 03:00 UTC == 11:00 KL → "lunch" (seamless windows)
    utc = datetime(2026, 5, 6, 3, 0, tzinfo=timezone.utc)
    assert time_of_day_window(utc) == "lunch"
    # 04:00 UTC == 12:00 KL → "lunch"
    utc = datetime(2026, 5, 6, 4, 0, tzinfo=timezone.utc)
    assert time_of_day_window(utc) == "lunch"


def test_time_of_day_window_naive_datetime_raises():
    naive = datetime(2026, 5, 6, 12, 0)
    with pytest.raises(ValueError):
        time_of_day_window(naive)


# ---- nearest_area ----------------------------------------------------------

def _loc(id_: str, area: str, lat: float, lng: float) -> Location:
    return Location(
        id=id_,
        name=area,
        lat=lat,
        lng=lng,
        area=area,
        type="district",
        tags=[],
        best_time=[],
        avg_time_minutes=30,
    )


def test_nearest_area_returns_closest_within_3km():
    locs = [
        _loc("klcc", "KLCC", 3.1565, 101.7124),
        _loc("bb", "Bukit Bintang", 3.1466, 101.7106),
    ]
    # Right on top of Bukit Bintang
    assert nearest_area(3.1466, 101.7106, locs) == "Bukit Bintang"


def test_nearest_area_skips_distant_locations():
    # User far from KL (Penang-ish ~350km). Nothing within 3km → "KL".
    locs = [_loc("klcc", "KLCC", 3.1565, 101.7124)]
    assert nearest_area(5.4164, 100.3327, locs) == "KL"


def test_nearest_area_with_empty_locations_returns_kl():
    assert nearest_area(3.15, 101.71, []) == "KL"


def test_nearest_area_picks_closest_when_multiple_in_range():
    locs = [
        _loc("a", "Far", 3.1700, 101.7124),     # ~1.5km
        _loc("b", "Near", 3.1568, 101.7124),    # ~30m
    ]
    assert nearest_area(3.1565, 101.7124, locs) == "Near"


# ---- build_context ---------------------------------------------------------

def _session_with_location(lat: float = 3.1565, lng: float = 101.7124) -> Session:
    return Session(
        telegram_user_id="42",
        current_state="chatting",
        location={"lat": lat, "lng": lng},
        dietary=DietaryPref(halal_only=True, source="asked"),
    )


def _fake_weather(*_args, **_kwargs) -> Weather:
    return Weather(condition="clouds", description="scattered clouds", temp_c=30.0)


def test_build_context_returns_full_context():
    session = _session_with_location()
    locations = [_loc("klcc", "KLCC", 3.1565, 101.7124)]
    ctx = build_context(
        session,
        _kl(2026, 5, 6, 12, 30),
        locations=locations,
        weather_fn=_fake_weather,
    )
    assert ctx.lat == pytest.approx(3.1565)
    assert ctx.lng == pytest.approx(101.7124)
    assert ctx.area_name == "KLCC"
    assert ctx.time_of_day_window == "lunch"
    assert ctx.weather.condition == "clouds"


def test_build_context_passes_session_coords_to_weather():
    captured: dict = {}

    def weather_fn(lat, lng):
        captured["lat"] = lat
        captured["lng"] = lng
        return Weather(condition="clear", description="clear sky", temp_c=29.0)

    session = _session_with_location(3.14, 101.69)
    build_context(session, _kl(2026, 5, 6, 12, 0), locations=[], weather_fn=weather_fn)
    assert captured == {"lat": 3.14, "lng": 101.69}


def test_build_context_raises_when_session_has_no_location():
    session = Session(telegram_user_id="42", current_state="awaiting_location")
    with pytest.raises(ValueError):
        build_context(
            session, _kl(2026, 5, 6, 12, 0), locations=[], weather_fn=_fake_weather
        )
