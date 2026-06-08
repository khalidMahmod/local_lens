"""Tests for bot.messenger.sender — Facebook Send API wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bot.messenger.sender import build_text_message, build_quick_reply_message, send_message


def test_build_text_message():
    msg = build_text_message("123", "Hello")
    assert msg == {
        "recipient": {"id": "123"},
        "message": {"text": "Hello"},
    }


def test_build_quick_reply_message():
    replies = [
        {"title": "Option A", "payload": "A"},
        {"title": "Option B", "payload": "B"},
    ]
    msg = build_quick_reply_message("123", "Pick one:", replies)
    assert msg["recipient"]["id"] == "123"
    assert msg["message"]["text"] == "Pick one:"
    qr = msg["message"]["quick_replies"]
    assert len(qr) == 2
    assert qr[0]["content_type"] == "text"
    assert qr[0]["title"] == "Option A"
    assert qr[0]["payload"] == "A"


@pytest.mark.asyncio
async def test_send_message_posts_to_graph_api():
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"recipient_id": "123", "message_id": "mid.1"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    body = build_text_message("123", "Hi")
    result = await send_message(body, page_token="tok_test", client=mock_client)

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "graph.facebook.com" in call_kwargs.args[0]
    assert result == {"recipient_id": "123", "message_id": "mid.1"}
