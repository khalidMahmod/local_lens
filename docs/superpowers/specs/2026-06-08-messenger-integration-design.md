# Facebook Messenger Integration — Design Specification

## Overview

Add a Facebook Messenger bot that answers common package inquiries (listing, pricing, inclusions) from customers who click through from Facebook ads. The bot handles FAQ-style questions automatically and hands off to the business owner (via Telegram notification + Messenger message) when the customer is ready to book or has questions the bot can't answer.

**Primary use case:** Facebook ad → Messenger → automated package info → human handoff for booking.

**Not in scope:** Location sharing, LLM/OpenAI calls, payment flow, session persistence, onboarding flow. This is a stateless lead-capture bot, not a full travel assistant.

---

## Conversation Flow

```
Facebook Ad click → Messenger conversation opens
    │
    ▼
Bot sends welcome message + 3 quick-reply buttons:
    ├── [View Packages]
    │     └── Bot lists all packages (name, audience, duration, price)
    │           └── User taps a package name (quick reply)
    │                 └── Bot sends full detail: description, steps summary,
    │                     inclusions, price, audience tags
    │                       ├── [Book This] → Handoff
    │                       ├── [Ask a Question] → Handoff
    │                       └── [Back to Packages] → Package list again
    │
    ├── [Get Pricing]
    │     └── Bot sends pricing table (all packages, one line each)
    │           └── User taps a package name → Same detail flow above
    │
    └── [Talk to a Human]
          └── Immediate handoff
```

### Welcome Message

Triggered on any first message or "Get Started" postback:

> "Hi! I'm LocalLens — we run curated day trips and experiences from KL.
>
> How can I help?"
>
> Quick replies: **View Packages** | **Get Pricing** | **Talk to a Human**

### Package List

When user taps "View Packages":

> "Here are our trips:"
>
> 1. Genting Highlands & Batu Caves — RM320 (4 pax)
> 2. Best of KL Full Day — RM490 (4 pax)
> 3. Genting Highlands Day Trip — RM320 (4 pax)
> 4. Port Dickson Beach Day — RM780 (4 pax)
> 5. Melaka Heritage Day Trip — RM780 (4 pax)
> 6. Ipoh 2D1N Premium — RM1,690 (4 pax)
>
> "Tap a package for full details."
>
> Quick replies: one per package name + **Talk to a Human**

### Package Detail

When user taps a specific package:

> **Melaka Heritage Day Trip**
> Duration: 10 hours | For: family, friends, couples
>
> Private transport from your KL hotel to UNESCO Melaka — A Famosa, Jonker Street, river cruise, Floating Mosque, Menara taming sari, Heritage Walk, Portuguese Ship, The Stadthuys, Melaka Maritime Museum, beaches
>
> Included:
> - Private return transport (hotel pickup & drop-off)
>
> **RM780 for 4 pax**
>
> Quick replies: **Book This** | **Ask a Question** | **Back to Packages**

