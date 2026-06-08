"""Telegram command, message, and callback handlers.

The handlers are thin glue: load session → apply a `bot.conversation` event →
save session → reply. Pure-logic state transitions live in `bot.conversation`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import ContextTypes

from bot import analytics, data_loader, payments
from bot.context_extractor import build_context
from bot.conversation import (
    InvalidTransition,
    accept_premium_package,
    offer_premium_package,
    transition,
)
from bot.keyboards import dietary_keyboard, intent_keyboard, premium_accept_keyboard
from bot.llm_client import generate_free_recommendations
from bot.models import Session
from bot.package_matcher import match_packages
from bot.payments import PaymentProvider
from bot.renderers import (
    render_bonus_package,
    render_free_package,
    render_meal_addon,
    render_premium_full,
    render_premium_tease,
)
from bot.restaurant_picker import pick_restaurants

logger = logging.getLogger(__name__)


def _location_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Share location", request_location=True)]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )


def _load_or_new(user_id: str) -> Session:
    session = data_loader.load_session(user_id)
    if session is None:
        session = Session(telegram_user_id=user_id)
    return session


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user_id = str(update.effective_user.id)
    session = _load_or_new(user_id)
    session = transition(session, {"type": "start"})
    data_loader.save_session(session)
    await update.message.reply_text(
        "Hey! I'm LocalLens — I help you find the best things to do right now. "
        "Share your location and I'll get started.",
        reply_markup=_location_request_keyboard(),
    )


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    # Accept both a raw location pin and a venue (named place from Telegram's
    # location search — its coords are nested under .venue.location).
    loc = update.message.location
    if loc is None and update.message.venue is not None:
        loc = update.message.venue.location
    if loc is None:
        return
    user_id = str(update.effective_user.id)
    session = data_loader.load_session(user_id)
    if session is None:
        await update.message.reply_text(
            "Type /start to begin.", reply_markup=ReplyKeyboardRemove()
        )
        return
    try:
        session = transition(
            session, {"type": "location", "lat": loc.latitude, "lng": loc.longitude}
        )
    except InvalidTransition:
        await update.message.reply_text(
            "Got your location. Type /start to redo onboarding if needed.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    data_loader.save_session(session)
    if session.current_state == "awaiting_dietary":
        await update.message.reply_text(
            "Got it. Quick one — should I stick to halal food spots?",
            reply_markup=ReplyKeyboardRemove(),
        )
        await update.message.reply_text(
            "Pick one:", reply_markup=dietary_keyboard()
        )
    else:
        await update.message.reply_text(
            "Updated your location.", reply_markup=ReplyKeyboardRemove()
        )


async def on_text_during_onboarding(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Catch-all text handler. In `awaiting_location`, nudge the user to use the
    location button — typing a place name as text isn't a real location."""
    if update.message is None or update.effective_user is None:
        return
    user_id = str(update.effective_user.id)
    session = data_loader.load_session(user_id)
    if session is None:
        await update.message.reply_text("Type /start to begin.")
        return
    if session.current_state == "awaiting_location":
        await update.message.reply_text(
            "I need a real location pin (typed place names won't cut it). "
            "Tap the 'Share location' button — or in Telegram: 📎 → Location → "
            "'Send my current location'.",
            reply_markup=_location_request_keyboard(),
        )
        return
    if session.current_state == "awaiting_dietary":
        await update.message.reply_text(
            "Pick one:", reply_markup=dietary_keyboard()
        )
        return
    if session.current_state == "awaiting_intent":
        await update.message.reply_text(
            "Pick one:", reply_markup=intent_keyboard()
        )
        return
    await _handle_chatting_message(update.message, session, update.message.text or "")


async def on_dietary_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.from_user is None:
        return
    await query.answer()
    _, value = query.data.split(":", 1)
    halal_only = value == "halal_only"
    user_id = str(query.from_user.id)
    session = data_loader.load_session(user_id)
    if session is None:
        await query.edit_message_text("Session expired. Type /start to begin.")
        return
    try:
        session = transition(session, {"type": "dietary", "halal_only": halal_only})
    except InvalidTransition:
        await query.edit_message_text(
            "Halal pref noted. Use /diet to change it any time."
        )
        return
    data_loader.save_session(session)
    pref_text = "Halal only" if halal_only else "No preference"
    await query.edit_message_text(f"Got it — {pref_text}.")
    if query.message is not None:
        await query.message.reply_text(
            "What are you looking for right now?", reply_markup=intent_keyboard()
        )


