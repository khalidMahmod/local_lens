"""LocalLens bot entry point.

Dev mode: long polling. Production mode (Phase 10): webhook.
"""

from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler

from config import load_config

from bot.handlers import start

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("locallens")


def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    return app


def main() -> None:
    config = load_config()
    app = build_application(config.telegram_bot_token)

    if config.is_production:
        logger.warning("Production webhook mode arrives in Phase 10; falling back to polling.")
    logger.info("Starting LocalLens bot in polling mode (mode=%s).", config.mode)
    app.run_polling()


if __name__ == "__main__":
    main()
