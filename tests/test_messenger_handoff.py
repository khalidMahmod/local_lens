"""Tests for bot.messenger.handoff — owner notification + customer message."""

from __future__ import annotations

from bot.messenger.handoff import format_owner_notification, format_customer_reply


def test_owner_notification_with_package():
    text = format_owner_notification(
        customer_name="Ahmad",
        package_name="Melaka Heritage Day Trip",
        price_rm=780,
        sender_id="12345",
    )
    assert "Ahmad" in text
    assert "Melaka Heritage Day Trip" in text
    assert "RM780" in text
    assert "12345" in text


def test_owner_notification_without_package():
    text = format_owner_notification(
        customer_name="Ahmad",
        package_name=None,
        price_rm=None,
        sender_id="12345",
    )
    assert "Ahmad" in text
    assert "General inquiry" in text
    assert "12345" in text


def test_customer_reply_is_friendly():
    text = format_customer_reply()
    assert "team" in text.lower() or "connect" in text.lower()
