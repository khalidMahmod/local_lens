"""LocalLens configuration: loads env vars from .env (dev) or process env (production)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


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
    def messenger_enabled(self) -> bool:
        return bool(self.fb_page_access_token and self.fb_verify_token)

    @property
    def is_production(self) -> bool:
        return self.mode == "production"


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in .env (dev) or via fly secrets (production)."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_config() -> Config:
    return Config(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        openai_api_key=_optional("OPENAI_API_KEY"),
        openweathermap_api_key=_optional("OPENWEATHERMAP_API_KEY"),
        toyyibpay_api_key=_optional("TOYYIBPAY_API_KEY"),
        toyyibpay_category_code=_optional("TOYYIBPAY_CATEGORY_CODE"),
        toyyibpay_base_url=_optional(
            "TOYYIBPAY_BASE_URL", "https://dev.toyyibpay.com"
        ),
        webhook_url=_optional("WEBHOOK_URL"),
        webhook_secret=_optional("WEBHOOK_SECRET"),
        port=int(_optional("PORT", "8080") or "8080"),
        mode=_optional("LL_MODE", "dev"),
        fb_page_access_token=_optional("FB_PAGE_ACCESS_TOKEN"),
        fb_verify_token=_optional("FB_VERIFY_TOKEN"),
        fb_app_secret=_optional("FB_APP_SECRET"),
        owner_telegram_user_id=_optional("OWNER_TELEGRAM_USER_ID"),
    )