The detail view uses a condensed summary of the package steps (not the full step-by-step with insider tips — that's the premium value delivered after booking).

### Pricing Table

When user taps "Get Pricing":

> **Our packages (all prices for 4 pax):**
>
> Genting & Batu Caves — RM320
> Best of KL Full Day — RM490
> Genting Highlands — RM320
> Port Dickson (private transport) — RM780
> Melaka (private transport) — RM780
> Ipoh 2D1N Premium — RM1,690
>
> "Tap a package for full details."
>
> Quick replies: one per package name + **Talk to a Human**

### Handoff

Triggered by "Book This", "Ask a Question", "Talk to a Human", or unrecognized freeform text.

**To the customer (Messenger):**
> "Great choice! Let me connect you with our team — they'll reply shortly."

**To the business owner (Telegram DM):**
> "New lead from Messenger:
> Name: {user_first_name}
> Interested in: {package_name} ({price})
> Messenger ID: {sender_id}
>
> Reply to them on Messenger."

If no specific package context (e.g. "Talk to a Human" from the main menu):
> "New lead from Messenger:
> Name: {user_first_name}
> General inquiry — no specific package selected.
> Messenger ID: {sender_id}"

---

## Technical Architecture

### Messenger Platform API

- Uses the free Messenger Platform (Send/Receive API) on the business's Facebook Page
- No business verification required for bots on your own Page
- Webhook receives messages at `POST /messenger`
- Verify endpoint at `GET /messenger` (hub.verify_token challenge)
- Messages sent via `POST https://graph.facebook.com/v21.0/me/messages`

### Configuration (new env vars)

```
# Facebook Messenger (required for Messenger integration)
FB_PAGE_ACCESS_TOKEN=        # Page token from Facebook Developer Portal
FB_VERIFY_TOKEN=             # Random string for webhook verification
FB_APP_SECRET=               # App secret for request signature verification

# Handoff notification (existing bot, owner's Telegram user ID)
OWNER_TELEGRAM_USER_ID=      # Your personal Telegram user ID
```

### Project Structure

```
bot/
  messenger/
    __init__.py
    webhook.py          — FastAPI/Starlette routes: GET /messenger (verify), POST /messenger (receive)
    handler.py          — Message routing: postbacks, quick replies, freeform text → actions
    renderer.py         — Format package list, detail, pricing table for Messenger (plain text + quick replies)
    sender.py           — Send messages via Messenger Send API (text, quick replies, button templates)
    handoff.py          — Notify owner via Telegram bot + send "connecting you" message to customer
```

### Webhook Integration

The existing `bot/main.py` runs either polling (dev) or webhook (production) for Telegram. The Messenger webhook needs to coexist on the same Fly.io app.

**Approach:** Add the Messenger routes to the same ASGI app. In webhook mode, Telegram already uses `/telegram`. Messenger uses `/messenger`. In polling mode (dev), Messenger routes still work — useful for local testing with ngrok.

The Telegram `Application` object is available in `bot_data` for sending handoff notifications to the owner.

### Message Processing

Messenger sends these event types we care about:

1. **messaging_postbacks** — "Get Started" button, "Book This", etc.
2. **messages with quick_reply** — User tapped a quick reply button
3. **messages (text)** — Freeform text typed by user

Handler routing:

| Event | Payload | Action |
|-------|---------|--------|
| Postback: `GET_STARTED` | — | Send welcome + menu |
| Quick reply: `VIEW_PACKAGES` | — | Send package list |
| Quick reply: `GET_PRICING` | — | Send pricing table |
| Quick reply: `PKG:{package_id}` | package_id | Send package detail |
| Quick reply: `BOOK:{package_id}` | package_id | Handoff with package context |
| Quick reply: `ASK_QUESTION:{package_id}` | package_id | Handoff with package context |
| Quick reply: `BACK_TO_PACKAGES` | — | Send package list |
| Quick reply: `TALK_TO_HUMAN` | — | Handoff (no package context) |
| Freeform text | any | Attempt keyword match → handoff if no match |

### Keyword Matching (Freeform Text)

Simple keyword matching for common questions — no LLM needed:

- Contains "package" / "trip" / "tour" → Send package list
- Contains "price" / "cost" / "how much" / "berapa" → Send pricing table
- Contains a package keyword ("melaka", "ipoh", "genting", "port dickson", "pd", "kl") → Send that package's detail
- No match → Handoff to human

### Messenger API Constraints

- Quick replies: max 13 buttons per message (we have 6 packages + 1 "Talk to Human" = 7, within limit)
- Quick reply title: max 20 characters (package names need abbreviation in buttons)
- Message text: max 2000 characters (package details should fit)
- No inline keyboards — quick replies disappear after tap (this is fine for our flow)

### Button Label Abbreviations

Quick reply titles are capped at 20 chars. Abbreviated package labels:

| Package | Button Label |
|---------|-------------|
| Genting Highlands & Batu Caves | Genting & Batu |
| Best of KL Full Day | KL Full Day |
| Genting Highlands Day Trip | Genting Day Trip |
| Port Dickson Beach Day | Port Dickson |
| Melaka Heritage Day Trip | Melaka Day Trip |
| Ipoh 2D1N Premium | Ipoh 2D1N |

---

## Security

- Verify `X-Hub-Signature-256` header on all incoming webhooks using `FB_APP_SECRET`
- `FB_VERIFY_TOKEN` checked during webhook registration handshake
- Page access token stored as env var / Fly secret, never in code

---

## Testing Strategy

- **Unit tests** for `handler.py` (routing logic), `renderer.py` (message formatting), `handoff.py` (notification formatting)
- **Integration test** for `webhook.py` (signature verification, event parsing)
- All tests use fixtures — no Facebook API calls in tests
- Existing 292 tests remain untouched

---

## What's NOT Built

- No LLM/OpenAI calls — all responses are template-based from package data
- No location sharing or GPS features
- No payment processing — handoff to human for booking
- No session/state persistence — each interaction is stateless
- No onboarding flow (dietary, intent) — this is a sales bot, not a travel assistant
- No restaurant recommendations — packages only
