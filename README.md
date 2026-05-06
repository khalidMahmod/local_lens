# LocalLens

Telegram-based AI travel assistant for Kuala Lumpur. See [docs/superpowers/specs/2026-05-04-locallens-design.md](docs/superpowers/specs/2026-05-04-locallens-design.md) for the full design spec.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # fill in TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, OPENWEATHERMAP_API_KEY
python -m bot.main
```

The bot starts in long-polling mode (`LL_MODE=dev`). Send `/start` from Telegram and the onboarding flow will fire.

Run the tests:

```bash
python -m pytest
```

## Deploy to Fly.io

The bot runs on the Fly.io free tier: one always-on `shared-cpu-1x` 256MB VM with a 1GB persistent volume mounted at `/app/data` (sessions + analytics). HTTPS endpoint is provisioned automatically — required for the Telegram webhook.

### One-time setup

```bash
# 1. Create the Fly app (do NOT deploy yet — we need to set secrets first).
fly launch --no-deploy --copy-config --name locallens

# 2. Create the persistent volume in the same region as the app.
fly volumes create locallens_data --size 1 --region sin

# 3. Set secrets. WEBHOOK_URL is the public app URL printed by `fly launch`.
#    WEBHOOK_SECRET should be a random string (e.g. `openssl rand -hex 32`).
fly secrets set \
  TELEGRAM_BOT_TOKEN=... \
  OPENAI_API_KEY=... \
  OPENWEATHERMAP_API_KEY=... \
  TOYYIBPAY_API_KEY=... \
  TOYYIBPAY_CATEGORY_CODE=... \
  WEBHOOK_URL=https://locallens.fly.dev \
  WEBHOOK_SECRET=$(openssl rand -hex 32)

# 4. Deploy.
fly deploy
```

### Register the Telegram webhook

The bot sets the webhook itself on startup, but `scripts/set_webhook.sh` is also available for re-pointing without a redeploy:

```bash
# From your laptop with .env loaded:
set -a && source .env && set +a && bash scripts/set_webhook.sh

# Or from the deployed app:
fly ssh console -C "bash /app/scripts/set_webhook.sh"
```

### Smoke test

```bash
fly logs                       # watch for "Starting LocalLens in webhook mode"
# In Telegram: send /start to your bot — onboarding should fire.
```

### Optional: uptime monitoring

[UptimeRobot](https://uptimerobot.com)'s free tier can HTTP-check the public URL every 5 min — if the bot drops, you'll get an email before users notice.

### Updating

```bash
fly deploy                     # rebuild + roll the running machine
fly secrets set FOO=bar        # rotate a secret (triggers a restart)
```

## Project layout

- `bot/` — Telegram handlers, conversation state machine, package matcher, restaurant picker, LLM client, weather, follow-up scheduler, payments, analytics
- `data/` — JSON fixtures (`restaurants.json`, `locations.json`, `packages.json`) + per-user sessions + `analytics.jsonl`
- `prompts/` — system prompt for the LLM
- `tests/` — pytest suite for pure-logic modules
- `docs/superpowers/specs/` — design spec
