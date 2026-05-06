"""Tests for bot.weather. No real network calls — http_get and clock are injected."""

from __future__ import annotations

from typing import Any

import pytest

from bot.weather import fetch_current_and_forecast
from bot.models import Weather


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeHttp:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, params: dict[str, Any], timeout: float | None = None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResponse(self._payload)


class _FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _sample_payload() -> dict[str, Any]:
    return {
        "weather": [{"id": 802, "main": "Clouds", "description": "scattered clouds"}],
        "main": {"temp": 30.4, "humidity": 75},
        "name": "Kuala Lumpur",
    }


def test_fetch_calls_openweathermap_with_correct_url_and_params():
    http = _FakeHttp(_sample_payload())
    fetch_current_and_forecast(
        3.1578,
        101.7117,
        api_key="test-key",
        http_get=http,
        clock=_FakeClock(),
        cache={},
    )
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == "https://api.openweathermap.org/data/2.5/weather"
    assert call["params"]["lat"] == 3.1578
    assert call["params"]["lon"] == 101.7117
    assert call["params"]["appid"] == "test-key"
    assert call["params"]["units"] == "metric"


def test_fetch_parses_response_into_weather():
    http = _FakeHttp(_sample_payload())
    w = fetch_current_and_forecast(
        3.1578, 101.7117, api_key="k", http_get=http, clock=_FakeClock(), cache={}
    )
    assert isinstance(w, Weather)
    assert w.condition == "clouds"
    assert w.description == "scattered clouds"
    assert w.temp_c == pytest.approx(30.4)


def test_second_call_within_ttl_hits_cache():
    http = _FakeHttp(_sample_payload())
    cache: dict = {}
    clock = _FakeClock(0.0)
    fetch_current_and_forecast(
        3.1578, 101.7117, api_key="k", http_get=http, clock=clock, cache=cache
    )
    clock.t = 300.0  # 5 min later, still under 10-min TTL
    fetch_current_and_forecast(
        3.1578, 101.7117, api_key="k", http_get=http, clock=clock, cache=cache
    )
    assert len(http.calls) == 1


def test_cache_expires_after_ttl():
    http = _FakeHttp(_sample_payload())
    cache: dict = {}
    clock = _FakeClock(0.0)
    fetch_current_and_forecast(
        3.1578, 101.7117, api_key="k", http_get=http, clock=clock, cache=cache,
        ttl_seconds=600.0,
    )
    clock.t = 700.0  # past 10-min TTL
    fetch_current_and_forecast(
        3.1578, 101.7117, api_key="k", http_get=http, clock=clock, cache=cache,
        ttl_seconds=600.0,
    )
    assert len(http.calls) == 2


def test_different_coordinates_do_not_share_cache():
    http = _FakeHttp(_sample_payload())
    cache: dict = {}
    clock = _FakeClock(0.0)
    fetch_current_and_forecast(
        3.1578, 101.7117, api_key="k", http_get=http, clock=clock, cache=cache
    )
    fetch_current_and_forecast(
        3.1437, 101.6981, api_key="k", http_get=http, clock=clock, cache=cache
    )
    assert len(http.calls) == 2


def test_nearby_coordinates_share_cache_after_rounding():
    """Coords ~10m apart should hit the same cache slot (rounded to ~110m)."""
    http = _FakeHttp(_sample_payload())
    cache: dict = {}
    clock = _FakeClock(0.0)
    fetch_current_and_forecast(
        3.15780, 101.71170, api_key="k", http_get=http, clock=clock, cache=cache
    )
    fetch_current_and_forecast(
        3.15782, 101.71171, api_key="k", http_get=http, clock=clock, cache=cache
    )
    assert len(http.calls) == 1