async def _handle_chatting_message(
    message: Message, session: Session, user_text: str
) -> None:
    """Path B (free package match) → premium tease → Path A (LLM) fallback.

    Free wins over premium when both match: free packages add no friction, so
    we deliver them directly. Premium packages get the tease + accept flow.
    """
    if not user_text.strip():
        return

    session.history.append({"role": "user", "text": user_text})
    analytics.log_event(
        "query", session.telegram_user_id, {"text_length": len(user_text)}
    )

    try:
        ctx = build_context(session, datetime.now(timezone.utc))
    except Exception:
        logger.exception("build_context failed for user %s", session.telegram_user_id)
        await message.reply_text(
            "I'm having trouble pulling local context right now. Try again in a moment."
        )
        return

    matches = match_packages(ctx)
    free_match = next(
        (m for m in matches if m.package.tier == "free"), None
    )
    if free_match is not None:
        # Path B: deliver the package + meal-time food add-on.
        # `exclude_meal_window` for packages whose steps already cover the meal
        # is a Phase 8+ refinement once a meal-package fixture exists.
        picks = pick_restaurants(ctx, session)
        reply = render_free_package(free_match.package)
        addon = render_meal_addon(picks, ctx.time_of_day_window)
        if addon:
            reply = f"{reply}\n\n{addon}"
        await message.reply_text(reply)
        session.active_package_id = free_match.package.id
        session.history.append({"role": "assistant", "text": reply})
        data_loader.save_session(session)
        analytics.log_event(
            "package_offered",
            session.telegram_user_id,
            {"package_id": free_match.package.id, "tier": "free"},
        )
        return

    premium_match = next(
        (m for m in matches if m.package.tier == "premium"), None
    )
    if premium_match is not None:
        pkg = premium_match.package
        try:
            session = offer_premium_package(session, pkg.id)
        except InvalidTransition:
            logger.exception(
                "offer_premium_package rejected for user %s in state %s",
                session.telegram_user_id,
                session.current_state,
            )
        tease = render_premium_tease(pkg)
        await message.reply_text(tease, reply_markup=premium_accept_keyboard(pkg.id))
        session.history.append({"role": "assistant", "text": tease})
        data_loader.save_session(session)
        analytics.log_event(
            "package_offered",
            session.telegram_user_id,
            {"package_id": pkg.id, "tier": "premium"},
        )
        return

    # Path A: no package match → LLM-generated recommendations + add-on.
    picks = pick_restaurants(ctx, session)
    try:
        reply = generate_free_recommendations(ctx, picks, session.history)
    except Exception:
        logger.exception(
            "LLM call failed for user %s", session.telegram_user_id
        )
        await message.reply_text(
            "My recommendation brain hit a snag — try again in a moment."
        )
        return

    await message.reply_text(reply)
    session.history.append({"role": "assistant", "text": reply})
    data_loader.save_session(session)


