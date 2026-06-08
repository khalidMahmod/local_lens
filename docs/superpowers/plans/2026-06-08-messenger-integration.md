# Messenger Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Facebook Messenger bot that answers package inquiries and hands off to the business owner via Telegram notification.

**Architecture:** New `bot/messenger/` module with its own webhook, handler, renderer, sender, and handoff layers. Shares `data/packages.json` via `bot.data_loader`. Coexists on the same Fly.io app alongside the Telegram bot. Stateless — no sessions, no LLM calls.

**Tech Stack:** `httpx` (async HTTP for Facebook Send API), `starlette` (ASGI webhook routes), existing `python-telegram-bot` (for owner notifications). Facebook Messenger Platform API v21.0.

**Spec:** `docs/superpowers/specs/2026-06-08-messenger-integration-design.md`

---

## File Structure

```
bot/messenger/
    __init__.py          — empty
    renderer.py          — format packages for Messenger (text + quick reply payloads)
    sender.py            — send messages via Facebook Send API
    handler.py           — route incoming events to actions
    handoff.py           — notify owner via Telegram + reply to customer
    webhook.py           — Starlette ASGI routes (GET verify + POST receive)
config.py                — add FB_PAGE_ACCESS_TOKEN, FB_VERIFY_TOKEN, FB_APP_SECRET, OWNER_TELEGRAM_USER_ID
bot/main.py              — mount Messenger ASGI app alongside Telegram
.env.example             — document new env vars
Dockerfile               — add bot/messenger/ to COPY
requirements.txt         — add httpx, starlette
tests/test_messenger_renderer.py
tests/test_messenger_sender.py
tests/test_messenger_handler.py
tests/test_messenger_handoff.py
tests/test_messenger_webhook.py
```

---

### Task 1: Dependencies and Config

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py` (if exists, else skip)

- [ ] **Step 1: Add dependencies to requirements.txt**

Add these two lines to `requirements.txt`:

```
httpx>=0.27.0
starlette>=0.37.0
```

- [ ] **Step 2: Install dependencies**

Run: `.venv/bin/pip install -r requirements.txt`
Expected: Successfully installed httpx and starlette

- [ ] **Step 3: Add Messenger config fields to Config dataclass**

In `config.py`, add four new fields to the `Config` dataclass after `mode`:

```python
@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    openai_api_key: str
    openweathermap_api_key: str
    toyyibpay_api_key: str
    toyyibpay_category_code: str
    toyyibpay_base_url: str
    webhook_url: str
    webhook_secret: str
    port: int
    mode: str
    fb_page_access_token: str
    fb_verify_token: str
    fb_app_secret: str
    owner_telegram_user_id: str

    @property
    def is_production(self) -> bool:
        return self.mode == "production"

    @property
    def messenger_enabled(self) -> bool:
        return bool(self.fb_page_access_token and self.fb_verify_token)
```

In `load_config()`, add:

```python
        fb_page_access_token=_optional("FB_PAGE_ACCESS_TOKEN"),
        fb_verify_token=_optional("FB_VERIFY_TOKEN"),
        fb_app_secret=_optional("FB_APP_SECRET"),
        owner_telegram_user_id=_optional("OWNER_TELEGRAM_USER_ID"),
```

- [ ] **Step 4: Update .env.example**

Append to `.env.example`:

```bash

# Facebook Messenger integration (optional — leave blank to disable).
FB_PAGE_ACCESS_TOKEN=
FB_VERIFY_TOKEN=
FB_APP_SECRET=

