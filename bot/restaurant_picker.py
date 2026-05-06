"""Pick 1–2 nearby restaurants for the meal-time food add-on.

Selection rules (spec lines 97–104):
  - Filter by current meal-time window (`time_of_day_window`).
  - When `session.dietary.halal_only`, allow only `halal_certified` and
    `muslim_friendly`; rank `halal_certified` first.
  - Proximity filter (≤2km).
  - When raining, prefer indoor spots.
  - Cap at 2.
  - Skip entirely when the active package already covers this meal window
    (caller passes `exclude_meal_window=context.time_of_day_window`).
  - Skip in the `between` window (no meal add-on outside meal hours).
"""

from __future__ import annotations

from geopy.distance import distance as geo_distance

from bot import data_loader
from bot.models import Context, Restaurant, Session

_RAIN_CONDITIONS = frozenset({"rain", "thunderstorm", "drizzle"})
_HALAL_OK = frozenset({"halal_certified", "muslim_friendly"})
_DEFAULT_RADIUS_KM = 2.0
_DEFAULT_MAX_RESULTS = 2


def pick_restaurants(
    context: Context,
    session: Session,
    *,
    restaurants: list[Restaurant] | None = None,
    exclude_meal_window: str | None = None,
    max_results: int = _DEFAULT_MAX_RESULTS,
    radius_km: float = _DEFAULT_RADIUS_KM,
) -> list[Restaurant]:
    window = context.time_of_day_window
    if window == "between":
        return []
    if exclude_meal_window == window:
        return []
    if restaurants is None:
        restaurants = data_loader.load_restaurants()

    halal_only = session.dietary.halal_only
    is_raining = context.weather.condition in _RAIN_CONDITIONS

    candidates: list[tuple[Restaurant, float]] = []
    for r in restaurants:
        if window not in r.meal_tags:
            continue
        if halal_only and r.halal_status not in _HALAL_OK:
            continue
        km = geo_distance((context.lat, context.lng), (r.lat, r.lng)).km
        if km > radius_km:
            continue
        candidates.append((r, km))

    def sort_key(item: tuple[Restaurant, float]) -> tuple[int, int, float]:
        r, km = item
        # Lower is better in every position.
        halal_rank = 0 if (halal_only and r.halal_status == "halal_certified") else 1 if halal_only else 0
        weather_rank = 0 if (not is_raining or r.indoor) else 1
        return (halal_rank, weather_rank, km)

    candidates.sort(key=sort_key)
    return [r for r, _ in candidates[:max_results]]
