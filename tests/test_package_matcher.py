"""Tests for bot.package_matcher — pure logic; no data files."""

from __future__ import annotations

import pytest

from bot.models import Context, Package, PackageStep, Weather
from bot.package_matcher import (
    DEFAULT_THRESHOLD,
    ScoredPackage,
    match_packages,
)


# Anchor used as the "user" location.
USER_LAT, USER_LNG = 3.1565, 101.7124


def _step(i: int = 1) -> PackageStep:
    return PackageStep(
        order=i,
        place_name=f"Step {i}",
        place_location={"lat": USER_LAT, "lng": USER_LNG},
        duration_minutes=30,
        description="desc",
        insider_tip="tip",
        google_maps_link="https://maps.app.goo.gl/x",
    )


def _package(
    id_: str = "pkg-a",
    *,
    tier: str = "free",
    center_lat: float = USER_LAT,
    center_lng: float = USER_LNG,
    radius_km: float = 1.5,
    weather_ideal: list[str] | None = None,
    weather_ok: list[str] | None = None,
    weather_avoid: list[str] | None = None,
    time_of_day: list[str] | None = None,
    intent_tags: list[str] | None = None,
) -> Package:
    return Package(
        id=id_,
        name=id_,
        tier=tier,
        price_rm=None if tier == "free" else 15,
        duration_minutes=120,
        location_center={"lat": center_lat, "lng": center_lng, "name": id_},
        radius_km=radius_km,
        intent_tags=intent_tags or ["chill"],
        weather_tags={
            "ideal": weather_ideal or ["clear", "clouds"],
            "ok": weather_ok or ["drizzle"],
            "avoid": weather_avoid or ["rain", "thunderstorm"],
        },
        indoor_percentage=40,
        time_of_day=time_of_day or ["morning", "afternoon"],
        steps=[_step(1), _step(2)],
        why_it_works="works",
        upsells=[],
    )


def _context(
    *,
    lat: float = USER_LAT,
    lng: float = USER_LNG,
    condition: str = "clear",
    window: str = "lunch",
) -> Context:
    return Context(
        lat=lat,
        lng=lng,
        area_name="KLCC",
        weather=Weather(condition=condition, description=condition, temp_c=30.0),
        time_of_day_window=window,
    )


# ---- shape -----------------------------------------------------------------

def test_returns_scored_packages_with_components():
    out = match_packages(_context(), packages=[_package()])
    assert len(out) == 1
    sp = out[0]
    assert isinstance(sp, ScoredPackage)
    assert sp.package.id == "pkg-a"
    assert 0.0 <= sp.score <= 1.0
    # components dict surfaces the sub-scores so future code (and tests) can introspect
    for key in ("proximity", "weather", "time_of_day"):
        assert key in sp.components


def test_empty_packages_returns_empty():
    assert match_packages(_context(), packages=[]) == []


# ---- proximity -------------------------------------------------------------

def test_user_at_center_gives_full_proximity_score():
    pkg = _package(center_lat=USER_LAT, center_lng=USER_LNG, radius_km=1.5)
    [out] = match_packages(_context(), packages=[pkg], threshold=0.0)
    assert out.components["proximity"] == pytest.approx(1.0)


def test_user_outside_double_radius_gives_zero_proximity():
    # Place center ~10km away from user.
    pkg = _package(center_lat=USER_LAT + 0.1, center_lng=USER_LNG, radius_km=1.5)
    [out] = match_packages(_context(), packages=[pkg], threshold=0.0)
    assert out.components["proximity"] == pytest.approx(0.0)


def test_proximity_decays_between_radius_and_double_radius():
    # ~1.7km out — between r (1.5km) and 2r (3km) → partial credit.
    pkg = _package(center_lat=USER_LAT + 0.0153, center_lng=USER_LNG, radius_km=1.5)
    [out] = match_packages(_context(), packages=[pkg], threshold=0.0)
    assert 0.0 < out.components["proximity"] < 1.0


# ---- weather ---------------------------------------------------------------

def test_weather_avoid_disqualifies_package():
    pkg = _package(weather_avoid=["rain"])
    out = match_packages(
        _context(condition="rain"), packages=[pkg], threshold=0.0
    )
    # Either filtered out, or returned with 0 score
    if out:
        assert out[0].score == pytest.approx(0.0)
        assert out[0].components["weather"] == pytest.approx(0.0)


def test_weather_ideal_outranks_ok():
    ideal_pkg = _package("ideal", weather_ideal=["clear"], weather_ok=["drizzle"])
    ok_pkg = _package("ok", weather_ideal=["clear"], weather_ok=["drizzle"])

    ideal_out = match_packages(
        _context(condition="clear"), packages=[ideal_pkg], threshold=0.0
    )[0]
    ok_out = match_packages(
        _context(condition="drizzle"), packages=[ok_pkg], threshold=0.0
    )[0]

    assert ideal_out.components["weather"] > ok_out.components["weather"]


def test_weather_unknown_condition_gives_neutral_score():
    pkg = _package(
        weather_ideal=["clear"], weather_ok=["drizzle"], weather_avoid=["rain"]
    )
    [out] = match_packages(
        _context(condition="snow"),  # not in any list
        packages=[pkg],
        threshold=0.0,
    )
    w = out.components["weather"]
    assert 0.0 < w < 1.0


# ---- time of day ----------------------------------------------------------

def test_time_of_day_match_boosts_score():
    morning_pkg = _package(time_of_day=["morning"])
    evening_pkg = _package(time_of_day=["evening"])

    # User at breakfast (morning bucket) → morning_pkg should score higher.
    morning_out = match_packages(
        _context(window="breakfast"), packages=[morning_pkg], threshold=0.0
    )[0]
    evening_out = match_packages(
        _context(window="breakfast"), packages=[evening_pkg], threshold=0.0
    )[0]

    assert morning_out.components["time_of_day"] > evening_out.components["time_of_day"]


# ---- threshold + ranking ---------------------------------------------------

def test_threshold_filters_low_scoring_packages():
    far_pkg = _package(
        "far",
        center_lat=USER_LAT + 0.1,  # ~10km away
        weather_ideal=["clear"],
    )
    out = match_packages(
        _context(condition="clear"),
        packages=[far_pkg],
        threshold=0.5,
    )
    assert out == []


def test_default_threshold_constant_exposed():
    # Sanity: default threshold is in the [0, 1] band the scoring uses.
    assert 0.0 < DEFAULT_THRESHOLD < 1.0


def test_results_sorted_by_score_descending():
    near = _package("near", center_lat=USER_LAT, center_lng=USER_LNG, radius_km=1.5)
    far = _package(
        "far",
        center_lat=USER_LAT + 0.005,
        center_lng=USER_LNG,
        radius_km=1.5,
    )
    out = match_packages(_context(), packages=[far, near], threshold=0.0)
    assert [p.package.id for p in out] == ["near", "far"]


def test_premium_packages_included_in_results():
    """Phase 7 returns all matches; the handler decides free vs premium routing."""
    free = _package("free-pkg", tier="free")
    premium = _package("premium-pkg", tier="premium")
    out = match_packages(_context(), packages=[free, premium], threshold=0.0)
    ids = {p.package.id for p in out}
    assert "free-pkg" in ids
    assert "premium-pkg" in ids
