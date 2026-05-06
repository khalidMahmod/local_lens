"""Build a Context object for a session at a given moment.

Produces `{lat, lng, area_name, weather, time_of_day_window}`. Time-of-day
windows follow the spec table (KL local time). Area is the closest seeded
location within 3km, else "KL".
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from geopy.distance import distance as geo_distance

from bot import data_loader
from bot.models import Context, Location, Session, Weather
from bot.weather import fetch_current_and_forecast

KL_TZ = ZoneInfo("Asia/Kuala_Lumpur")

# (window_name, start, end) — half-open intervals on local KL time.
# Late_night spans midnight, handled separately below.
_WINDOWS: list[tuple[str, time, time]] = [
    ("breakfast",       time(7, 0),  time(10, 30)),
    ("lunch",           time(11, 30), time(14, 30)),
    ("afternoon_snack", time(15, 0), time(17, 30)),
    ("dinner",          time(18, 30), time(22, 0)),
]
_LATE_NIGHT_START = time(22, 0)
_LATE_NIGHT_END = time(2, 0)

_AREA_RADIUS_KM = 3.0


def time_of_day_window(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    t = now.astimezone(KL_TZ).time()
    for name, start, end in _WINDOWS:
        if start <= t < end:
            return name
    if t >= _LATE_NIGHT_START or t < _LATE_NIGHT_END:
        return "late_night"
    return "between"


def nearest_area(
    lat: float,
    lng: float,
    locations: Iterable[Location],
    max_km: float = _AREA_RADIUS_KM,
) -> str:
    best: Location | None = None
    best_km = float("inf")
    for loc in locations:
        km = geo_distance((lat, lng), (loc.lat, loc.lng)).km
        if km <= max_km and km < best_km:
            best = loc
            best_km = km
    return best.area if best is not None else "KL"


def build_context(
    session: Session,
    now: datetime,
    *,
    locations: list[Location] | None = None,
    weather_fn: Callable[[float, float], Weather] | None = None,
) -> Context:
    if session.location is None:
        raise ValueError("session has no location; cannot build context")
    if locations is None:
        locations = data_loader.load_locations()
    if weather_fn is None:
        weather_fn = fetch_current_and_forecast

    lat = session.location["lat"]
    lng = session.location["lng"]
    return Context(
        lat=lat,
        lng=lng,
        area_name=nearest_area(lat, lng, locations),
        weather=weather_fn(lat, lng),
        time_of_day_window=time_of_day_window(now),
    )
