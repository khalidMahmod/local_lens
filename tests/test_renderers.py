"""Tests for bot.renderers — Phase 8 premium tease + full plan.

Synthetic Packages and Restaurants only; no fixtures or data files.
"""

from __future__ import annotations

import pytest

from bot.models import Package, PackageStep, Restaurant
from bot.renderers import (
    render_free_package,
    render_meal_addon,
    render_premium_full,
    render_premium_tease,
)


def _step(order: int, place_name: str, description: str) -> PackageStep:
    return PackageStep(
        order=order,
        place_name=place_name,
        place_location={"lat": 3.15, "lng": 101.71},
        duration_minutes=45,
        description=description,
        insider_tip=f"Tip for {place_name}",
        google_maps_link=f"https://maps.app.goo.gl/{order}",
    )


def _package(tier: str = "premium", price_rm: int | None = 15) -> Package:
    return Package(
        id="test-premium",
        name="3-Hour Hidden Gems",
        tier=tier,
        price_rm=price_rm,
        duration_minutes=180,
        location_center={"lat": 3.15, "lng": 101.71, "name": "Center"},
        radius_km=1.5,
        intent_tags=["explore"],
        weather_tags={"ideal": ["clear"], "ok": [], "avoid": ["thunderstorm"]},
        indoor_percentage=60,
        time_of_day=["afternoon", "evening"],
        steps=[
            _step(1, "Lot 10 Hutong", "Underground heritage hawker hall"),
            _step(2, "Concubine Lane", "Hidden alley with old-school dessert stalls"),
            _step(3, "Heli Lounge Bar", "Rooftop helipad-turned-bar with skyline views"),
        ],
        why_it_works="Three locals-only spots in walking distance",
        upsells=[],
    )


def _restaurant(id_: str = "r1") -> Restaurant:
    return Restaurant(
        id=id_,
        name="Sample Restaurant",
        lat=3.15,
        lng=101.71,
        area="KLCC",
        cuisine="Malay",
        price_tier="$",
        meal_tags=["lunch", "dinner"],
        indoor=True,
        vibe_tags=["hawker"],
        halal_status="halal_certified",
        insider_tip="Order the nasi lemak",
        google_maps_link="https://maps.app.goo.gl/r1",
    )


# ---- render_premium_tease --------------------------------------------------

def test_tease_excludes_every_place_name():
    pkg = _package()
    tease = render_premium_tease(pkg)
    for step in pkg.steps:
        assert step.place_name not in tease, (
            f"Tease leaked place_name {step.place_name!r}: {tease!r}"
        )


def test_tease_excludes_insider_tips_and_maps_links():
    pkg = _package()
    tease = render_premium_tease(pkg)
    for step in pkg.steps:
        assert step.insider_tip not in tease
        assert step.google_maps_link not in tease


def test_tease_includes_descriptions_and_durations():
    pkg = _package()
    tease = render_premium_tease(pkg)
    for step in pkg.steps:
        assert step.description in tease
        assert str(step.duration_minutes) in tease


def test_tease_includes_price_and_post_pay_framing():
    pkg = _package(price_rm=15)
    tease = render_premium_tease(pkg)
    assert "RM15" in tease
    assert "pay after" in tease
    assert "Want the full plan?" in tease


def test_tease_includes_package_name_and_why():
    pkg = _package()
    tease = render_premium_tease(pkg)
    assert pkg.name in tease
    assert pkg.why_it_works in tease


def test_tease_handles_missing_price_gracefully():
    pkg = _package(price_rm=None)
    tease = render_premium_tease(pkg)
    assert "RM" not in tease
    assert "Want the full plan?" in tease


# ---- render_premium_full ---------------------------------------------------

def test_full_includes_every_place_name():
    pkg = _package()
    full = render_premium_full(pkg)
    for step in pkg.steps:
        assert step.place_name in full, (
            f"Full plan missing place_name {step.place_name!r}"
        )


def test_full_includes_insider_tips_and_maps_links():
    pkg = _package()
    full = render_premium_full(pkg)
    for step in pkg.steps:
        assert step.insider_tip in full
        assert step.google_maps_link in full


def test_full_appends_follow_up_promise():
    pkg = _package()
    full = render_premium_full(pkg)
    assert "check in" in full.lower()


def test_full_appends_meal_addon_when_picks_and_window_provided():
    pkg = _package()
    picks = [_restaurant("r1")]
    full = render_premium_full(pkg, picks=picks, window="lunch")
    assert "Sample Restaurant" in full
    assert "Hungry?" in full


def test_full_skips_meal_addon_when_window_is_between():
    pkg = _package()
    picks = [_restaurant("r1")]
    full = render_premium_full(pkg, picks=picks, window="between")
    assert "Sample Restaurant" not in full


def test_full_skips_meal_addon_when_picks_empty():
    pkg = _package()
    full = render_premium_full(pkg, picks=[], window="lunch")
    assert "Hungry?" not in full


# ---- render_free_package (sanity, not new) --------------------------------

def test_free_package_includes_place_names():
    pkg = _package(tier="free", price_rm=None)
    out = render_free_package(pkg)
    for step in pkg.steps:
        assert step.place_name in out


# ---- render_meal_addon (sanity, not new) ----------------------------------

@pytest.mark.parametrize("window,opener", [
    ("breakfast", "Breakfast nearby?"),
    ("lunch", "Hungry?"),
    ("afternoon_snack", "Snack time?"),
    ("dinner", "Dinner nearby?"),
    ("late_night", "Late-night bite?"),
])
def test_meal_addon_opener_per_window(window: str, opener: str):
    out = render_meal_addon([_restaurant()], window)
    assert opener in out


def test_meal_addon_empty_for_between_window():
    assert render_meal_addon([_restaurant()], "between") == ""