# Your personal Telegram user ID — receives handoff notifications from Messenger leads.
OWNER_TELEGRAM_USER_ID=
```

- [ ] **Step 5: Run existing tests**

Run: `.venv/bin/python -m pytest -q --tb=short`
Expected: 292 passed

- [ ] **Step 6: Commit**

```bash
git add requirements.txt config.py .env.example
git commit -m "feat(messenger): add config fields and dependencies for Messenger integration"
```

---

### Task 2: Messenger Renderer

**Files:**
- Create: `bot/messenger/__init__.py`
- Create: `bot/messenger/renderer.py`
- Test: `tests/test_messenger_renderer.py`

- [ ] **Step 1: Create the module init**

Create empty `bot/messenger/__init__.py`.

- [ ] **Step 2: Write failing tests for renderer**

Create `tests/test_messenger_renderer.py`:

```python
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
    # One quick reply per package + Talk to a Human
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
    assert len(replies) == 3  # 2 packages + Talk to Human
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_messenger_renderer.py -v`
Expected: FAIL — module not found

- [ ] **Step 4: Implement renderer**

Create `bot/messenger/renderer.py`:

```python
"""Format package data for Facebook Messenger quick-reply messages."""

from __future__ import annotations

from bot.models import Package

# Messenger quick reply titles are max 20 chars.
_LABEL_OVERRIDES: dict[str, str] = {
    "genting-batu-caves-daytrip": "Genting & Batu",
    "kl-city-daytrip-8hr": "KL Full Day",
    "genting-highlands-daytrip": "Genting Day Trip",
    "port-dickson-daytrip-private": "Port Dickson",
    "melaka-daytrip-private": "Melaka Day Trip",
    "ipoh-2d1n-premium": "Ipoh 2D1N",
}

QuickReply = dict[str, str]

MENU_QUICK_REPLIES: list[QuickReply] = [
    {"title": "View Packages", "payload": "VIEW_PACKAGES"},
    {"title": "Get Pricing", "payload": "GET_PRICING"},
    {"title": "Talk to a Human", "payload": "TALK_TO_HUMAN"},
]

_TALK_TO_HUMAN_QR: QuickReply = {"title": "Talk to a Human", "payload": "TALK_TO_HUMAN"}


def _short_label(pkg: Package) -> str:
    label = _LABEL_OVERRIDES.get(pkg.id, pkg.name)
    return label[:20]


def _duration_label(minutes: int) -> str:
    if minutes >= 1440:
        days = minutes // 1440
        return f"{days} day{'s' if days > 1 else ''}"
    hours = minutes // 60
    return f"{hours} hour{'s' if hours != 1 else ''}"


def render_welcome() -> tuple[str, list[QuickReply]]:
    text = (
        "Hi! I'm LocalLens — we run curated day trips and experiences from KL.\n\n"
        "How can I help?"
    )
    return text, list(MENU_QUICK_REPLIES)


def render_package_list(packages: list[Package]) -> tuple[str, list[QuickReply]]:
    premium = [p for p in packages if p.tier == "premium"]
    lines = ["Here are our trips:\n"]
    for i, pkg in enumerate(premium, 1):
        price = f"RM{pkg.price_rm}" if pkg.price_rm else "Free"
        lines.append(f"{i}. {pkg.name} — {price} (4 pax)")
    lines.append("\nTap a package for full details.")
    text = "\n".join(lines)
    replies: list[QuickReply] = [
        {"title": _short_label(pkg), "payload": f"PKG:{pkg.id}"}
        for pkg in premium
    ]
    replies.append(_TALK_TO_HUMAN_QR)
    return text, replies


def render_package_detail(pkg: Package) -> tuple[str, list[QuickReply]]:
    duration = _duration_label(pkg.duration_minutes)
    audience = ", ".join(pkg.audience_tags) if pkg.audience_tags else "everyone"
    # Condensed step summary — place names only, no insider tips.
    places = ", ".join(s.place_name for s in pkg.steps if "Pickup" not in s.place_name and "Drop-off" not in s.place_name)

    lines = [
        f"{pkg.name}",
        f"Duration: {duration} | For: {audience}",
        "",
        places,
    ]
    if pkg.inclusions:
        lines.append("")
        lines.append("Included:")
        for item in pkg.inclusions:
            lines.append(f"- {item}")
    lines.append("")
    if pkg.price_rm:
        lines.append(f"RM{pkg.price_rm} for 4 pax")
    replies: list[QuickReply] = [
        {"title": "Book This", "payload": f"BOOK:{pkg.id}"},
        {"title": "Ask a Question", "payload": f"ASK_QUESTION:{pkg.id}"},
        {"title": "Back to Packages", "payload": "BACK_TO_PACKAGES"},
    ]
    return "\n".join(lines), replies


