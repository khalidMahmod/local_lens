"""Promote live Candidates → rows in `data/restaurants.json`.

Hand-curated entries (id NOT prefixed with `ig_`) are immune: the exporter
splits the existing file into ig-owned vs curated rows, replaces only the
ig-owned set with the latest live Candidates, and rewrites. Curated rows pass
through verbatim.

Re-running the exporter is idempotent — editing a Candidate and re-running
overwrites its row in `restaurants.json`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ingest import candidates_store
from ingest.models import Candidate

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RESTAURANTS_PATH = _PROJECT_ROOT / "data" / "restaurants.json"

# Fields that must be non-null on a live Candidate before it's eligible for
# export. List-typed fields must additionally be non-empty.
REQUIRED_RESTAURANT_FIELDS = (
    "lat",
    "lng",
    "area",
    "cuisine",
    "price_tier",
    "meal_tags",
    "indoor",
    "vibe_tags",
    "halal_status",
    "google_maps_link",
    "insider_tip",
)

_LIST_FIELDS = frozenset({"meal_tags", "vibe_tags"})

INGEST_ID_PREFIX = "ig_"


@dataclass(frozen=True)
class ExportResult:
    exported: int
    skipped_invalid: int
    total_live: int
    invalid_ids: list[str] = field(default_factory=list)


class _ValidationError(ValueError):
    pass


def export(
    *,
    candidates_path: Path | None = None,
    restaurants_path: Path | None = None,
) -> ExportResult:
    target = restaurants_path or _DEFAULT_RESTAURANTS_PATH

    live = list(candidates_store.iter_all(status="live", path=candidates_path))

    new_ig_rows: list[dict[str, Any]] = []
    invalid_ids: list[str] = []
    for candidate in live:
        try:
            new_ig_rows.append(_candidate_to_restaurant(candidate))
        except _ValidationError as exc:
            logger.info("Skipping live candidate %s: %s", candidate.id, exc)
            invalid_ids.append(candidate.id)

    curated_rows = _read_curated_rows(target)
    merged = curated_rows + new_ig_rows
    merged.sort(key=lambda row: row.get("id", ""))

    _atomic_write_json(target, merged)

    return ExportResult(
        exported=len(new_ig_rows),
        skipped_invalid=len(invalid_ids),
        total_live=len(live),
        invalid_ids=invalid_ids,
    )


# ---- internals ------------------------------------------------------------

def _candidate_to_restaurant(candidate: Candidate) -> dict[str, Any]:
    if not candidate.stall_name:
        raise _ValidationError("missing stall_name")

    for field_name in REQUIRED_RESTAURANT_FIELDS:
        value = getattr(candidate, field_name)
        if value is None:
            raise _ValidationError(f"missing field {field_name}")
        if field_name in _LIST_FIELDS and not value:
            raise _ValidationError(f"empty list for {field_name}")

    return {
        "id": candidate.id,
        "name": candidate.stall_name,
        "lat": float(candidate.lat),
        "lng": float(candidate.lng),
        "area": candidate.area,
        "cuisine": candidate.cuisine,
        "price_tier": candidate.price_tier,
        "meal_tags": list(candidate.meal_tags or []),
        "indoor": bool(candidate.indoor),
        "vibe_tags": list(candidate.vibe_tags or []),
        "halal_status": candidate.halal_status,
        "insider_tip": candidate.insider_tip,
        "google_maps_link": candidate.google_maps_link,
    }


def _read_curated_rows(path: Path) -> list[dict[str, Any]]:
    """Existing rows whose id does NOT start with `ig_` — these are immune to
    ingestion. Returns [] when restaurants.json is missing."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON list")
    return [r for r in raw if not str(r.get("id", "")).startswith(INGEST_ID_PREFIX)]


def _atomic_write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
