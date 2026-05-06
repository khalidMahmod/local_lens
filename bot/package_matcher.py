"""Score curated packages against a Context.

Components (each 0–1, weighted into a single score):
  - proximity      (0.5): distance from user to package center, normalized by radius
  - weather        (0.3): condition vs the package's ideal/ok/avoid tags. An
                          `avoid` match disqualifies the package (overall score = 0).
  - time_of_day    (0.2): broad-bucket overlap (morning/afternoon/evening/night)
                          between the package's `time_of_day` and the user's
                          current `time_of_day_window`.

`match_packages(context)` returns scored packages above `threshold`, sorted
descending. The handler decides what to do with the result (free package →
deliver immediately; premium → tease, accept, deliver — Phase 8).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from geopy.distance import distance as geo_distance

from bot import data_loader
from bot.models import Context, Package

# Component weights — must sum to 1.
_WEIGHT_PROXIMITY = 0.5
_WEIGHT_WEATHER = 0.3
_WEIGHT_TIME_OF_DAY = 0.2

# Confidence threshold below which the matcher returns "no match".
DEFAULT_THRESHOLD = 0.5

# Map the spec's narrow meal windows onto the broader buckets that packages use
# in their `time_of_day` field (morning / afternoon / evening / night).
_WINDOW_TO_BROAD: dict[str, str] = {
    "breakfast": "morning",
    "lunch": "afternoon",
    "afternoon_snack": "afternoon",
    "dinner": "evening",
    "late_night": "night",
    "between": "",
}


@dataclass(frozen=True)
class ScoredPackage:
    package: Package
    score: float
    components: dict[str, float] = field(default_factory=dict)


def match_packages(
    context: Context,
    *,
    packages: list[Package] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[ScoredPackage]:
    if packages is None:
        packages = data_loader.load_packages()

    scored: list[ScoredPackage] = []
    for pkg in packages:
        components = {
            "proximity": _proximity_score(context, pkg),
            "weather": _weather_score(context, pkg),
            "time_of_day": _time_of_day_score(context, pkg),
        }
        # Hard disqualifiers — a great-weather, great-time package that is
        # nowhere near the user is still not a match for "what should I do
        # right now?". Same for weather-avoid.
        if components["proximity"] <= 0.0 or _condition_in_avoid(context, pkg):
            total = 0.0
        else:
            total = (
                _WEIGHT_PROXIMITY * components["proximity"]
                + _WEIGHT_WEATHER * components["weather"]
                + _WEIGHT_TIME_OF_DAY * components["time_of_day"]
            )
        scored.append(ScoredPackage(package=pkg, score=total, components=components))

    scored.sort(key=lambda sp: sp.score, reverse=True)
    return [sp for sp in scored if sp.score >= threshold]


def _proximity_score(context: Context, pkg: Package) -> float:
    """Linear decay from 1.0 at the center to 0.0 at 2× radius. Differentiates
    within-radius packages so the sort by score is meaningful."""
    center = pkg.location_center
    km = geo_distance((context.lat, context.lng), (center["lat"], center["lng"])).km
    r = max(pkg.radius_km, 0.001)
    return max(0.0, 1.0 - km / (2 * r))


def _weather_score(context: Context, pkg: Package) -> float:
    cond = context.weather.condition
    tags = pkg.weather_tags
    if cond in tags.get("avoid", []):
        return 0.0
    if cond in tags.get("ideal", []):
        return 1.0
    if cond in tags.get("ok", []):
        return 0.6
    return 0.4  # unknown / unlisted — neutral


def _condition_in_avoid(context: Context, pkg: Package) -> bool:
    return context.weather.condition in pkg.weather_tags.get("avoid", [])


def _time_of_day_score(context: Context, pkg: Package) -> float:
    broad = _WINDOW_TO_BROAD.get(context.time_of_day_window, "")
    if not broad:
        return 0.5  # `between` window or unknown — neutral
    return 1.0 if broad in pkg.time_of_day else 0.3
