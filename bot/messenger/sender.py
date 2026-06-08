"""Send messages via the Facebook Messenger Send API."""

from __future__ import annotations

from typing import Any

import httpx

_GRAPH_API_URL = "https://graph.facebook.com/v21.0/me/messages"

QuickReply = dict[str, str]


def build_text_message(recipient_id: str, text: str) -> dict[str, Any]:
    return {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }


def build_quick_reply_message(
    recipient_id: str, text: str, quick_replies: list[QuickReply]
) -> dict[str, Any]:
    return {
        "recipient": {"id": recipient_id},
        "message": {
            "text": text,
            "quick_replies": [
                {
                    "content_type": "text",
                    "title": qr["title"],
                    "payload": qr["payload"],
                }
                for qr in quick_replies
            ],
        },
    }


async def send_message(
    message_body: dict[str, Any],
    *,
    page_token: str,
    client: httpx.AsyncClient | Any | None = None,
) -> dict[str, Any]:
    should_close = False
    if client is None:
        client = httpx.AsyncClient()
        should_close = True
    try:
        response = await client.post(
            _GRAPH_API_URL,
            params={"access_token": page_token},
            json=message_body,
        )
        _rhs = response.raise_for_status()
        if hasattr(_rhs, "__await__"):
            await _rhs
        data = response.json()
        if hasattr(data, "__await__"):
            data = await data
        return data
    finally:
        if should_close:
            await client.aclose()
