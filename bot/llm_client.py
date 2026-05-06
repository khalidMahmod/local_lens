"""OpenAI wrapper for free-recommendation generation (Phase 6, Path A).

Uses `gpt-4o-mini` by default — cheap, fast, fits the project's per-turn cost
target. Override via the `model=` kwarg if you want quality bumps later
(`gpt-4o`, `gpt-4.1`, etc.).

The picks chosen by `restaurant_picker` are serialized into the latest user
message so the model has a closed list of real spots to draw from — the system
prompt forbids inventing places. OpenAI applies prompt caching automatically
on the system-message prefix; no explicit cache markers are needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI

from bot.models import Context, Restaurant

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS = 1024
_DEFAULT_HISTORY_TURNS = 5

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SYSTEM_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "system_prompt.txt"


def generate_free_recommendations(
    context: Context,
    restaurant_picks: list[Restaurant],
    session_history: list[dict[str, Any]],
    *,
    client: Any | None = None,
    api_key: str | None = None,
    model: str = _DEFAULT_MODEL,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    max_history_turns: int = _DEFAULT_HISTORY_TURNS,
    system_prompt_path: Path | None = None,
) -> str:
    if not session_history:
        raise ValueError(
            "session_history must contain at least the latest user message"
        )

    if client is None:
        if api_key is None:
            from config import load_config
            api_key = load_config().openai_api_key
        client = OpenAI(api_key=api_key)

    system_prompt = _load_system_prompt(system_prompt_path or _DEFAULT_SYSTEM_PROMPT_PATH)
    context_block = _format_context_block(context, restaurant_picks)
    messages = _build_messages(
        system_prompt, session_history, context_block, max_history_turns
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
    )
    return response.choices[0].message.content or ""


def _load_system_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _build_messages(
    system_prompt: str,
    history: list[dict[str, Any]],
    context_block: str,
    max_history_turns: int,
) -> list[dict[str, Any]]:
    trimmed = history[-max_history_turns:]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    last_idx = len(trimmed) - 1
    for i, turn in enumerate(trimmed):
        role = turn["role"]
        text = turn["text"]
        if i == last_idx and role == "user":
            text = f"{context_block}\n\n{text}"
        messages.append({"role": role, "content": text})
    return messages


def _format_context_block(context: Context, picks: Iterable[Restaurant]) -> str:
    lines = [
        "[CONTEXT — system-supplied, not from the user]",
        f"Area: {context.area_name}",
        f"Time-of-day window: {context.time_of_day_window}",
        f"Weather: {context.weather.condition} ({context.weather.description}), "
        f"{context.weather.temp_c:.0f}°C",
    ]
    pick_list = list(picks)
    if pick_list:
        lines.append("")
        lines.append(
            f"Nearby food spots for the {context.time_of_day_window} add-on "
            "(use 1–2 of these — do NOT invent others):"
        )
        for i, r in enumerate(pick_list, 1):
            lines.append(f"{i}. {r.name}")
            lines.append(f"   Cuisine: {r.cuisine} ({r.price_tier})")
            lines.append(f"   Halal: {r.halal_status}")
            lines.append(f"   Indoor: {'yes' if r.indoor else 'no'}")
            if r.insider_tip:
                lines.append(f"   Tip: {r.insider_tip}")
            if r.google_maps_link:
                lines.append(f"   Maps: {r.google_maps_link}")
    else:
        lines.append("")
        lines.append(
            "No food spots returned for the current window — skip the meal-time "
            "add-on for this reply."
        )
    lines.append("[/CONTEXT]")
    return "\n".join(lines)
