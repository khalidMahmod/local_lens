"""Tests for bot.messenger.webhook — HTTP verification and event parsing."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from starlette.testclient import TestClient

from bot.messenger.webhook import create_messenger_app


@pytest.fixture
def app():
    return create_messenger_app(
        page_token="test_page_token",
        verify_token="test_verify_token",
        app_secret="test_app_secret",
        owner_telegram_id="999",
        telegram_bot=None,
    )


@pytest.fixture
def client(app):
    return TestClient(app)


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_endpoint_succeeds_with_correct_token(client):
    resp = client.get(
        "/messenger",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token",
            "hub.challenge": "challenge_123",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "challenge_123"


def test_verify_endpoint_rejects_bad_token(client):
    resp = client.get(
        "/messenger",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "challenge_123",
        },
    )
    assert resp.status_code == 403


def test_receive_rejects_missing_signature(client):
    body = json.dumps({"object": "page", "entry": []})
    resp = client.post("/messenger", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 403


def test_receive_rejects_bad_signature(client):
    body = json.dumps({"object": "page", "entry": []})
    resp = client.post(
        "/messenger",
        content=body,
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": "sha256=bad",
        },
    )
    assert resp.status_code == 403


def test_receive_accepts_valid_signature(client):
    payload = {"object": "page", "entry": []}
    body = json.dumps(payload).encode()
    sig = _sign(body, "test_app_secret")
    resp = client.post(
        "/messenger",
        content=body,
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": sig,
        },
    )
    assert resp.status_code == 200


def test_parse_text_message_event():
    from bot.messenger.webhook import parse_events

    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "123"},
                        "message": {"text": "hello"},
                    }
                ]
            }
        ],
    }
    events = parse_events(payload)
    assert len(events) == 1
    assert events[0]["type"] == "text"
    assert events[0]["text"] == "hello"
    assert events[0]["sender_id"] == "123"


def test_parse_quick_reply_event():
    from bot.messenger.webhook import parse_events

    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "123"},
                        "message": {
                            "text": "View Packages",
                            "quick_reply": {"payload": "VIEW_PACKAGES"},
                        },
                    }
                ]
            }
        ],
    }
    events = parse_events(payload)
    assert len(events) == 1
    assert events[0]["type"] == "quick_reply"
    assert events[0]["payload"] == "VIEW_PACKAGES"


def test_parse_postback_event():
    from bot.messenger.webhook import parse_events

    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "123"},
                        "postback": {"payload": "GET_STARTED"},
                    }
                ]
            }
        ],
    }
    events = parse_events(payload)
    assert len(events) == 1
    assert events[0]["type"] == "postback"
    assert events[0]["payload"] == "GET_STARTED"
