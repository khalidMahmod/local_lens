"""Verifies the bundled JSON data loads cleanly and meets fixture requirements."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.data_loader import (
    DATA_DIR,
    load_locations,
    load_packages,
    load_restaurants,
    load_session,
    save_session,
)
from bot.models import HALAL_STATUSES, MEAL_TAGS, PACKAGE_TIERS, Session


def test_load_restaurants_returns_models() -> None:
    restaurants = load_restaurants()
    assert len(restaurants) >= 5

    halal_tiers_seen = {r.halal_status for r in restaurants}
    assert halal_tiers_seen == HALAL_STATUSES, (
        f"Fixture must cover every halal tier; missing: {HALAL_STATUSES - halal_tiers_seen}"
    )

    meal_windows_covered = set().union(*(set(r.meal_tags) for r in restaurants))
    for required in {"breakfast", "lunch", "dinner"}:
        assert required in meal_windows_covered, f"No restaurant covers {required}"

    for r in restaurants:
        assert r.id and r.name
        assert -90 <= r.lat <= 90
        assert -180 <= r.lng <= 180
        assert set(r.meal_tags).issubset(MEAL_TAGS)
        assert r.halal_status in HALAL_STATUSES


def test_load_locations_returns_three_kl_locations() -> None:
    locations = load_locations()
    assert len(locations) >= 3
    names = {loc.name for loc in locations}
    assert any("KLCC" in n for n in names)
    assert any("Petaling" in n for n in names)
    assert any("Bukit Bintang" in n for n in names)
    for loc in locations:
        assert loc.avg_time_minutes > 0
        assert loc.tags


def test_load_packages_returns_at_least_one_free_package() -> None:
    packages = load_packages()
    assert len(packages) >= 1
    free_packages = [p for p in packages if p.tier == "free"]
    assert free_packages, "At least one free package fixture required"

    pkg = free_packages[0]
    assert pkg.tier in PACKAGE_TIERS
    assert pkg.steps, "Package must have at least one step"
    assert pkg.steps[0].order == 1
    assert pkg.location_center["name"]
    assert "ideal" in pkg.weather_tags


def test_load_restaurants_rejects_unknown_halal_status(tmp_path: Path) -> None:
    bad = tmp_path / "restaurants.json"
    bad.write_text(
        json.dumps(
            [
                {
                    "id": "x",
                    "name": "x",
                    "lat": 0,
                    "lng": 0,
                    "area": "x",
                    "cuisine": "x",
                    "price_tier": "$",
                    "meal_tags": ["lunch"],
                    "indoor": True,
                    "vibe_tags": [],
                    "halal_status": "kinda_halal",
                    "insider_tip": "x",
                    "google_maps_link": "x",
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="halal_status"):
        load_restaurants(bad)


def test_load_session_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_session("nope", sessions_dir=tmp_path) is None


def test_save_then_load_session_roundtrip(tmp_path: Path) -> None:
    session = Session(telegram_user_id="42", current_state="chatting")
    session.dietary.halal_only = True
    session.dietary.source = "asked"
    session.location = {"lat": 3.15, "lng": 101.71}

    saved_path = save_session(session, sessions_dir=tmp_path)
    assert saved_path.exists()

    loaded = load_session("42", sessions_dir=tmp_path)
    assert loaded is not None
    assert loaded.telegram_user_id == "42"
    assert loaded.current_state == "chatting"
    assert loaded.dietary.halal_only is True
    assert loaded.dietary.source == "asked"
    assert loaded.location == {"lat": 3.15, "lng": 101.71}


def test_data_dir_exists() -> None:
    assert DATA_DIR.is_dir()
    assert (DATA_DIR / "sessions").is_dir()