def render_pricing_table(packages: list[Package]) -> tuple[str, list[QuickReply]]:
    premium = [p for p in packages if p.tier == "premium"]
    lines = ["Our packages (all prices for 4 pax):\n"]
    for pkg in premium:
        price = f"RM{pkg.price_rm}" if pkg.price_rm else "Free"
        lines.append(f"{pkg.name} — {price}")
    lines.append("\nTap a package for full details.")
    text = "\n".join(lines)
    replies: list[QuickReply] = [
        {"title": _short_label(pkg), "payload": f"PKG:{pkg.id}"}
        for pkg in premium
    ]
    replies.append(_TALK_TO_HUMAN_QR)
    return text, replies
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_messenger_renderer.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add bot/messenger/__init__.py bot/messenger/renderer.py tests/test_messenger_renderer.py
git commit -m "feat(messenger): package renderer with quick replies"
```

---

### Task 3: Messenger Sender

**Files:**
- Create: `bot/messenger/sender.py`
- Test: `tests/test_messenger_sender.py`

- [ ] **Step 1: Write failing tests for sender**

Create `tests/test_messenger_sender.py`:

```python
"""Tests for bot.messenger.sender — Facebook Send API wrapper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_messenger_sender.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Add pytest-asyncio to requirements**

Add to `requirements.txt`:

```
pytest-asyncio>=0.23.0
```

Run: `.venv/bin/pip install -r requirements.txt`

- [ ] **Step 4: Implement sender**

Create `bot/messenger/sender.py`:

```python
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
        response.raise_for_status()
        return response.json()
    finally:
        if should_close:
            await client.aclose()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_messenger_sender.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add bot/messenger/sender.py tests/test_messenger_sender.py requirements.txt
git commit -m "feat(messenger): Send API wrapper with quick reply support"
```

---

### Task 4: Messenger Handler

**Files:**
- Create: `bot/messenger/handler.py`
- Test: `tests/test_messenger_handler.py`

- [ ] **Step 1: Write failing tests for handler**

Create `tests/test_messenger_handler.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_messenger_handler.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement handler**

Create `bot/messenger/handler.py`:

```python
"""Route incoming Messenger events to actions."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    kind: str  # welcome, package_list, pricing_table, package_detail, handoff
    sender_id: str
    package_id: str | None = None


_GREETINGS = re.compile(r"^(hi|hello|hey|assalamualaikum|salam)\b", re.IGNORECASE)
_PRICE_KEYWORDS = re.compile(r"(price|cost|how much|berapa|harga)", re.IGNORECASE)
_PACKAGE_KEYWORDS = re.compile(r"(package|trip|tour|itinerary|plan)", re.IGNORECASE)


