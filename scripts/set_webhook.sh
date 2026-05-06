#!/usr/bin/env bash
# Register the Telegram webhook with the Bot API.
#
# Run on a machine that can read the secrets:
#   - From your laptop with .env loaded:
#       set -a && source .env && set +a && bash scripts/set_webhook.sh
#   - From the deployed Fly app:
#       fly ssh console -C "bash /app/scripts/set_webhook.sh"
#
# Required env vars:
#   TELEGRAM_BOT_TOKEN  — same token the bot uses
#   WEBHOOK_URL         — full public HTTPS URL the bot listens on
#                         (e.g. https://locallens.fly.dev). The script appends
#                         the /telegram path component the bot expects.
# Optional:
#   WEBHOOK_SECRET      — Telegram echoes this back as the
#                         X-Telegram-Bot-Api-Secret-Token header so the bot
#                         can verify requests really came from Telegram.

set -euo pipefail

: "${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN before running}"
: "${WEBHOOK_URL:?Set WEBHOOK_URL (e.g. https://locallens.fly.dev) before running}"

target="${WEBHOOK_URL%/}/telegram"

echo "Setting Telegram webhook → ${target}"
response=$(
  curl -fsSL -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    --data-urlencode "url=${target}" \
    --data-urlencode "secret_token=${WEBHOOK_SECRET:-}" \
    --data-urlencode "drop_pending_updates=true"
)

echo "${response}"

# Bail out if the API didn't return ok=true.
case "${response}" in
  *'"ok":true'*) ;;
  *) echo "setWebhook did not return ok=true; check the response above." >&2; exit 1 ;;
esac

echo "Verifying with getWebhookInfo:"
curl -fsSL "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
echo
