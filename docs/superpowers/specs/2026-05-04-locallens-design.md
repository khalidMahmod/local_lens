# LocalLens — Design Specification

## Overview

LocalLens is a Telegram-based AI travel assistant that helps travelers decide what to do right now. It combines local knowledge, real-time context awareness (location, weather, time), and curated micro-packages to deliver actionable plans — not just options.

**Core differentiator:** "Here's exactly what you should do — and you can follow this plan immediately."

**Target users:**
- Budget backpackers / solo travelers seeking authentic local experiences
- Mid-range tourists (couples, small groups) who want curated, hassle-free plans

**Launch market:** Kuala Lumpur (primary), with expansion to Putrajaya, Genting Highlands, and Melaka after validation.

---

## Monetization Model: Freemium + Post-Pay Premium

Two tiers of micro-packages:

- **Free packages** (5 starter plans): Build trust, demonstrate curation quality, drive organic sharing
- **Premium packages** (10+ plans, RM10–30): Deeper plans with hidden gems, exact timing, insider tips

**Payment model:** Post-experience with soft commitment.
1. Bot presents premium package with a stated price (e.g., RM15)
2. User agrees (soft commitment recorded)
3. Full plan delivered immediately
4. Bot follows up 2-3 hours later with payment link (DuitNow/ToyyibPay)
5. If user had a bad experience — collect feedback, no payment push

**Additional revenue levers:**
- Optional tipping ("Tip extra if you loved it")
- Referral loop ("Share with a friend — they get their first package free")

---

## System Architecture: Hybrid Smart Router

### Components

```
Telegram User
    ↕
Telegram Bot API (python-telegram-bot)
    ↓
┌─────────────────────────────────────────────────┐
│ SMART ROUTER (Python Core)                      │
│                                                 │
│  Context Extractor  │ Package Matcher │ Convo   │
│  - Location         │ - Location prox │ Manager │
│  - Time available   │ - Duration fit  │ - State │
│  - Intent           │ - Intent score  │ - Upsell│
│  - Weather (live)   │ - Weather score │ - Pay   │
│  - Time of day      │ - Top 1-3 hits  │ - Sesh  │
└─────────────────────────────────────────────────┘
    ↕               ↕               ↕
Claude API    OpenWeatherMap    Data Layer (JSON)
```

### Request Flow

1. User sends message or shares location via Telegram
2. **Context Extractor** parses location, time, intent, conditions; fetches weather from OpenWeatherMap
3. **Package Matcher** filters/scores curated packages against context (location proximity, duration fit, intent overlap, weather compatibility)
4. **Decision point:**
   - Strong match → send matched package(s) + context to Claude for presentation
   - No match → send context + location data to Claude for free recommendations
5. **Claude** generates natural, opinionated response
6. Bot sends response to user via Telegram
7. If package accepted → Conversation Manager tracks state → delivers full plan → schedules payment follow-up

### Weather Integration

- **API:** OpenWeatherMap (free tier, 1,000 calls/day)
- **Data:** Current conditions + 3-hour forecast via lat/long from Telegram location
- **Impact:** Package Matcher uses weather-aware scoring. Each package has weather tags:
  - `ideal`: conditions where the package shines
  - `ok`: acceptable conditions
  - `avoid`: conditions where the package shouldn't be suggested
- **UX benefit:** Bot proactively adapts — "Rain's expected soon — I've planned this mostly indoors"

### Meal-Time Restaurant Suggestions

Every response — free recommendations, free packages, and premium packages — **always** includes 1–2 nearby restaurant/food suggestions matched to the current time of day. The traveler's next meal is never more than one tap away.

**Time-of-day windows (local KL time):**

| Window | Hours | Suggestion type |
|--------|-------|-----------------|
| `breakfast` | 07:00 – 10:30 | Local breakfast spots (nasi lemak, dim sum, kopitiam) |
| `lunch` | 11:30 – 14:30 | Full lunch spots (hawker, casual sit-down) |
| `afternoon_snack` | 15:00 – 17:30 | Cafes, kuih stalls, teh tarik / cendol spots |
| `dinner` | 18:30 – 22:00 | Dinner spots (street food, restaurants) |
| `late_night` | 22:00 – 02:00 | Mamak, supper spots |
| `between` | other | Skip food add-on; suggest a drink/coffee spot only if user asks |

