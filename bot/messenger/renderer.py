"""Format package data for Facebook Messenger quick-reply messages."""

from __future__ import annotations

from bot.models import Package

_LABEL_OVERRIDES: dict[str, str] = {
    "genting-batu-caves-daytrip": "Genting & Batu",
    "kl-city-daytrip-8hr": "KL Full Day",
    "genting-highlands-daytrip": "Genting Day Trip",
    "port-dickson-daytrip-private": "Port Dickson",
    "melaka-daytrip-private": "Melaka Day Trip",
    "ipoh-2d1n-premium": "Ipoh 2D1N",
}

QuickReply = dict[str, str]

MENU_QUICK_REPLIES: list[QuickReply] = [
    {"title": "View Packages", "payload": "VIEW_PACKAGES"},
    {"title": "Get Pricing", "payload": "GET_PRICING"},
    {"title": "Talk to a Human", "payload": "TALK_TO_HUMAN"},
]

_TALK_TO_HUMAN_QR: QuickReply = {"title": "Talk to a Human", "payload": "TALK_TO_HUMAN"}


def _short_label(pkg: Package) -> str:
    label = _LABEL_OVERRIDES.get(pkg.id, pkg.name)
    return label[:20]


def _duration_label(minutes: int) -> str:
    if minutes >= 1440:
        days = minutes // 1440
        return f"{days} day{'s' if days > 1 else ''}"
    hours = minutes // 60
    return f"{hours} hour{'s' if hours != 1 else ''}"


def render_welcome() -> tuple[str, list[QuickReply]]:
    text = (
        "Hi! I'm LocalLens — we run curated day trips and experiences from KL.\n\n"
        "How can I help?"
    )
    return text, list(MENU_QUICK_REPLIES)


def render_package_list(packages: list[Package]) -> tuple[str, list[QuickReply]]:
    premium = [p for p in packages if p.tier == "premium"]
    lines = ["Here are our trips:\n"]
    for i, pkg in enumerate(premium, 1):
        price = f"RM{pkg.price_rm}" if pkg.price_rm else "Free"
        lines.append(f"{i}. {pkg.name} — {price} (4 pax)")
    lines.append("\nTap a package for full details.")
    text = "\n".join(lines)
    replies: list[QuickReply] = [
        {"title": _short_label(pkg), "payload": f"PKG:{pkg.id}"}
        for pkg in premium
    ]
    replies.append(_TALK_TO_HUMAN_QR)
    return text, replies


def render_package_detail(pkg: Package) -> tuple[str, list[QuickReply]]:
    duration = _duration_label(pkg.duration_minutes)
    audience = ", ".join(pkg.audience_tags) if pkg.audience_tags else "everyone"
    places = ", ".join(s.place_name for s in pkg.steps if "Pickup" not in s.place_name and "Drop-off" not in s.place_name)

    lines = [
        f"{pkg.name}",
        f"Duration: {duration} | For: {audience}",
        "",
        places,
    ]
    if pkg.inclusions:
        lines.append("")
        lines.append("Included:")
        for item in pkg.inclusions:
            lines.append(f"- {item}")
    lines.append("")
    if pkg.price_rm:
        lines.append(f"RM{pkg.price_rm} for 4 pax")
    replies: list[QuickReply] = [
        {"title": "Book This", "payload": f"BOOK:{pkg.id}"},
        {"title": "Ask a Question", "payload": f"ASK_QUESTION:{pkg.id}"},
        {"title": "Back to Packages", "payload": "BACK_TO_PACKAGES"},
    ]
    return "\n".join(lines), replies


def render_pricing_table(packages: list[Package]) -> tuple[str, list[QuickReply]]:
    premium = [p for p in packages if p.tier == "premium"]
    lines = ["Our packages (all prices for 4 pax):\n"]
    for pkg in premium:
        price = f"RM{pkg.price_rm}" if pkg.price_rm else "Free"
        lines.append(f"{pkg.name} — {price}")
    lines.append("\nTap a package for full details.")
    text = "\n".join(lines)
    replies: list[QuickReply] = [
        {"title": _short_label(pkg), "payload": f"PKG:{pkg.id}"}
        for pkg in premium
    ]
    replies.append(_TALK_TO_HUMAN_QR)
    return text, replies
