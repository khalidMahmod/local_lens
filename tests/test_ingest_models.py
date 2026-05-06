"""Tests for ingest.models — Candidate + RawItem dataclasses."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.models import Candidate, RawItem


# ---- Candidate construction + validation ----------------------------------

def test_candidate_minimal_construction():
    c = Candidate(id="ig_X")
    assert c.id == "ig_X"
    assert c.status == "pending"
    assert c.source_platform == "instagram"
    assert c.stall_name is None
    assert c.lat is None


def test_candidate_rejects_invalid_status():
    with pytest.raises(ValueError, match="status"):
        Candidate(id="ig_X", status="bogus")


def test_candidate_rejects_invalid_halal_signals():
    with pytest.raises(ValueError, match="halal_signals"):
        Candidate(id="ig_X", halal_signals="kinda_halal")


def test_candidate_accepts_none_halal_signals():
    c = Candidate(id="ig_X", halal_signals=None)
    assert c.halal_signals is None


def test_candidate_rejects_invalid_stall_name_confidence():
    with pytest.raises(ValueError, match="stall_name_confidence"):
        Candidate(id="ig_X", stall_name_confidence="kinda_sure")


def test_candidate_accepts_all_valid_status_values():
    for status in ("pending", "live", "rejected"):
        Candidate(id="ig_X", status=status)


def test_candidate_accepts_all_valid_halal_signals():
    for signal in ("no_pork_visible", "pork_visible", "unclear"):
        Candidate(id="ig_X", halal_signals=signal)


# ---- Candidate round-trip --------------------------------------------------

def _full_candidate_dict() -> dict:
    return {
        "id": "ig_DCxAbc123",
        "status": "live",
        "source_url": "https://www.instagram.com/reel/DCxAbc123/",
        "source_platform": "instagram",
        "scraped_at": "2026-05-06T14:30:00+08:00",
        "thumbnail_path": "data/source_archive/DCxAbc123/cover.jpg",
        "stall_name": "Restoran Win Heng Seng",
        "stall_name_confidence": "high",
        "dish_featured": "Char kuey teow",
        "viral_hook": "Wok hei shot at 0:08",
        "claimed_must_order": "Char kuey teow with extra duck egg",
        "halal_signals": "no_pork_visible",
        "operating_hours_mentioned": "Closes 1pm",
        "google_maps_search_query": "Restoran Win Heng Seng Jalan Imbi",
        "candidate_quality_score": 8,
        "extractor_notes": "Caption inconsistent on stall name",
        "lat": 3.1466,
        "lng": 101.7106,
        "area": "Bukit Bintang",
        "cuisine": "Chinese / Hokkien",
        "price_tier": "$",
        "meal_tags": ["lunch", "dinner"],
        "indoor": True,
        "vibe_tags": ["hawker", "iconic"],
        "halal_status": "non_halal",
        "google_maps_link": "https://maps.app.goo.gl/x",
        "insider_tip": "Order the Hokkien mee — the original recipe",
    }


def test_candidate_round_trip_full():
    src = _full_candidate_dict()
    c = Candidate.from_dict(src)
    out = c.to_dict()
    assert out == src


def test_candidate_round_trip_minimal_preserves_nulls():
    src = {"id": "ig_X"}
    c = Candidate.from_dict(src)
    out = c.to_dict()
    # All extraction + manual-fill fields stay None across round-trip
    for key in (
        "stall_name",
        "stall_name_confidence",
        "halal_signals",
        "lat",
        "lng",
        "meal_tags",
        "indoor",
        "vibe_tags",
        "halal_status",
        "insider_tip",
    ):
        assert out[key] is None, f"field {key} should be None"


def test_candidate_from_dict_ignores_unknown_keys():
    src = {"id": "ig_X", "totally_made_up_key": 42}
    c = Candidate.from_dict(src)
    assert c.id == "ig_X"


def test_candidate_meal_tags_round_trip_preserves_list():
    src = {"id": "ig_X", "meal_tags": ["lunch", "dinner"]}
    c = Candidate.from_dict(src)
    assert c.meal_tags == ["lunch", "dinner"]
    # Mutating the round-tripped list shouldn't affect the original.
    c.meal_tags.append("breakfast")
    assert src["meal_tags"] == ["lunch", "dinner"]


def test_candidate_lat_coerced_to_float():
    src = {"id": "ig_X", "lat": "3.1466", "lng": 101.7106}
    c = Candidate.from_dict(src)
    assert c.lat == pytest.approx(3.1466)
    assert isinstance(c.lat, float)


# ---- RawItem -------------------------------------------------------------

def test_raw_item_construction():
    item = RawItem(
        reel_id="DCxAbc123",
        candidate_id="ig_DCxAbc123",
        source_url="https://www.instagram.com/reel/DCxAbc123/",
        thumbnail_path=Path("data/source_archive/DCxAbc123/cover.jpg"),
        caption="char kuey teow at jalan imbi",
        play_count=12000,
        like_count=400,
        posted_at="2026-05-01T18:00:00+08:00",
        scraped_at="2026-05-06T14:30:00+08:00",
    )
    assert item.reel_id == "DCxAbc123"
    assert item.candidate_id == "ig_DCxAbc123"
    assert item.thumbnail_path == Path("data/source_archive/DCxAbc123/cover.jpg")


def test_raw_item_is_frozen():
    item = RawItem(
        reel_id="DCx",
        candidate_id="ig_DCx",
        source_url="",
        thumbnail_path=Path("/tmp/x.jpg"),
        caption="",
        play_count=None,
        like_count=None,
        posted_at=None,
        scraped_at="2026-05-06T14:30:00+08:00",
    )
    with pytest.raises(Exception):
        item.reel_id = "ABC"  # type: ignore[misc]


def test_raw_item_accepts_none_for_optional_fields():
    item = RawItem(
        reel_id="X",
        candidate_id="ig_X",
        source_url="",
        thumbnail_path=Path("/tmp/x.jpg"),
        caption="",
        play_count=None,
        like_count=None,
        posted_at=None,
        scraped_at="2026-05-06T14:30:00+08:00",
    )
    assert item.play_count is None
    assert item.like_count is None
    assert item.posted_at is None
