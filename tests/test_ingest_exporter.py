"""Tests for ingest.exporter — Candidate → Restaurant merge.

All test cases use tmp paths; nothing in the live data/ directory is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.models import Restaurant
from ingest import candidates_store, exporter
from ingest.models import Candidate


# ---- helpers --------------------------------------------------------------

def _full_live_candidate(id_: str = "ig_X", **overrides) -> Candidate:
    """A Candidate whose manual block satisfies every required field."""
    base = dict(
        id=id_,
        status="live",
        source_url=f"https://www.instagram.com/reel/{id_.removeprefix('ig_')}/",
        source_platform="instagram",
        scraped_at="2026-05-06T14:30:00+08:00",
        thumbnail_path=f"data/source_archive/{id_.removeprefix('ig_')}/cover.jpg",
        stall_name="Test Stall",
        stall_name_confidence="high",
        dish_featured="char kuey teow",
        viral_hook="wok hei shot",
        halal_signals="no_pork_visible",
        candidate_quality_score=8,
        # manual block — all required fields populated
        lat=3.1466,
        lng=101.7106,
        area="Bukit Bintang",
        cuisine="Chinese / Hokkien",
        price_tier="$",
        meal_tags=["lunch", "dinner"],
        indoor=True,
        vibe_tags=["hawker", "iconic"],
        halal_status="non_halal",
        google_maps_link="https://maps.app.goo.gl/x",
        insider_tip="Order the Hokkien mee — original recipe",
    )
    base.update(overrides)
    return Candidate(**base)


def _curated_row(id_: str = "lot10-hutong") -> dict:
    """A hand-curated restaurants.json row (id NOT prefixed `ig_`)."""
    return {
        "id": id_,
        "name": "Hand-Curated Spot",
        "lat": 3.1466,
        "lng": 101.7106,
        "area": "Bukit Bintang",
        "cuisine": "Chinese",
        "price_tier": "$",
        "meal_tags": ["lunch"],
        "indoor": True,
        "vibe_tags": ["iconic"],
        "halal_status": "non_halal",
        "insider_tip": "Hand-written tip",
        "google_maps_link": "https://maps.app.goo.gl/curated",
    }


def _read_restaurants(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---- empty / no-op cases --------------------------------------------------

def test_empty_candidates_with_no_existing_file_writes_empty_list(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result == exporter.ExportResult(0, 0, 0, [])
    assert _read_restaurants(restaurants) == []


def test_empty_candidates_preserves_existing_curated_rows(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    restaurants.write_text(json.dumps([_curated_row("a"), _curated_row("b")]))

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.exported == 0
    rows = _read_restaurants(restaurants)
    assert [r["id"] for r in rows] == ["a", "b"]


# ---- adding new ig_ rows --------------------------------------------------

def test_one_valid_live_candidate_appears_in_restaurants_json(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X"), path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.exported == 1
    assert result.total_live == 1
    rows = _read_restaurants(restaurants)
    assert [r["id"] for r in rows] == ["ig_X"]
    row = rows[0]
    assert row["name"] == "Test Stall"
    assert row["lat"] == 3.1466
    assert row["meal_tags"] == ["lunch", "dinner"]


def test_exported_row_satisfies_bot_restaurant_schema(tmp_path: Path):
    """The bot reads restaurants.json via Restaurant.from_dict — exported rows
    must round-trip cleanly through that constructor."""
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X"), path=candidates)

    exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    [row] = _read_restaurants(restaurants)
    restaurant = Restaurant.from_dict(row)
    assert restaurant.id == "ig_X"
    assert restaurant.name == "Test Stall"


# ---- replacing existing ig_ rows ------------------------------------------

def test_existing_ig_row_replaced_by_new_export(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    # Pre-existing ig_X row in restaurants.json (an earlier export)
    old_row = _curated_row("ig_X")
    old_row["name"] = "Old Name"
    restaurants.write_text(json.dumps([old_row]))
    # New live candidate with the same id and a new name
    candidates_store.append(
        _full_live_candidate("ig_X", stall_name="New Name"), path=candidates
    )

    exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    [row] = _read_restaurants(restaurants)
    assert row["id"] == "ig_X"
    assert row["name"] == "New Name"


def test_curated_rows_preserved_alongside_ig_rows(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    restaurants.write_text(
        json.dumps([_curated_row("lot10-hutong-hokkien-mee"), _curated_row("kim-lian-kee")])
    )
    candidates_store.append(_full_live_candidate("ig_NEW"), path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.exported == 1
    rows = _read_restaurants(restaurants)
    ids = [r["id"] for r in rows]
    assert "ig_NEW" in ids
    assert "lot10-hutong-hokkien-mee" in ids
    assert "kim-lian-kee" in ids
    assert len(rows) == 3


def test_stale_ig_row_with_no_matching_candidate_is_dropped(tmp_path: Path):
    """An existing ig_OLD row with no live candidate disappears on re-export
    — the ingest pipeline owns the ig_* namespace."""
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    restaurants.write_text(json.dumps([_curated_row("ig_OLD")]))
    # No candidates at all → the ig_OLD row gets cleared.
    exporter.export(candidates_path=candidates, restaurants_path=restaurants)
    assert _read_restaurants(restaurants) == []


# ---- status filtering -----------------------------------------------------

def test_pending_candidates_are_ignored(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    pending = _full_live_candidate("ig_P")
    pending.status = "pending"
    candidates_store.append(pending, path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.exported == 0
    assert result.total_live == 0
    assert _read_restaurants(restaurants) == []


def test_rejected_candidates_are_ignored(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    rejected = _full_live_candidate("ig_R")
    rejected.status = "rejected"
    candidates_store.append(rejected, path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.exported == 0
    assert result.total_live == 0


# ---- validation -----------------------------------------------------------

def test_live_candidate_missing_lat_skipped_with_invalid_id(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X", lat=None), path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.exported == 0
    assert result.skipped_invalid == 1
    assert result.total_live == 1
    assert result.invalid_ids == ["ig_X"]
    assert _read_restaurants(restaurants) == []


def test_live_candidate_with_empty_meal_tags_skipped(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X", meal_tags=[]), path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.skipped_invalid == 1
    assert result.invalid_ids == ["ig_X"]


def test_live_candidate_with_empty_vibe_tags_skipped(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X", vibe_tags=[]), path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.skipped_invalid == 1


def test_live_candidate_missing_insider_tip_skipped(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X", insider_tip=None), path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.skipped_invalid == 1


def test_live_candidate_missing_stall_name_skipped(tmp_path: Path):
    """Without a stall_name there's nothing to call the Restaurant — skip."""
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X", stall_name=None), path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.skipped_invalid == 1


