"""Tests for ingest.candidates_store — JSONL append-only working surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest import candidates_store
from ingest.models import Candidate


def _candidate(id_: str = "ig_X", *, status: str = "pending", **overrides) -> Candidate:
    return Candidate(id=id_, status=status, **overrides)


# ---- append + iter_all ----------------------------------------------------

def test_append_and_iter_all(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A"), path=log)
    candidates_store.append(_candidate("ig_B", status="live"), path=log)
    out = list(candidates_store.iter_all(path=log))
    assert [c.id for c in out] == ["ig_A", "ig_B"]
    assert [c.status for c in out] == ["pending", "live"]


def test_iter_all_filter_by_status(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A", status="pending"), path=log)
    candidates_store.append(_candidate("ig_B", status="live"), path=log)
    candidates_store.append(_candidate("ig_C", status="rejected"), path=log)
    live_only = list(candidates_store.iter_all(status="live", path=log))
    assert [c.id for c in live_only] == ["ig_B"]


def test_iter_all_missing_file_returns_empty(tmp_path: Path):
    log = tmp_path / "missing.jsonl"
    assert list(candidates_store.iter_all(path=log)) == []


def test_iter_all_skips_blank_lines(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A"), path=log)
    # Sneak a blank line in (could happen if curator hand-edits the file).
    with log.open("a", encoding="utf-8") as f:
        f.write("\n\n")
    candidates_store.append(_candidate("ig_B"), path=log)
    out = list(candidates_store.iter_all(path=log))
    assert [c.id for c in out] == ["ig_A", "ig_B"]


def test_append_creates_parent_dir(tmp_path: Path):
    log = tmp_path / "subdir" / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A"), path=log)
    assert log.exists()


def test_append_one_line_per_candidate(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A"), path=log)
    candidates_store.append(_candidate("ig_B"), path=log)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    # Each line is a complete JSON object.
    for line in lines:
        json.loads(line)


# ---- existing_ids ---------------------------------------------------------

def test_existing_ids_returns_all_unique_ids(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A"), path=log)
    candidates_store.append(_candidate("ig_B"), path=log)
    candidates_store.append(_candidate("ig_C", status="live"), path=log)
    assert candidates_store.existing_ids(path=log) == {"ig_A", "ig_B", "ig_C"}


def test_existing_ids_missing_file(tmp_path: Path):
    log = tmp_path / "missing.jsonl"
    assert candidates_store.existing_ids(path=log) == set()


# ---- replace_in_place -----------------------------------------------------

def test_replace_in_place_swaps_one_row(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A"), path=log)
    candidates_store.append(_candidate("ig_B"), path=log)
    candidates_store.append(_candidate("ig_C"), path=log)

    updated = _candidate("ig_B", status="live", stall_name="Updated Name")
    candidates_store.replace_in_place(updated, path=log)

    out = list(candidates_store.iter_all(path=log))
    assert [c.id for c in out] == ["ig_A", "ig_B", "ig_C"]
    by_id = {c.id: c for c in out}
    assert by_id["ig_B"].status == "live"
    assert by_id["ig_B"].stall_name == "Updated Name"
    # Other rows untouched.
    assert by_id["ig_A"].status == "pending"
    assert by_id["ig_C"].status == "pending"


def test_replace_in_place_raises_on_missing_id(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A"), path=log)
    with pytest.raises(KeyError):
        candidates_store.replace_in_place(_candidate("ig_NOT_THERE"), path=log)


def test_replace_in_place_raises_when_file_missing(tmp_path: Path):
    log = tmp_path / "missing.jsonl"
    with pytest.raises(FileNotFoundError):
        candidates_store.replace_in_place(_candidate("ig_X"), path=log)


def test_replace_in_place_no_tmp_artifact_on_success(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    candidates_store.append(_candidate("ig_A"), path=log)
    candidates_store.replace_in_place(_candidate("ig_A", status="live"), path=log)
    # Atomic write should have removed the .tmp via os.replace.
    assert list(tmp_path.glob("*.tmp")) == []


def test_replace_in_place_preserves_unrelated_field_values(tmp_path: Path):
    log = tmp_path / "candidates.jsonl"
    full = _candidate(
        "ig_A",
        stall_name="Original",
        meal_tags=["lunch"],
        indoor=True,
    )
    candidates_store.append(full, path=log)

    updated = _candidate("ig_A", stall_name="Renamed")
    candidates_store.replace_in_place(updated, path=log)

    [out] = list(candidates_store.iter_all(path=log))
    assert out.stall_name == "Renamed"
    # The updated Candidate didn't carry meal_tags/indoor — they're cleared
    # because replace_in_place writes the whole row, not a patch.
    assert out.meal_tags is None
    assert out.indoor is None