def route_event(event: dict) -> Action:
    sender_id = event["sender_id"]
    event_type = event.get("type")
    payload = event.get("payload", "")

    # Postbacks (e.g. Get Started button).
    if event_type == "postback":
        if payload == "GET_STARTED":
            return Action(kind="welcome", sender_id=sender_id)
        return Action(kind="handoff", sender_id=sender_id)

    # Quick reply taps.
    if event_type == "quick_reply":
        if payload == "VIEW_PACKAGES":
            return Action(kind="package_list", sender_id=sender_id)
        if payload == "GET_PRICING":
            return Action(kind="pricing_table", sender_id=sender_id)
        if payload == "TALK_TO_HUMAN":
            return Action(kind="handoff", sender_id=sender_id)
        if payload == "BACK_TO_PACKAGES":
            return Action(kind="package_list", sender_id=sender_id)
        if payload.startswith("PKG:"):
            pkg_id = payload.split(":", 1)[1]
            return Action(kind="package_detail", sender_id=sender_id, package_id=pkg_id)
        if payload.startswith("BOOK:") or payload.startswith("ASK_QUESTION:"):
            pkg_id = payload.split(":", 1)[1]
            return Action(kind="handoff", sender_id=sender_id, package_id=pkg_id)
        return Action(kind="handoff", sender_id=sender_id)

    # Freeform text — keyword matching.
    if event_type == "text":
        text = event.get("text", "")
        if _GREETINGS.search(text):
            return Action(kind="welcome", sender_id=sender_id)
        if _PRICE_KEYWORDS.search(text):
            return Action(kind="pricing_table", sender_id=sender_id)
        if _PACKAGE_KEYWORDS.search(text):
            return Action(kind="package_list", sender_id=sender_id)
        return Action(kind="handoff", sender_id=sender_id)

    return Action(kind="handoff", sender_id=sender_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_messenger_handler.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add bot/messenger/handler.py tests/test_messenger_handler.py
git commit -m "feat(messenger): event router with keyword matching"
```

---

### Task 5: Handoff (Telegram notification + Messenger reply)

**Files:**
- Create: `bot/messenger/handoff.py`
- Test: `tests/test_messenger_handoff.py`

- [ ] **Step 1: Write failing tests for handoff**

Create `tests/test_messenger_handoff.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_messenger_handoff.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement handoff**

Create `bot/messenger/handoff.py`:

```python
"""Handoff: notify the business owner via Telegram and reply to the customer."""

from __future__ import annotations


def format_owner_notification(
    *,
    customer_name: str,
    package_name: str | None,
    price_rm: int | None,
    sender_id: str,
) -> str:
    lines = ["New lead from Messenger:", f"Name: {customer_name}"]
    if package_name:
        price_str = f"RM{price_rm}" if price_rm else "N/A"
        lines.append(f"Interested in: {package_name} ({price_str})")
    else:
        lines.append("General inquiry — no specific package selected.")
    lines.append(f"Messenger ID: {sender_id}")
    lines.append("\nReply to them on Messenger.")
    return "\n".join(lines)


def format_customer_reply() -> str:
    return (
        "Great choice! Let me connect you with our team — "
        "they'll reply shortly."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_messenger_handoff.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add bot/messenger/handoff.py tests/test_messenger_handoff.py
git commit -m "feat(messenger): handoff notification formatter"
```

---

### Task 6: Webhook (Starlette ASGI routes)

**Files:**
- Create: `bot/messenger/webhook.py`
- Test: `tests/test_messenger_webhook.py`

- [ ] **Step 1: Write failing tests for webhook**

Create `tests/test_messenger_webhook.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_messenger_webhook.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement webhook**

Create `bot/messenger/webhook.py`:

```python
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
from bot.messenger.handler import Action, route_event
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
        # Reply to customer.
        customer_reply = format_customer_reply()
        msg = build_text_message(action.sender_id, customer_reply)
        await send_message(msg, page_token=page_token, client=client)

        # Notify owner via Telegram.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_messenger_webhook.py -v`
Expected: All pass

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/python -m pytest -q --tb=short`
Expected: All pass (292 existing + new messenger tests)

- [ ] **Step 6: Commit**

```bash
git add bot/messenger/webhook.py tests/test_messenger_webhook.py
git commit -m "feat(messenger): webhook with signature verification and event processing"
```

---

### Task 7: Mount Messenger App in Main Entry Point

**Files:**
- Modify: `bot/main.py`
- Modify: `Dockerfile`

- [ ] **Step 1: Update bot/main.py to mount Messenger ASGI app**

Add the Messenger app mounting after the Telegram app is built. Add this import at the top of `bot/main.py`:

```python
from bot.messenger.webhook import create_messenger_app
```

Add a new function after `_build_payment_provider`:

```python
def _start_messenger_server(config: Config, telegram_bot: Any) -> None:
    """Start the Messenger webhook server in a background thread if configured."""
    if not config.messenger_enabled:
        logger.info(
            "FB_PAGE_ACCESS_TOKEN / FB_VERIFY_TOKEN not set — "
            "Messenger integration disabled."
        )
        return
    import threading
    import uvicorn

    messenger_app = create_messenger_app(
        page_token=config.fb_page_access_token,
        verify_token=config.fb_verify_token,
        app_secret=config.fb_app_secret,
        owner_telegram_id=config.owner_telegram_user_id,
        telegram_bot=telegram_bot,
    )
    messenger_port = config.port + 1  # Telegram uses 8080, Messenger uses 8081.

    def run() -> None:
        uvicorn.run(messenger_app, host="0.0.0.0", port=messenger_port, log_level="info")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logger.info("Messenger webhook started on 0.0.0.0:%d/messenger", messenger_port)
```

Update the `_post_init` function to start Messenger after Telegram is ready:

```python
async def _post_init(app: Application) -> None:
    """Cache bot identity + start the follow-up scheduler + start Messenger."""
    me = await app.bot.get_me()
    app.bot_data["bot_username"] = me.username or ""

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_follow_up_tick,
        trigger=IntervalTrigger(minutes=FOLLOW_UP_INTERVAL_MINUTES),
        kwargs={"app": app},
        id="follow_up_tick",
        replace_existing=True,
    )
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    logger.info(
        "Follow-up scheduler started (every %d min).", FOLLOW_UP_INTERVAL_MINUTES
    )

    # Start Messenger webhook if configured.
    config = load_config()
    _start_messenger_server(config, app.bot)
