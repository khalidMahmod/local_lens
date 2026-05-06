"""`/diet` command — re-edit halal preference any time, without changing state.

Pairs with the `diet_edit:*` callback prefix produced by
`bot.keyboards.dietary_keyboard("diet_edit")`.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import data_loader
from bot.conversation import set_dietary_preference
from bot.keyboards import dietary_keyboard


async def diet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user_id = str(update.effective_user.id)
    session = data_loader.load_session(user_id)
    if session is None:
        await update.message.reply_text("Type /start first so I can set you up.")
        return
    current = "Halal only" if session.dietary.halal_only else "No preference"
    await update.message.reply_text(
        f"Halal preference is currently: {current}.\nChange it?",
        reply_markup=dietary_keyboard("diet_edit"),
    )


async def on_diet_edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    session = set_dietary_preference(session, halal_only=halal_only, source="asked")
    data_loader.save_session(session)
    pref_text = "Halal only" if halal_only else "No preference"
    await query.edit_message_text(f"Updated — sticking to: {pref_text}.")
