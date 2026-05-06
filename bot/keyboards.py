"""Inline keyboard builders for onboarding and the /diet command.

Callback-data conventions (parsed in `bot.handlers`):
    dietary:halal_only    onboarding answer — Halal only
    dietary:no_pref       onboarding answer — No preference
    diet_edit:halal_only  /diet — Halal only
    diet_edit:no_pref     /diet — No preference
    intent:<key>          intent picker (chill / food / explore / surprise)
    premium_accept:<id>   "Want full plan?" on a premium tease — id is package_id
    feedback:loved        Follow-up DM — user enjoyed the plan
    feedback:meh          Follow-up DM — user didn't enjoy it
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


INTENT_OPTIONS: list[tuple[str, str]] = [
    ("Chill", "chill"),
    ("Food", "food"),
    ("Explore", "explore"),
    ("Surprise me", "surprise"),
]


def dietary_keyboard(prefix: str = "dietary") -> InlineKeyboardMarkup:
    """Halal pref buttons. `prefix` is `dietary` for onboarding, `diet_edit` for /diet."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Halal only", callback_data=f"{prefix}:halal_only"),
                InlineKeyboardButton("No preference", callback_data=f"{prefix}:no_pref"),
            ]
        ]
    )


def intent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"intent:{key}")] for label, key in INTENT_OPTIONS]
    )


def premium_accept_keyboard(package_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Want full plan?", callback_data=f"premium_accept:{package_id}")]]
    )


def follow_up_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Loved it", callback_data="feedback:loved"),
                InlineKeyboardButton("Was meh", callback_data="feedback:meh"),
            ]
        ]
    )
