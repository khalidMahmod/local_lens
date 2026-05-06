"""Vision-extractor: cover thumbnail + caption → Candidate.

Single OpenAI call per Reel. The image is sent at `detail: low` to keep token
cost predictable (~$0.00025 per Candidate at gpt-4o-mini). The system prompt
pins the JSON schema; `response_format=json_object` makes the parse reliable.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from openai import OpenAI, APIStatusError, RateLimitError

from ingest.models import (
    HALAL_SIGNALS,
    STALL_NAME_CONFIDENCE,
    Candidate,
    RawItem,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "extraction_prompt.txt"
_DEFAULT_MODEL = "gpt-4o-mini"
_RETRY_BACKOFF_SECONDS = 5

# Keys we expect the model to return. Used both for validation and for the
# "blank" extraction block when an extraction fails.
_EXTRACTION_FIELDS = (
    "stall_name",
    "stall_name_confidence",
    "dish_featured",
    "viral_hook",
    "claimed_must_order",
    "halal_signals",
    "operating_hours_mentioned",
    "google_maps_search_query",
    "candidate_quality_score",
    "extractor_notes",
)


def extract(
    raw_item: RawItem,
    *,
    client: Any | None = None,
    model: str | None = None,
    api_key: str | None = None,
    prompt_path: Path | None = None,
    sleep: Any = time.sleep,
) -> Candidate:
    """Run vision extraction on `raw_item`. Always returns a Candidate.

    On extraction failure (model error, malformed JSON, validation reject),
    returns a Candidate whose extraction block is blank and whose
    `extractor_notes` records the failure. The caller appends the result to
    `candidates.jsonl` regardless — failed rows are visible to the curator
    for re-extract via `--force`.
    """
    model_name = model or os.environ.get("INGEST_OPENAI_MODEL") or _DEFAULT_MODEL
    if client is None:
        if api_key is None:
            from config import load_config
            api_key = load_config().openai_api_key
        client = OpenAI(api_key=api_key)

    system_prompt = _load_prompt(prompt_path or _DEFAULT_PROMPT_PATH)
    messages = _build_messages(system_prompt, raw_item)

    extracted, failure_reason = _call_with_retry(
        client, model_name, messages, sleep=sleep
    )

    if failure_reason is not None:
        return _make_failed_candidate(raw_item, failure_reason)

    return _candidate_from_extraction(raw_item, extracted)


# ---- internals ------------------------------------------------------------

def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _build_messages(system_prompt: str, raw_item: RawItem) -> list[dict[str, Any]]:
    image_b64 = _encode_image(raw_item.thumbnail_path)
    user_text = (
        f"Source URL: {raw_item.source_url}\n\n"
        f"Caption:\n{raw_item.caption.strip() or '(empty)'}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                        "detail": "low",
                    },
                },
            ],
        },
    ]


def _encode_image(path: Path) -> str:
    with Path(path).open("rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _call_with_retry(
    client: Any, model: str, messages: list[dict[str, Any]], *, sleep: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (extracted_dict, None) on success or (None, reason) on failure."""
    for attempt in (1, 2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except RateLimitError as exc:
            if attempt == 1:
                logger.warning("OpenAI rate limit; retrying in %ds", _RETRY_BACKOFF_SECONDS)
                sleep(_RETRY_BACKOFF_SECONDS)
                continue
            return None, f"rate limit after retry: {exc}"
        except APIStatusError as exc:
            if 500 <= getattr(exc, "status_code", 0) < 600 and attempt == 1:
                logger.warning(
                    "OpenAI %s; retrying in %ds", exc.status_code, _RETRY_BACKOFF_SECONDS
                )
                sleep(_RETRY_BACKOFF_SECONDS)
                continue
            return None, f"api error {getattr(exc, 'status_code', '?')}: {exc}"
        except Exception as exc:  # network / unknown
            return None, f"openai call failed: {exc}"

        content = response.choices[0].message.content or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            return None, f"malformed JSON from model: {exc}"

        if not isinstance(parsed, dict):
            return None, f"expected JSON object, got {type(parsed).__name__}"

        return parsed, None

    return None, "exhausted retries without response"


def _candidate_from_extraction(raw_item: RawItem, extracted: dict[str, Any]) -> Candidate:
    """Validate + map extracted fields onto a Candidate. Validation problems
    don't drop the row — they're recorded in `extractor_notes`."""
    notes_addendum: list[str] = []

    halal = extracted.get("halal_signals")
    if halal is not None and halal not in HALAL_SIGNALS:
        notes_addendum.append(f"invalid halal_signals={halal!r}; coerced to unclear")
        halal = "unclear"

    confidence = extracted.get("stall_name_confidence")
    if confidence is not None and confidence not in STALL_NAME_CONFIDENCE:
        notes_addendum.append(
            f"invalid stall_name_confidence={confidence!r}; coerced to low"
        )
        confidence = "low"

    quality = extracted.get("candidate_quality_score")
    if quality is not None:
        try:
            quality = int(quality)
        except (TypeError, ValueError):
            notes_addendum.append(
                f"invalid candidate_quality_score={extracted.get('candidate_quality_score')!r}; dropped"
            )
            quality = None

    notes = extracted.get("extractor_notes")
    if notes_addendum:
        prefix = f"{notes} | " if notes else ""
        notes = prefix + "; ".join(notes_addendum)

    return Candidate(
        id=raw_item.candidate_id,
        status="pending",
        source_url=raw_item.source_url,
        source_platform="instagram",
        scraped_at=raw_item.scraped_at,
        thumbnail_path=str(raw_item.thumbnail_path),
        stall_name=extracted.get("stall_name"),
        stall_name_confidence=confidence,
        dish_featured=extracted.get("dish_featured"),
        viral_hook=extracted.get("viral_hook"),
        claimed_must_order=extracted.get("claimed_must_order"),
        halal_signals=halal,
        operating_hours_mentioned=extracted.get("operating_hours_mentioned"),
        google_maps_search_query=extracted.get("google_maps_search_query"),
        candidate_quality_score=quality,
        extractor_notes=notes,
    )


def _make_failed_candidate(raw_item: RawItem, reason: str) -> Candidate:
    return Candidate(
        id=raw_item.candidate_id,
        status="pending",
        source_url=raw_item.source_url,
        source_platform="instagram",
        scraped_at=raw_item.scraped_at,
        thumbnail_path=str(raw_item.thumbnail_path),
        extractor_notes=f"extraction failed: {reason}",
    )