```

Add import at the top:

```python
from typing import Any
```

- [ ] **Step 2: Add uvicorn to requirements.txt**

Add to `requirements.txt`:

```
uvicorn>=0.29.0
```

Run: `.venv/bin/pip install -r requirements.txt`

- [ ] **Step 3: Update Dockerfile to copy messenger module**

In `Dockerfile`, the existing `COPY bot/ ./bot/` already copies all subdirectories including `bot/messenger/`. No change needed. Verify by reading the Dockerfile.

Also expose the Messenger port. Change:

```dockerfile
EXPOSE 8080
```

To:

```dockerfile
EXPOSE 8080 8081
```

- [ ] **Step 4: Update .env.example with port note**

Append to the Messenger section of `.env.example`:

```bash
# Messenger webhook runs on PORT+1 (default 8081).
```

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/python -m pytest -q --tb=short`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add bot/main.py requirements.txt Dockerfile .env.example
git commit -m "feat(messenger): mount webhook server alongside Telegram bot"
```

---

### Task 8: End-to-End Verification

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest -v --tb=short`
Expected: All tests pass (292 existing + ~25 new messenger tests)

- [ ] **Step 2: Verify local startup with Messenger disabled**

Run: `FB_PAGE_ACCESS_TOKEN= .venv/bin/python -c "from bot.messenger.webhook import create_messenger_app; print('import ok')"`
Expected: "import ok"

- [ ] **Step 3: Verify renderer output looks correct**

Run:
```bash
.venv/bin/python -c "
from bot.data_loader import load_packages
from bot.messenger.renderer import render_welcome, render_package_list, render_package_detail, render_pricing_table

pkgs = load_packages()
premium = [p for p in pkgs if p.tier == 'premium']

print('=== WELCOME ===')
text, _ = render_welcome()
print(text)

print('\n=== PACKAGE LIST ===')
text, replies = render_package_list(pkgs)
print(text)
print('Buttons:', [r['title'] for r in replies])

print('\n=== DETAIL (first premium) ===')
text, replies = render_package_detail(premium[0])
print(text)
print('Buttons:', [r['title'] for r in replies])

print('\n=== PRICING ===')
text, _ = render_pricing_table(pkgs)
print(text)
"
```

Expected: Nicely formatted welcome, package list, detail with inclusions, and pricing table.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(messenger): complete Messenger integration — lead capture bot with Telegram handoff"
```
