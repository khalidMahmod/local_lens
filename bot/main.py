"""LocalLens bot entry point.

Dev mode: long polling. Production mode (Phase 10): webhook.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import Config, load_config

from bot import follow_up
from bot.commands.diet import diet_command, on_diet_edit_choice
from bot.handlers import (
    on_dietary_choice,
    on_feedback_loved,
    on_feedback_meh,
    on_intent_choice,
    on_location,
    on_premium_accept,
    on_text_during_onboarding,
    start,
)
from bot.payments import PaymentProvider, ToyyibPayProvider

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("locallens")

FOLLOW_UP_INTERVAL_MINUTES = 15

# Constant URL path component for the Telegram webhook. The full public URL
# (config.webhook_url) plus this suffix is what we register with Telegram.
WEBHOOK_URL_PATH = "telegram"


def build_application(config: Config) -> Application:
    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["payment_provider"] = _build_payment_provider(config)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("diet", diet_command))
    app.add_handler(MessageHandler(filters.LOCATION | filters.VENUE, on_location))
    app.add_handler(CallbackQueryHandler(on_dietary_choice, pattern=r"^dietary:"))
    app.add_handler(CallbackQueryHandler(on_diet_edit_choice, pattern=r"^diet_edit:"))
    app.add_handler(CallbackQueryHandler(on_intent_choice, pattern=r"^intent:"))
    app.add_handler(CallbackQueryHandler(on_premium_accept, pattern=r"^premium_accept:"))
    app.add_handler(CallbackQueryHandler(on_feedback_loved, pattern=r"^feedback:loved$"))
    app.add_handler(CallbackQueryHandler(on_feedback_meh, pattern=r"^feedback:meh$"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_during_onboarding)
    )
    app.post_init = _post_init
    return app


def _build_payment_provider(config: Config) -> PaymentProvider | None:
    if not (config.toyyibpay_api_key and config.toyyibpay_category_code):
        logger.info(
            "TOYYIBPAY_API_KEY / TOYYIBPAY_CATEGORY_CODE not set — payment links "
            "will use a placeholder URL until configured."
        )
        return None
    return ToyyibPayProvider(
        api_key=config.toyyibpay_api_key,
        category_code=config.toyyibpay_category_code,
        base_url=config.toyyibpay_base_url,
    )


async def _post_init(app: Application) -> None:
    """Cache bot identity + start the follow-up scheduler once the loop is up."""
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


async def _run_follow_up_tick(*, app: Application) -> None:
    sent = await follow_up.tick(datetime.now(timezone.utc), bot=app.bot)
    if sent:
        logger.info("Follow-up DMs sent to %d user(s): %s", len(sent), sent)


def main() -> None:
    config = load_config()
    app = build_application(config)

    if config.is_production:
        if not config.webhook_url:
            raise RuntimeError(
                "LL_MODE=production requires WEBHOOK_URL (the full public HTTPS URL "
                "the bot listens on, e.g. https://locallens.fly.dev)."
            )
        full_webhook_url = f"{config.webhook_url.rstrip('/')}/{WEBHOOK_URL_PATH}"
        logger.info(
            "Starting LocalLens in webhook mode on 0.0.0.0:%d → %s",
            config.port,
            full_webhook_url,
        )
        app.run_webhook(
            listen="0.0.0.0",
            port=config.port,
            url_path=WEBHOOK_URL_PATH,
            webhook_url=full_webhook_url,
            secret_token=config.webhook_secret or None,
            drop_pending_updates=True,
        )
        return

    logger.info("Starting LocalLens bot in polling mode (mode=%s).", config.mode)
    app.run_polling()


if __name__ == "__main__":
    main()
