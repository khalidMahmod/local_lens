"""Ingestion-domain dataclasses.

`Candidate` is the persistent working-surface row (one per JSONL line).
`RawItem` is the transient hand-off from collector to extractor — never persisted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


STATUS_VALUES = frozenset({"pending", "live", "rejected"})
# `None` is allowed for the extraction-block fields below — present in the
# Candidate before the extractor has run, or after a failed extraction.
HALAL_SIGNALS = frozenset({"no_pork_visible", "pork_visible", "unclear"})
STALL_NAME_CONFIDENCE = frozenset({"high", "medium", "low"})

SOURCE_PLATFORMS = frozenset({"instagram"})  # extends as new collectors land


def _require_enum(
    value: Any, allowed: frozenset[str], field_name: str, *, allow_none: bool = False
) -> Any:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} must not be None")
    if value not in allowed:
        raise ValueError(
            f"Invalid {field_name}: {value!r}. Expected one of {sorted(allowed)}."
        )
    return value


@dataclass
class Candidate:
    # --- identity / provenance (collector-set) -------------------------
    id: str
    status: str = "pending"
    source_url: str = ""
    source_platform: str = "instagram"
    scraped_at: str = ""
    thumbnail_path: str | None = None

    # --- extraction (OpenAI vision-set) --------------------------------
    stall_name: str | None = None
    stall_name_confidence: str | None = None
    dish_featured: str | None = None
    viral_hook: str | None = None
    claimed_must_order: str | None = None
    halal_signals: str | None = None
    operating_hours_mentioned: str | None = None
    google_maps_search_query: str | None = None
    candidate_quality_score: int | None = None
    extractor_notes: str | None = None

    # --- manual fill (curator-set) -------------------------------------
    lat: float | None = None
    lng: float | None = None
    area: str | None = None
    cuisine: str | None = None
    price_tier: str | None = None
    meal_tags: list[str] | None = None
    indoor: bool | None = None
    vibe_tags: list[str] | None = None
    halal_status: str | None = None
    google_maps_link: str | None = None
    insider_tip: str | None = None

    def __post_init__(self) -> None:
        _require_enum(self.status, STATUS_VALUES, "status")
        _require_enum(self.halal_signals, HALAL_SIGNALS, "halal_signals", allow_none=True)
        _require_enum(
            self.stall_name_confidence,
            STALL_NAME_CONFIDENCE,
            "stall_name_confidence",
            allow_none=True,
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Candidate":
        # Pull fields out explicitly so an unknown key in d doesn't silently
        # tank construction. Lists are copied so the dataclass can be mutated
        # safely.
        return cls(
            id=str(d["id"]),
            status=str(d.get("status", "pending")),
            source_url=str(d.get("source_url", "")),
            source_platform=str(d.get("source_platform", "instagram")),
            scraped_at=str(d.get("scraped_at", "")),
            thumbnail_path=d.get("thumbnail_path"),
            stall_name=d.get("stall_name"),
            stall_name_confidence=d.get("stall_name_confidence"),
            dish_featured=d.get("dish_featured"),
            viral_hook=d.get("viral_hook"),
            claimed_must_order=d.get("claimed_must_order"),
            halal_signals=d.get("halal_signals"),
            operating_hours_mentioned=d.get("operating_hours_mentioned"),
            google_maps_search_query=d.get("google_maps_search_query"),
            candidate_quality_score=(
                None if d.get("candidate_quality_score") is None else int(d["candidate_quality_score"])
            ),
            extractor_notes=d.get("extractor_notes"),
            lat=None if d.get("lat") is None else float(d["lat"]),
            lng=None if d.get("lng") is None else float(d["lng"]),
            area=d.get("area"),
            cuisine=d.get("cuisine"),
            price_tier=d.get("price_tier"),
            meal_tags=None if d.get("meal_tags") is None else list(d["meal_tags"]),
            indoor=None if d.get("indoor") is None else bool(d["indoor"]),
            vibe_tags=None if d.get("vibe_tags") is None else list(d["vibe_tags"]),
            halal_status=d.get("halal_status"),
            google_maps_link=d.get("google_maps_link"),
            insider_tip=d.get("insider_tip"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RawItem:
    """Collector → extractor hand-off. Transient — never written to disk as-is.
    The extractor reads thumbnail_path and produces a `Candidate`.
    """

    reel_id: str
    candidate_id: str
    source_url: str
    thumbnail_path: Path
    caption: str
    play_count: int | None
    like_count: int | None
    posted_at: str | None
    scraped_at: str
