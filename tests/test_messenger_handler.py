"""Tests for bot.messenger.handler — event routing logic."""

from __future__ import annotations

from bot.messenger.handler import route_event, Action


def test_get_started_postback_returns_welcome():
    event = {"type": "postback", "payload": "GET_STARTED", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="welcome", sender_id="123")


def test_view_packages_returns_package_list():
    event = {"type": "quick_reply", "payload": "VIEW_PACKAGES", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="package_list", sender_id="123")


def test_get_pricing_returns_pricing_table():
    event = {"type": "quick_reply", "payload": "GET_PRICING", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="pricing_table", sender_id="123")


def test_pkg_prefix_returns_package_detail():
    event = {"type": "quick_reply", "payload": "PKG:melaka-daytrip", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="package_detail", sender_id="123", package_id="melaka-daytrip")


def test_book_prefix_returns_handoff():
    event = {"type": "quick_reply", "payload": "BOOK:melaka-daytrip", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="handoff", sender_id="123", package_id="melaka-daytrip")


def test_ask_question_returns_handoff():
    event = {"type": "quick_reply", "payload": "ASK_QUESTION:melaka-daytrip", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="handoff", sender_id="123", package_id="melaka-daytrip")


def test_talk_to_human_returns_handoff_no_package():
    event = {"type": "quick_reply", "payload": "TALK_TO_HUMAN", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="handoff", sender_id="123", package_id=None)


def test_back_to_packages_returns_package_list():
    event = {"type": "quick_reply", "payload": "BACK_TO_PACKAGES", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="package_list", sender_id="123")


def test_freeform_text_with_price_keyword_returns_pricing():
    event = {"type": "text", "text": "how much is the melaka trip?", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="pricing_table", sender_id="123")


def test_freeform_text_with_package_keyword_returns_pricing():
    event = {"type": "text", "text": "what packages do you have?", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="package_list", sender_id="123")


def test_freeform_text_unrecognized_returns_handoff():
    event = {"type": "text", "text": "can I bring my dog?", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="handoff", sender_id="123", package_id=None)


def test_freeform_text_hi_returns_welcome():
    event = {"type": "text", "text": "hi", "sender_id": "123"}
    action = route_event(event)
    assert action == Action(kind="welcome", sender_id="123")