async def on_premium_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback when user taps "Want full plan?" on a premium tease.

    Records the soft commitment (price + accepted_at), transitions to
    `accepted`, and delivers the full plan with all step details.
    """
    query = update.callback_query
    if query is None or query.data is None or query.from_user is None:
        return
    await query.answer()
    _, package_id = query.data.split(":", 1)
    user_id = str(query.from_user.id)
    session = data_loader.load_session(user_id)
    if session is None:
        await query.edit_message_text("Session expired. Type /start to begin.")
        return

    package = next(
        (p for p in data_loader.load_packages() if p.id == package_id), None
    )
    if package is None:
        logger.error("premium_accept for unknown package_id=%r", package_id)
        await query.edit_message_text("That plan is no longer available.")
        return

    accepted_at_iso = datetime.now(timezone.utc).isoformat()
    try:
        session = accept_premium_package(
            session, package_id, package.price_rm or 0, accepted_at_iso
        )
    except InvalidTransition:
        logger.exception(
            "accept_premium_package rejected for user %s in state %s",
            session.telegram_user_id,
            session.current_state,
        )
        await query.edit_message_text(
            "That plan can't be accepted right now. Send a new message to start over."
        )
        return

    try:
        ctx = build_context(session, datetime.now(timezone.utc))
        picks = pick_restaurants(ctx, session)
        full_plan = render_premium_full(package, picks, ctx.time_of_day_window)
    except Exception:
        logger.exception(
            "rendering full plan failed for user %s", session.telegram_user_id
        )
        full_plan = render_premium_full(package)

    await query.edit_message_text("Locked in — full plan coming up.")
    if query.message is not None:
        await query.message.reply_text(full_plan)
    session.history.append({"role": "assistant", "text": full_plan})

    # Deliver complimentary bonus package if one is linked.
    bonus_text = ""
    if package.bonus_package_id:
        bonus_pkg = next(
            (p for p in data_loader.load_packages() if p.id == package.bonus_package_id),
            None,
        )
        if bonus_pkg and query.message is not None:
            bonus_text = render_bonus_package(bonus_pkg)
            await query.message.reply_text(bonus_text)
            session.history.append({"role": "assistant", "text": bonus_text})

    data_loader.save_session(session)
    analytics.log_event(
        "package_accepted",
        session.telegram_user_id,
        {"package_id": package.id, "commitment_price": session.commitment_price},
    )
    if bonus_text:
        analytics.log_event(
            "bonus_package_delivered",
            session.telegram_user_id,
            {"bonus_package_id": package.bonus_package_id, "parent_package_id": package.id},
        )


async def on_feedback_loved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User tapped [Loved it] on a follow-up DM. Send payment link + tip + referral."""
    query = update.callback_query
    if query is None or query.from_user is None:
        return
    await query.answer()
    user_id = str(query.from_user.id)
    session = data_loader.load_session(user_id)
    if session is None:
        await query.edit_message_text("Session expired. Type /start to begin.")
        return

    provider: PaymentProvider | None = context.bot_data.get("payment_provider") if context.bot_data else None
    payment_url = payments.build_payment_link(session, provider=provider)
    bot_username = context.bot_data.get("bot_username", "") if context.bot_data else ""
    referral = (
        f"https://t.me/{bot_username}?start=ref_{user_id}"
        if bot_username
        else "https://t.me/"
    )
    reply = (
        "Glad you enjoyed it! Pay what you committed (or tip extra if it really was worth it):\n"
        f"{payment_url}\n\n"
        "Got a friend who'd love this? Share LocalLens:\n"
        f"{referral}"
    )

    await query.edit_message_text("Awesome — sending you the payment link.")
    if query.message is not None:
        await query.message.reply_text(reply)
    session.history.append({"role": "assistant", "text": reply})
    data_loader.save_session(session)
    analytics.log_event(
        "payment_sent",
        session.telegram_user_id,
        {
            "package_id": session.active_package_id,
            "amount_rm": session.commitment_price,
            "url": payment_url,
        },
    )


async def on_feedback_meh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User tapped [Was meh]. Collect feedback, no payment push."""
    query = update.callback_query
    if query is None or query.from_user is None:
        return
    await query.answer()
    user_id = str(query.from_user.id)
    session = data_loader.load_session(user_id)
    if session is None:
        await query.edit_message_text("Session expired. Type /start to begin.")
        return

    reply = (
        "Sorry it didn't land. What would've made it better? Reply here — your "
        "feedback shapes the next plans I build."
    )
    await query.edit_message_text("Got it — appreciate the honesty.")
    if query.message is not None:
        await query.message.reply_text(reply)
    session.history.append({"role": "assistant", "text": reply})
    data_loader.save_session(session)
    analytics.log_event(
        "feedback",
        session.telegram_user_id,
        {"sentiment": "negative", "package_id": session.active_package_id},
    )


_INTENT_PROMPTS: dict[str, str] = {
    "food": "I'm looking for food nearby — what's good to eat right now?",
    "chill": "I want to chill and relax — what's nearby?",
    "explore": "I want to explore the area — what's interesting nearby?",
    "surprise": "Surprise me — what should I do right now?",
}


async def on_intent_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.from_user is None:
        return
    await query.answer()
    _, intent = query.data.split(":", 1)
    user_id = str(query.from_user.id)
    session = data_loader.load_session(user_id)
    if session is None:
        await query.edit_message_text("Session expired. Type /start to begin.")
        return
    try:
        session = transition(session, {"type": "intent", "intent": intent})
    except InvalidTransition:
        await query.edit_message_text("Already onboarded — just send me a message.")
        return
    data_loader.save_session(session)
    await query.edit_message_text(f"Locked in — {intent}. Let me find something for you...")

    # Immediately trigger a recommendation using the intent as the first message.
    auto_text = _INTENT_PROMPTS.get(intent, f"I'm looking for {intent} — what do you suggest?")
    if query.message is not None:
        await _handle_chatting_message(query.message, session, auto_text)
