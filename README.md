# LocalLens

Telegram-based AI travel assistant for Kuala Lumpur. See [docs/superpowers/specs/2026-05-04-locallens-design.md](docs/superpowers/specs/2026-05-04-locallens-design.md) for the full design spec.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # then fill in TELEGRAM_BOT_TOKEN
python -m bot.main
```

The bot starts in long-polling mode. Send `/start` to it from Telegram and it should reply `Hi from LocalLens`. Webhook mode arrives in Phase 10.
