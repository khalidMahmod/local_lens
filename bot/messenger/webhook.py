"""Starlette ASGI app for Facebook Messenger webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route

from bot import data_loader
from bot.messenger.handler import route_event
from bot.messenger.handoff import format_customer_reply, format_owner_notification
from bot.messenger.renderer import (
    render_package_detail,
    render_package_list,
    render_pricing_table,
    render_welcome,
)
from bot.messenger.sender import build_quick_reply_message, build_text_message, send_message

logger = logging.getLogger(__name__)


def parse_events(body: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for entry in body.get("entry", []):
        for msg_event in entry.get("messaging", []):
            sender_id = msg_event.get("sender", {}).get("id", "")
            if "postback" in msg_event:
                events.append({
                    "type": "postback",
                    "payload": msg_event["postback"].get("payload", ""),
                    "sender_id": sender_id,
                })
            elif "message" in msg_event:
                message = msg_event["message"]
                if "quick_reply" in message:
                    events.append({
                        "type": "quick_reply",
                        "payload": message["quick_reply"].get("payload", ""),
                        "sender_id": sender_id,
                    })
                else:
                    events.append({
                        "type": "text",
                        "text": message.get("text", ""),
                        "sender_id": sender_id,
                    })
    return events


def _verify_signature(body: bytes, signature: str, app_secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        app_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_messenger_app(
    *,
    page_token: str,
    verify_token: str,
    app_secret: str,
    owner_telegram_id: str,
    telegram_bot: Any | None,
) -> Starlette:

    async def verify(request: Request) -> PlainTextResponse:
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge", "")
        if mode == "subscribe" and token == verify_token:
            return PlainTextResponse(challenge, status_code=200)
        return PlainTextResponse("Forbidden", status_code=403)

    async def receive(request: Request) -> JSONResponse:
        body_bytes = await request.body()
        signature = request.headers.get("x-hub-signature-256", "")
        if not signature or not _verify_signature(body_bytes, signature, app_secret):
            return JSONResponse({"error": "bad signature"}, status_code=403)

        payload = json.loads(body_bytes)
        events = parse_events(payload)

        async with httpx.AsyncClient() as client:
            for event in events:
                try:
                    await _process_event(
                        event,
                        page_token=page_token,
                        owner_telegram_id=owner_telegram_id,
                        telegram_bot=telegram_bot,
                        client=client,
                    )
                except Exception:
                    logger.exception("Error processing Messenger event: %s", event)

        return JSONResponse({"status": "ok"}, status_code=200)

    return Starlette(routes=[
        Route("/messenger", verify, methods=["GET"]),
        Route("/messenger", receive, methods=["POST"]),
    ])


async def _process_event(
    event: dict[str, Any],
    *,
    page_token: str,
    owner_telegram_id: str,
    telegram_bot: Any | None,
    client: httpx.AsyncClient,
) -> None:
    action = route_event(event)
    packages = data_loader.load_packages()

    if action.kind == "welcome":
        text, replies = render_welcome()
        msg = build_quick_reply_message(action.sender_id, text, replies)
        await send_message(msg, page_token=page_token, client=client)

    elif action.kind == "package_list":
        text, replies = render_package_list(packages)
        msg = build_quick_reply_message(action.sender_id, text, replies)
        await send_message(msg, page_token=page_token, client=client)

    elif action.kind == "pricing_table":
        text, replies = render_pricing_table(packages)
        msg = build_quick_reply_message(action.sender_id, text, replies)
        await send_message(msg, page_token=page_token, client=client)

    elif action.kind == "package_detail":
        pkg = next((p for p in packages if p.id == action.package_id), None)
        if pkg is None:
            text, replies = render_package_list(packages)
            msg = build_quick_reply_message(action.sender_id, text, replies)
        else:
            text, replies = render_package_detail(pkg)
            msg = build_quick_reply_message(action.sender_id, text, replies)
        await send_message(msg, page_token=page_token, client=client)

    elif action.kind == "handoff":
        customer_reply = format_customer_reply()
        msg = build_text_message(action.sender_id, customer_reply)
        await send_message(msg, page_token=page_token, client=client)

        pkg = next((p for p in packages if p.id == action.package_id), None) if action.package_id else None
        owner_text = format_owner_notification(
            customer_name=f"User {action.sender_id}",
            package_name=pkg.name if pkg else None,
            price_rm=pkg.price_rm if pkg else None,
            sender_id=action.sender_id,
        )
        if telegram_bot and owner_telegram_id:
            try:
                await telegram_bot.send_message(
                    chat_id=owner_telegram_id, text=owner_text
                )
            except Exception:
                logger.exception("Failed to send Telegram handoff notification")