**Selection rules:**
- Filter restaurants by current time-of-day window AND proximity to user (or to the package's `location_center` if a package is being suggested).
- **Halal filter (when user is Muslim):** restrict to `halal_certified` and `muslim_friendly` only. Never suggest `non_halal` or `unknown`. Prefer `halal_certified` first.
- Prefer restaurants whose `meal_tags` include the current window. Fall back to the next-closest window if nothing nearby fits.
- Max 2 suggestions, ranked by proximity + curation score.
- Match the user's intent vibe (e.g., budget backpacker → hawker, not hotel restaurant).
- Weather-aware: if it's raining, prefer indoor/covered spots.
- If a premium package already includes a meal stop in the current window, **skip** the add-on — don't double up.

**Detecting Muslim users:**
- **Explicit:** Onboarding asks a single soft question after location is shared — "Quick one — should I stick to halal food spots? `[Halal only] [No preference]`". Stored on the session as `dietary.halal_only: true | false`.
- **Implicit signals (only used if onboarding skipped):** name with strong Muslim association, message language (Bahasa Malaysia/Arabic phrases like "halal ke?"), explicit mention ("I'm Muslim", "halal please"). Implicit detection sets `dietary.halal_only: true` but the bot confirms inline on first food suggestion: "Sticking to halal spots — let me know if that's not needed."
- Preference persists for the session and is editable any time via "/diet" command.

**UX format:** Append a short "Hungry? / Snack time? / Dinner nearby?" line at the end of the response with 1–2 picks + Google Maps link each. Keep it tight — never let the food add-on dominate the main answer.

---

## Data Model

### Package (packages.json)

```json
{
  "id": "klcc-chill-2hr",
  "name": "2-Hour KLCC Chill Plan",
  "tier": "free | premium",
  "price_rm": null,
  "duration_minutes": 120,
  "location_center": { "lat": 3.1578, "lng": 101.7117, "name": "KLCC" },
  "radius_km": 1.5,
  "intent_tags": ["chill", "explore"],
  "weather_tags": {
    "ideal": ["clear", "clouds"],
    "ok": ["drizzle"],
    "avoid": ["rain", "thunderstorm"]
  },
  "indoor_percentage": 40,
  "time_of_day": ["morning", "afternoon"],
  "steps": [
    {
      "order": 1,
      "place_name": "KLCC Park",
      "place_location": { "lat": 3.1565, "lng": 101.7124 },
      "duration_minutes": 45,
      "description": "Walk through the park — head to the lake side for the best Petronas view with fewer people",
      "insider_tip": "Enter from the Traders Hotel side, not the main Suria entrance — much quieter",
      "google_maps_link": "https://maps.app.goo.gl/..."
    }
  ],
  "why_it_works": "Minimal walking, weather-safe with indoor options, efficient use of time",
  "upsells": ["coffee recommendation", "dinner add-on"]
}
```

### Location (locations.json)

```json
{
  "id": "klcc-park",
  "name": "KLCC Park",
  "lat": 3.1565,
  "lng": 101.7124,
  "area": "KLCC",
  "type": "park",
  "tags": ["scenic", "free", "family-friendly"],
  "best_time": ["morning", "evening"],
  "avg_time_minutes": 45
}
```

### Restaurant (restaurants.json)

```json
{
  "id": "lot10-hutong-hokkien-mee",
  "name": "Kim Lian Kee — Lot 10 Hutong",
  "lat": 3.1466,
  "lng": 101.7106,
  "area": "Bukit Bintang",
  "cuisine": "Chinese / Hokkien",
  "price_tier": "$",
  "meal_tags": ["lunch", "dinner"],
  "indoor": true,
  "vibe_tags": ["hawker", "iconic", "quick"],
  "halal_status": "non_halal",
  "insider_tip": "Order the Hokkien mee — the original stall, lard-fried wok hei is unbeatable",
  "google_maps_link": "https://maps.app.goo.gl/..."
}
```

**`halal_status` values:**
- `halal_certified` — JAKIM-certified or equivalent official certification
- `muslim_friendly` — no pork/alcohol but no formal cert (e.g., Indian veg, most Malay warungs)
- `non_halal` — serves pork and/or alcohol
- `unknown` — not yet verified; **never** suggested to Muslim users

### Session (sessions/{telegram_user_id}.json)

```json
{
  "telegram_user_id": "123456789",
  "current_state": "chatting",
  "location": { "lat": 3.1478, "lng": 101.7100 },
  "dietary": { "halal_only": false, "source": "asked" },
  "active_package_id": null,
  "commitment_price": null,
  "accepted_at": null,
  "follow_up_at": null,
  "history": []
}
```

`dietary.source` is one of `asked` (user answered onboarding), `inferred` (implicit signal), or `default` (not yet asked).

**Session states:** `new` → `location_set` → `chatting` → `package_offered` → `accepted` → `follow_up_pending` → `paid`

---

## Conversation Flow

### First-Time User

1. **NEW** — User sends /start → Bot: "Hey! I'm LocalLens — I help you find the best things to do right now. Share your location and I'll get started."
2. **LOCATION SET** — User shares location → Bot confirms area + weather, asks dietary preference: "Quick one — should I stick to halal food spots? `[Halal only] [No preference]`", then offers quick intent buttons: `[Chill] [Food] [Explore] [Surprise me]`
3. **CONTEXT READY** — Smart Router decides path:

### Path A: Free Recommendations (no package match)

Bot gives 2-3 opinionated, actionable suggestions via Claude. If a free package exists for the area/intent, suggest it naturally at the end. **Always append** the meal-time food add-on (1–2 nearby picks for the current window).

### Path B: Package Suggestion (match found)

**Free package:** Deliver full plan immediately — "I've got a ready-made plan for this. Want me to walk you through it?" Append the meal-time food add-on if the package doesn't already cover that window.

**Premium package — the tease:**
- Show 3-step outline (what, not where exactly)
- Withhold details (exact spots, insider tips, timing)
- State price + post-pay framing: "RM15 — you only pay after if it was worth it"
- Ask: "Want the full plan?"

### After Package Accepted

- Record soft commitment (price + timestamp)
- Deliver full premium plan with all details: exact locations, timing, insider tips, Google Maps links
- "Enjoy! I'll check in with you in a couple of hours."
- Set follow-up timer

### Follow-Up (2-3 hours later)

- "How was the plan? Did you enjoy it?"
- **Positive:** Payment link + tip option + referral invite
- **Negative:** Collect feedback, no payment push

---

## Bot Personality

**Persona:** A knowledgeable local friend who's lived in Malaysia for years. Not a tour guide, not a chatbot — a friend who knows the country.

**Voice principles:**
- **Opinionated** — "Go to stall #23, skip the rest" not "Here are 10 options"
- **Concise** — 5-10 lines max. Travelers are on their phone, probably walking.
- **Action-first** — Lead with what to do, explain why after
- **Warm but not cheesy** — Natural, helpful tone. No "Hey there, fellow adventurer!"
- **Context-aware** — Reference weather, time, location naturally

**Response rules:**
- Max 3 recommendations for free suggestions
- Numbered steps for packages
- Google Maps links on their own line (easy to tap)
- No walls of text — use line breaks generously
- Emoji sparingly — one or two max
- **Always close with a meal-time food add-on** (1–2 nearby picks) matched to the current time window — lunch, afternoon snack, or dinner. Skip only if the package already covers that meal, or if the time falls outside meal windows.

---

## Technical Implementation

### Project Structure

```
local_lens/
├── bot/
│   ├── __init__.py
│   ├── main.py              — entry point, Telegram bot setup
│   ├── handlers.py          — message & command handlers
│   ├── context_extractor.py — parse location, time, intent from input
│   ├── package_matcher.py   — score & filter packages against context
│   ├── conversation.py      — state machine, session management
│   ├── claude_client.py     — Claude API wrapper, system prompt
│   ├── weather.py           — OpenWeatherMap API client
│   └── follow_up.py         — scheduled payment follow-up logic
├── data/
│   ├── packages.json        — curated micro-packages
│   ├── locations.json       — places with metadata
│   ├── restaurants.json     — curated food spots tagged by meal window
│   └── sessions/            — per-user session files
├── ingest/
│   ├── __init__.py
│   ├── cli.py               — entry points (add-url, run-source, export)
│   ├── collectors/
│   │   ├── web.py           — blog / article scraper (BeautifulSoup + RSS)
│   │   ├── youtube.py       — yt-dlp wrapper for Shorts + reviews
│   │   ├── instagram.py     — yt-dlp for Reels; Apify for hashtag fanout
│   │   └── facebook.py      — Apify-based Page / group scraper
│   ├── extractor.py         — vision-aware Claude extraction → Candidate dict
│   ├── airtable_writer.py   — pushes Candidates to Airtable working surface
│   └── exporter.py          — pulls verified rows → writes data/*.json
├── prompts/
│   ├── system_prompt.txt    — Claude system prompt with personality & rules
│   └── extraction_prompt.txt — Candidate-extraction prompt for ingestion
├── config.py                — API keys, bot token, settings
├── requirements.txt
└── README.md
```

### Key Modules

- **handlers.py** — routes Telegram events (/start, shared location, text, button callbacks). Thin delegation layer.
- **context_extractor.py** — produces structured context: `{location, area, intent, time_available, weather, time_of_day}`. Uses Claude Haiku for intent extraction from vague messages (cheap, fast). Falls back to keyword matching for clear intents like button taps.
- **package_matcher.py** — scores packages on: location proximity (haversine), duration fit, intent overlap, weather compatibility. Returns ranked candidates with confidence threshold.
- **restaurant_picker.py** — given user location, current time, weather, and `dietary.halal_only`, returns 1–2 nearby restaurants matching the active meal window. Applies halal filter when set. Skips automatically if a suggested package already covers the current meal window.
- **conversation.py** — manages state machine, persists to `sessions/` as JSON per user.
- **claude_client.py** — wraps Anthropic SDK. Two model tiers: Haiku for context extraction (fast, cheap), Sonnet for user-facing responses (quality). System prompt defines personality. Receives context + matched packages, generates response. Keeps last 5 messages as history.
- **weather.py** — fetches current weather + 3-hour forecast from OpenWeatherMap by lat/long.
- **follow_up.py** — checks sessions for accepted packages where enough time has passed, sends follow-up. Runs on APScheduler.

### Dependencies

**Bot runtime:**
- `python-telegram-bot` — Telegram integration
- `anthropic` — Claude API (vision-capable for ingestion)
- `requests` — weather API calls
- `APScheduler` — timed follow-ups

**Ingestion pipeline:**
- `yt-dlp` — downloads Instagram Reels, TikTok, YouTube Shorts (caption + media)
- `beautifulsoup4` + `feedparser` — web blog / RSS scraping
- `apify-client` — hashtag-driven IG / Facebook scraping at scale
- `pyairtable` — read/write Candidates working surface
- `ffmpeg` (system) — video frame extraction for vision analysis

### Deployment (MVP — free tier)

The MVP runs entirely on free-tier infrastructure. No paid hosting until product-market fit is proven.

**Primary host: Fly.io free allowance**
- 3 × `shared-cpu-1x` 256MB VMs free (use 1 for the bot, leaves headroom)
- 3GB persistent volume free — holds `data/*.json`, sessions, and source archive
- Always-on (no cold starts that affect Telegram webhook latency)
- HTTPS endpoint provided automatically — required for Telegram webhooks
- Single `Dockerfile` deploy; `fly.toml` defines the volume mount

**Alternative: Oracle Cloud Always Free**
- ARM Ampere A1 instance: up to 4 OCPUs / 24GB RAM total, 200GB block storage — forever free
- More setup overhead than Fly.io but no resource ceiling for the MVP
- Use this if Fly.io's 256MB RAM proves tight (e.g., yt-dlp + ffmpeg ingestion runs)

**Avoid for now:**
- Render free tier — spins down after 15min idle; first webhook after sleep adds 30–60s cold-start lag, which kills the "right now" UX
- Railway — no longer has a true free tier (hobby plan is $5/mo)
- Vercel / Netlify Functions — APScheduler can't run; would require re-architecting follow-ups
- Cloudflare Workers — Python support too limited for the bot stack

**Storage (free):**
- JSON files on Fly.io persistent volume (or Oracle block storage)
- Airtable free tier for Candidates working surface (1,200 records/base — plenty for MVP)
- Source media archive: Cloudflare R2 free tier (10GB) when the volume gets tight; until then, local disk

**Cron / follow-ups:**
- APScheduler runs in-process on the always-on Fly.io / Oracle VM — no external cron needed
- If forced onto serverless later, switch to [cron-job.org](https://cron-job.org) (free) hitting a `/tick` endpoint every 5min

**Ingestion runs:**
- Manual `ingest add-url` runs from the same VM (or your laptop) — no extra infra
- Weekly `ingest run-all` cron triggered by APScheduler on the same VM

**Other free pieces:**
- Telegram Bot API: free
- OpenWeatherMap: free (1,000 calls/day, well within MVP envelope)
- ToyyibPay: free to integrate; takes per-transaction fee on actual payments only
- Webhook HTTPS cert: free via Fly.io / Oracle (Let's Encrypt)
- Logs / monitoring: Fly.io built-in logs free; UptimeRobot free tier for uptime checks

**Environment variables:** API keys (Anthropic, Telegram, OpenWeatherMap, Apify, Airtable) loaded from `fly secrets` or `.env` (gitignored). Never committed.

### Cost per Interaction (MVP)

- Claude API: ~$0.01–0.03 per turn (Haiku for extraction, Sonnet for responses) — **only real cost**
- Weather API: free (within 1,000/day)
- Hosting: **$0** (Fly.io free tier)
- Storage: **$0** (Airtable free + 3GB Fly volume)
- Break-even: ~6–8 paid packages/month at RM15 average (just covers Claude API)

**Upgrade triggers (move off free tier when):**
- Active users exceed ~200/day (Fly free RAM gets tight)
- Source archive exceeds 3GB (Fly volume cap)
- Ingestion runs need consistent ffmpeg + yt-dlp throughput (move to Oracle ARM or paid Fly tier)
- Airtable Candidates table approaches 1,200 records (upgrade to Airtable Plus or migrate to Postgres)

---

## Knowledge Base Ingestion

The curation moat (restaurants, locations, packages) is built and maintained by an ingestion pipeline that pulls candidate data from the web and social platforms, extracts structured info via Claude, and stages it for human verification before promotion.

### Sources

| Source | Discovery method | Tooling |
|---|---|---|
| **Web** (blogs, articles) | RSS feeds + targeted scraping of curator blogs (KY Eats, Eat Drink KL, MalaysianFlavours) | `feedparser` + `BeautifulSoup` |
| **YouTube** (Shorts, reviews) | yt-dlp on channels and search queries | `yt-dlp` |
| **Instagram** (Reels) | Manual URL collection (default); Apify hashtag scraper at scale | `yt-dlp` for Reel download; Apify for hashtag fanout |
| **Facebook** (Pages, food groups) | Apify Page / group scraper | `apify-client` |


### Pipeline

```
[Sources: web, YouTube, IG, FB, TikTok]
    ↓
[Collectors]   ── per-source modules: collect(query) → list[RawItem]
    ↓
[Extractor]    ── downloads media, extracts video frames (ffmpeg),
                  sends frames + caption to Claude (vision) →
                  structured Candidate JSON
    ↓
[Candidates]   ── Airtable "Candidates" table (working surface)
    ↓
[Human verify] ── in-person visit, halal check (JAKIM), photo capture
    ↓
[Promotion]    ── status="live" rows exported to data/*.json
    ↓
[Bot runtime]  ── reads JSON files
```

### Candidate schema (extractor output)

```json
{
  "source_url": "https://www.instagram.com/reel/...",
  "source_platform": "instagram",
  "scraped_at": "2026-05-04T10:30:00+08:00",
  "stall_name": "Restoran Win Heng Seng",
  "stall_name_confidence": "high | medium | low",
  "dish_featured": "Char kuey teow",
  "location_hint": "Jalan Imbi, KL",
  "google_maps_search_query": "Restoran Win Heng Seng Jalan Imbi",
  "halal_signals": "no_pork_visible | pork_visible | unclear",
  "viral_hook": "Wok hei shot at 0:08, queue out the door",
  "claimed_must_order": "Char kuey teow with extra duck egg",
  "operating_hours_mentioned": "Closes 1pm",
  "candidate_quality_score": 8,
  "needs_human_review": false,
  "notes_for_verification": "Caption inconsistent on stall name"
}
```

### Storage layers

| Layer | Format | Purpose |
|---|---|---|
| Working candidates | Airtable "Candidates" table | Mobile-friendly editing, photo attachments, triage workflow |
| Verified knowledge base | JSON files in `data/` | What the bot reads at runtime — keeps MVP infra simple |
| Source archive | Local disk (later S3) | Raw downloaded media + scrape timestamps for audit |

### CLI interface

```
ingest add-url <url>            # one-off: process a single URL end-to-end
ingest run-source <source>      # batch: run a collector + extractor for one source
ingest run-all                  # cron entry point: all sources
ingest export                   # promote Airtable status=live rows → data/*.json
ingest reverify --older-than 90d  # flag stale entries for re-verification
```

### Verification gate (Candidate → Live)

A Candidate is **never** read by the bot until:
1. Visited in person within 90 days
2. Photo captured of dish + storefront
3. Operating hours + days closed confirmed on-site
4. Halal status verified (JAKIM lookup for `halal_certified`; on-site observation for `muslim_friendly`)
5. Insider tip captured (the differentiator that makes the recommendation viral)
6. Status flipped to `live` in Airtable
7. `ingest export` run to refresh `data/*.json`

### Compliance & risk

- **ToS:** Instagram and Facebook scraping violates platform ToS. Use Apify for hashtag-driven discovery so legal risk sits with them, not the bot infrastructure. Manual URL collection (Route A) carries no ToS risk.
- **Republishing:** Source media is research input only. The bot describes places in its own words; never embed or rehost source content.
- **Caption claims:** All scraped claims (e.g., "best in KL", "halal") are unverified until physical verification. Halal status is **always** double-checked via JAKIM regardless of caption claim.
- **Rate limits:** Throttle to ≤1 request per source per minute when scraping from bot infrastructure. Apify handles its own rate management.
- **Source attribution:** `source_url` and `scraped_at` are mandatory on every Candidate so a recommendation can be traced back if challenged.

### Update cadence

- Manual URL ingestion: continuous (you / staff browse and submit)
- Automated source runs: weekly cron (`ingest run-all`)
- Verification visits: target 5–10 promotions per week
- Re-verification cycle: 90 days per active entry
- JSON export: before every deploy, plus daily cron after verification visits

---

## MVP Scope

### In Scope

- Telegram bot with location-first onboarding
- 5 free + 10 premium packages (KL area)
- 20+ curated KL restaurants tagged by meal window (lunch / afternoon snack / dinner) and halal status (halal_certified / muslim_friendly / non_halal)
- Onboarding halal preference question + session-persisted dietary filter
- Context extraction (location, intent, weather, time)
- Package matching with weather-aware scoring
- Meal-time-aware restaurant add-on appended to every response
- Free recommendations via Claude for non-matching queries
- Upsell flow with soft commitment
- Post-experience follow-up with DuitNow/ToyyibPay payment link
- Referral message
- Basic analytics (queries, offers, accepts, payments)
- **Ingestion pipeline (manual mode):** `ingest add-url` CLI for single-URL processing; web + YouTube + Instagram (URL-based) collectors; Claude vision extraction; Airtable Candidates surface; `ingest export` to JSON

### Out of Scope (v1)

- Putrajaya, Genting, Melaka packages (add after KL validated)
- Automated payment processing
- User accounts or preference memory
- Multi-language support
- Rating/review system
- Web or mobile app
- Full travel planning / multi-day itineraries
- **Automated ingestion at scale:** Apify hashtag scrapers, Facebook Page scraping, scheduled `run-all` cron — add in v2 once manual ingestion volume exceeds capacity

---

## Launch Plan

1. Build core bot (1-2 weeks)
2. Curate 15 packages for KL (parallel with build)
3. Test with 5-10 friends/travelers
4. Soft launch in KL travel Telegram groups / Reddit r/malaysia
5. Iterate based on feedback

---

## Success Metrics (First 30 Days)

| Metric | Target | Why |
|--------|--------|-----|
| Conversations started | 100+ | Are people finding the bot? |
| Location shared | 60%+ of users | Do they trust it? |
| Free package completed | 20+ | Do plans actually work? |
| Premium package accepted | 15+ | Will people commit? |
| Payment collected | 40%+ of accepts | Will they pay after? |
| Referral sent | 10+ | Organic growth signal |

---

## Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Low payment collection | Free packages build trust first; conversational follow-up; feedback from non-payers |
| Claude hallucinating locations | Package matcher feeds exact data — Claude presents, not invents. System prompt forbids making up places. |
| Not enough package variety | 15 KL packages covering: food/chill/explore × morning/afternoon/evening |
| Slow user acquisition | Seed in travel groups, Reddit, hostel QR codes, partner with KL hostels |
