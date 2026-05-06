"""OpenWeatherMap client with an in-memory TTL cache.

Tests inject `http_get`, `clock`, and `cache` to avoid network and time coupling.
Production callers pass nothing: the module-level cache and `requests.get` are
used, with the API key pulled from `config.load_config()`.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

from bot.models import Weather

_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
_DEFAULT_TTL_SECONDS = 600.0  # 10 min — keeps free-tier quota safe.
_CACHE_PRECISION = 3  # ~110m bucketing.

# Module-level cache for production use. Tests pass their own dict.
_MODULE_CACHE: dict[tuple[float, float], tuple[float, Weather]] = {}


def fetch_current_and_forecast(
    lat: float,
    lng: float,
    *,
    api_key: str | None = None,
    http_get: Callable[..., Any] | None = None,
    clock: Callable[[], float] | None = None,
    cache: dict[tuple[float, float], tuple[float, Weather]] | None = None,
    ttl_seconds: float = _DEFAULT_TTL_SECONDS,
) -> Weather:
    if api_key is None:
        from config import load_config
        api_key = load_config().openweathermap_api_key
    if http_get is None:
        http_get = requests.get
    if clock is None:
        clock = time.monotonic
    if cache is None:
        cache = _MODULE_CACHE

    key = (round(lat, _CACHE_PRECISION), round(lng, _CACHE_PRECISION))
    now = clock()
    hit = cache.get(key)
    if hit is not None:
        ts, weather = hit
        if now - ts < ttl_seconds:
            return weather

    resp = http_get(
        _BASE_URL,
        params={"lat": lat, "lon": lng, "appid": api_key, "units": "metric"},
        timeout=5.0,
    )
    resp.raise_for_status()
    data = resp.json()
    weather = _parse(data)
    cache[key] = (now, weather)
    return weather


def _parse(data: dict[str, Any]) -> Weather:
    weather_block = data["weather"][0]
    return Weather(
        condition=str(weather_block["main"]).lower(),
        description=str(weather_block["description"]),
        temp_c=float(data["main"]["temp"]),
    )
