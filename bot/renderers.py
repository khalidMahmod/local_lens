"""Plain-text renderers for Telegram replies.

No markdown — Telegram's `reply_text` is sent without `parse_mode`, so any
asterisks would render literally. Each step gets the Maps link on its own line
for one-tap navigation.
"""

from __future__ import annotations

from bot.models import Package, Restaurant

_WINDOW_OPENERS: dict[str, str] = {
    "breakfast": "Breakfast nearby?",
    "lunch": "Hungry?",
    "afternoon_snack": "Snack time?",
    "dinner": "Dinner nearby?",
    "late_night": "Late-night bite?",
}


def render_free_package(package: Package) -> str:
    lines: list[str] = [f"📍 {package.name}"]
    if package.why_it_works:
        lines.append(package.why_it_works)
    lines.append("")
    for step in package.steps:
        lines.append(f"{step.order}. {step.place_name} ({step.duration_minutes} min)")
        if step.description:
            lines.append(f"   {step.description}")
        if step.insider_tip:
            lines.append(f"   Tip: {step.insider_tip}")
        if step.google_maps_link:
            lines.append(f"   {step.google_maps_link}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_premium_tease(package: Package) -> str:
    """Premium upsell tease per spec lines 232–237.

    Shows the *what* of each step (the description) plus duration, but withholds
    the *where exactly* — `place_name`, `insider_tip`, and `google_maps_link`
    are all suppressed. Closes with the price + post-pay framing.

    Caller responsibility: the package's step descriptions must not embed the
    place_name verbatim. Existing fixtures honour this.
    """
    lines: list[str] = [f"📍 {package.name}"]
    if package.why_it_works:
        lines.append(package.why_it_works)
    lines.append("")
    lines.append("Here's the outline:")
    for step in package.steps:
        lines.append(
            f"{step.order}. {step.description} (~{step.duration_minutes} min)"
        )
    lines.append("")
    if package.price_rm is not None:
        lines.append(
            f"RM{package.price_rm} — you only pay after if it was worth it."
        )
    lines.append("Want the full plan?")
    return "\n".join(lines).rstrip()


def render_premium_full(
    package: Package,
    picks: list[Restaurant] | None = None,
    window: str | None = None,
) -> str:
    """Full premium plan once accepted: place names, tips, Maps links, plus
    optional meal-time food add-on and the follow-up promise.
    """
    body = render_free_package(package)
    if picks and window:
        addon = render_meal_addon(picks, window)
        if addon:
            body = f"{body}\n\n{addon}"
    return f"{body}\n\nEnjoy! I'll check in with you in a couple of hours."


def render_meal_addon(picks: list[Restaurant], window: str) -> str:
    """Short food add-on appended to free-package replies.

    Returns empty string when picks is empty or window is `between` — the spec
    says skip the add-on outside meal hours.
    """
    if not picks or window == "between":
        return ""
    opener = _WINDOW_OPENERS.get(window, "Hungry?")
    lines: list[str] = [opener]
    for r in picks:
        lines.append(f"• {r.name} — {r.cuisine}")
        if r.insider_tip:
            lines.append(f"  Tip: {r.insider_tip}")
        if r.google_maps_link:
            lines.append(f"  {r.google_maps_link}")
    return "\n".join(lines)
