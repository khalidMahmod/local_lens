"""LocalLens configuration: loads env vars from .env (dev) or process env (production)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    anthropic_api_key: str
    openweathermap_api_key: str
    toyyibpay_api_key: str
    mode: str

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
        anthropic_api_key=_optional("ANTHROPIC_API_KEY"),
        openweathermap_api_key=_optional("OPENWEATHERMAP_API_KEY"),
        toyyibpay_api_key=_optional("TOYYIBPAY_API_KEY"),
        mode=_optional("LL_MODE", "dev"),
    )
