"""Tests for bot.messenger.renderer — Messenger message formatting."""

from __future__ import annotations

from bot.messenger.renderer import (
    render_package_detail,
    render_package_list,
    render_pricing_table,
    render_welcome,
    MENU_QUICK_REPLIES,
)
from bot.models import Package, PackageStep


def _step(order: int = 1) -> PackageStep:
    return PackageStep(
        order=order,
        place_name=f"Place {order}",
        place_location={"lat": 3.15, "lng": 101.71},
        duration_minutes=60,
        description=f"Visit place {order}",
        insider_tip="A tip",
        google_maps_link="https://maps.app.goo.gl/x",
    )


def _package(
    id_: str = "melaka-daytrip-private",
    name: str = "Melaka Heritage Day Trip",
    tier: str = "premium",
    price_rm: int = 780,
    duration_minutes: int = 600,
    audience: list[str] | None = None,
    inclusions: list[str] | None = None,
) -> Package:
    return Package(
        id=id_,
        name=name,
        tier=tier,
        price_rm=price_rm,
        duration_minutes=duration_minutes,
        location_center={"lat": 2.19, "lng": 102.25, "name": "Melaka"},
        radius_km=3.0,
        intent_tags=["explore"],
        weather_tags={"ideal": ["clear"], "ok": [], "avoid": []},
        indoor_percentage=50,
        time_of_day=["morning"],
        steps=[_step(1), _step(2)],
        why_it_works="Great trip",
        upsells=[],
        audience_tags=audience or ["family", "friends", "couples"],
        inclusions=inclusions or [],
    )


def test_welcome_message_contains_greeting():
    text, replies = render_welcome()
    assert "LocalLens" in text
    assert len(replies) == 3
    assert replies[0]["title"] == "View Packages"
    assert replies[0]["payload"] == "VIEW_PACKAGES"


def test_menu_quick_replies_has_three_options():
    assert len(MENU_QUICK_REPLIES) == 3
    payloads = [r["payload"] for r in MENU_QUICK_REPLIES]
    assert "VIEW_PACKAGES" in payloads
    assert "GET_PRICING" in payloads
    assert "TALK_TO_HUMAN" in payloads


def test_package_list_includes_all_packages():
    pkgs = [_package(id_="a", name="Trip A"), _package(id_="b", name="Trip B")]
    text, replies = render_package_list(pkgs)
    assert "Trip A" in text
    assert "Trip B" in text
    assert len(replies) == 3


def test_package_list_quick_replies_have_pkg_prefix():
    pkgs = [_package(id_="melaka")]
    _, replies = render_package_list(pkgs)
    pkg_reply = replies[0]
    assert pkg_reply["payload"] == "PKG:melaka"


def test_package_detail_shows_price_and_duration():
    pkg = _package(price_rm=780, duration_minutes=600)
    text, replies = render_package_detail(pkg)
    assert "RM780" in text
    assert "10 hours" in text or "600" in text


def test_package_detail_shows_inclusions():
    pkg = _package(inclusions=["Private transport", "Complimentary lunch"])
    text, _ = render_package_detail(pkg)
    assert "Private transport" in text
    assert "Complimentary lunch" in text


def test_package_detail_shows_audience():
    pkg = _package(audience=["family", "couples"])
    text, _ = render_package_detail(pkg)
    assert "family" in text
    assert "couples" in text


def test_package_detail_quick_replies_include_book():
    pkg = _package(id_="melaka")
    _, replies = render_package_detail(pkg)
    payloads = [r["payload"] for r in replies]
    assert "BOOK:melaka" in payloads
    assert "ASK_QUESTION:melaka" in payloads
    assert "BACK_TO_PACKAGES" in payloads


def test_pricing_table_lists_all_packages():
    pkgs = [
        _package(id_="a", name="Trip A", price_rm=320),
        _package(id_="b", name="Trip B", price_rm=780),
    ]
    text, replies = render_pricing_table(pkgs)
    assert "Trip A" in text and "RM320" in text
    assert "Trip B" in text and "RM780" in text
    assert len(replies) == 3