def test_mixed_valid_and_invalid_split_correctly(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_GOOD"), path=candidates)
    candidates_store.append(_full_live_candidate("ig_BAD", lat=None), path=candidates)
    candidates_store.append(_full_live_candidate("ig_GOOD2"), path=candidates)

    result = exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert result.exported == 2
    assert result.skipped_invalid == 1
    assert result.total_live == 3
    assert result.invalid_ids == ["ig_BAD"]
    rows = _read_restaurants(restaurants)
    assert sorted(r["id"] for r in rows) == ["ig_GOOD", "ig_GOOD2"]


# ---- output shape ---------------------------------------------------------

def test_output_sorted_by_id(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    restaurants.write_text(json.dumps([_curated_row("zzz-spot"), _curated_row("aaa-spot")]))
    candidates_store.append(_full_live_candidate("ig_M"), path=candidates)

    exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    rows = _read_restaurants(restaurants)
    assert [r["id"] for r in rows] == ["aaa-spot", "ig_M", "zzz-spot"]


def test_atomic_write_leaves_no_tmp_file_on_success(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X"), path=candidates)

    exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert list(tmp_path.glob("*.tmp")) == []


def test_output_is_pretty_printed_two_space_indent(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X"), path=candidates)

    exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    text = restaurants.read_text(encoding="utf-8")
    # A pretty-printed array has a newline after the opening bracket.
    assert text.startswith("[\n")
    # A 2-space indent: the first key is preceded by exactly 4 spaces (one
    # array-element indent + one object indent).
    assert "    \"id\":" in text


def test_export_creates_parent_dir(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "subdir" / "nested" / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X"), path=candidates)

    exporter.export(candidates_path=candidates, restaurants_path=restaurants)

    assert restaurants.exists()


def test_idempotent_re_export_yields_same_file(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    restaurants = tmp_path / "restaurants.json"
    candidates_store.append(_full_live_candidate("ig_X"), path=candidates)

    exporter.export(candidates_path=candidates, restaurants_path=restaurants)
    first = restaurants.read_bytes()
    exporter.export(candidates_path=candidates, restaurants_path=restaurants)
    second = restaurants.read_bytes()

    assert first == second
