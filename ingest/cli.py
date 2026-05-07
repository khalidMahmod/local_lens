"""argparse entry point for the ingestion pipeline.

Subcommands:
- `pull-profile <url>`  — yt-dlp metadata pass + thumbnail download, then
                          chains into extract for each new RawItem.
- `add-url <url>`       — single-Reel variant of pull-profile.
- `extract`             — re-extract one row (`--id`) or every pending row
                          (`--all-pending`) using thumbnails already on disk.
- `export`              — promote `status=live` Candidates into restaurants.json.

Cookie failure modes (per the spec error table) are caught and translated into
friendly stderr messages with exit code 2 so the curator knows what to do.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from yt_dlp.utils import DownloadError

from ingest import candidates_store, exporter, extractor
from ingest.collectors import instagram
from ingest.collectors.instagram import CookieAuth
from ingest.models import Candidate, RawItem


logger = logging.getLogger("ingest")


_COOKIE_EXPIRED_HINTS = ("login required", "login_required", "401")
_CHROME_LOCKED_HINTS = (
    "could not copy",
    "database is locked",
    "unable to read browser cookies",
)
_COOKIE_EXPIRED_MSG = (
    "IG session expired — re-login in Chrome, or pass --no-cookies "
    "for an anonymous run."
)
_CHROME_LOCKED_MSG = (
    "Chrome cookie store locked — quit Chrome and retry, or use "
    "--cookies-from-browser firefox / --no-cookies."
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging()

    if args.command == "pull-profile":
        return _cmd_pull_profile(args)
    if args.command == "add-url":
        return _cmd_add_url(args)
    if args.command == "extract":
        return _cmd_extract(args)
    if args.command == "export":
        return _cmd_export(args)
    parser.print_help(sys.stderr)
    return 2


# ---- argparse setup -----------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    pp = sub.add_parser("pull-profile", help="Pull a profile feed via yt-dlp + extract")
    pp.add_argument("profile_url")
    pp.add_argument("--limit", type=int, default=10)
    pp.add_argument(
        "--rank-by", choices=["recent", "popularity"], default="recent"
    )
    pp.add_argument("--window", type=int, default=50)
    pp.add_argument("--force", action="store_true")
    _add_auth_group(pp)

    au = sub.add_parser("add-url", help="Pull a single Reel by URL + extract")
    au.add_argument("reel_url")
    au.add_argument("--force", action="store_true")
    _add_auth_group(au)

    ex = sub.add_parser("extract", help="Re-extract from on-disk thumbnails")
    g = ex.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", dest="candidate_id")
    g.add_argument("--all-pending", action="store_true", dest="all_pending")

    sub.add_parser("export", help="Write live Candidates into restaurants.json")

    return parser


def _add_auth_group(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cookies", type=Path, default=None, metavar="PATH")
    g.add_argument(
        "--cookies-from-browser",
        dest="cookies_from_browser",
        default=None,
        metavar="BROWSER",
    )
    g.add_argument("--no-cookies", action="store_true", dest="no_cookies")


def _build_auth(args: argparse.Namespace) -> CookieAuth:
    if getattr(args, "no_cookies", False):
        return CookieAuth.anonymous()
    if args.cookies is not None:
        return CookieAuth(cookies_file=args.cookies)
    if args.cookies_from_browser is not None:
        return CookieAuth(cookies_from_browser=args.cookies_from_browser)
    return CookieAuth.default()


def _configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


# ---- subcommands --------------------------------------------------------

def _cmd_pull_profile(args: argparse.Namespace) -> int:
    auth = _build_auth(args)
    try:
        items = instagram.pull_profile(
            args.profile_url,
            limit=args.limit,
            rank_by=args.rank_by,
            window=args.window,
            auth=auth,
            force=args.force,
        )
    except DownloadError as exc:
        return _handle_download_error(exc)
    return _extract_and_append(items)


def _cmd_add_url(args: argparse.Namespace) -> int:
    auth = _build_auth(args)
    try:
        item = instagram.pull_url(args.reel_url, auth=auth, force=args.force)
    except DownloadError as exc:
        return _handle_download_error(exc)
    return _extract_and_append([item])


def _cmd_extract(args: argparse.Namespace) -> int:
    if args.candidate_id is not None:
        targets = [c for c in candidates_store.iter_all() if c.id == args.candidate_id]
        if not targets:
            print(f"no candidate with id={args.candidate_id!r}", file=sys.stderr)
            return 1
    else:
        targets = list(candidates_store.iter_all(status="pending"))

    total = len(targets)
    if total == 0:
        logger.info("no candidates to extract")
        return 0

    for i, candidate in enumerate(targets, 1):
        logger.info("[%d/%d] %s — extracting…", i, total, candidate.id)
        raw = _candidate_to_raw_item(candidate)
        fresh = extractor.extract(raw)
        candidates_store.replace_in_place(_merge_extraction(candidate, fresh))
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    result = exporter.export()
    print(
        f"exported: {result.exported}, "
        f"skipped_invalid: {result.skipped_invalid}, "
        f"total_live: {result.total_live}"
    )
    if result.invalid_ids:
        print("invalid: " + ", ".join(result.invalid_ids))
    return 0


# ---- helpers ------------------------------------------------------------

def _extract_and_append(items: Iterable[RawItem]) -> int:
    items = list(items)
    total = len(items)
    if total == 0:
        logger.info("nothing to extract")
        return 0
    for i, raw in enumerate(items, 1):
        logger.info("[%d/%d] %s — extracting…", i, total, raw.candidate_id)
        candidates_store.append(extractor.extract(raw))
    return 0


def _candidate_to_raw_item(candidate: Candidate) -> RawItem:
    """Reconstruct a RawItem for re-extraction from a Candidate already on disk.

    The caption + counts live in `info.json` (saved alongside cover.jpg by the
    collector); we read them back so the re-extract sees the same prompt input
    as the original extraction.
    """
    thumbnail_path = Path(candidate.thumbnail_path or "")
    info_path = thumbnail_path.parent / "info.json"

    caption = ""
    play_count: int | None = None
    like_count: int | None = None
    posted_at: str | None = None
    if info_path.exists():
        info = json.loads(info_path.read_text(encoding="utf-8"))
        caption = str(info.get("description") or "")
        play_count = _int_or_none(info.get("play_count"))
        like_count = _int_or_none(info.get("like_count"))
        posted_at = _iso_or_none(info.get("timestamp"))

    reel_id = candidate.id.removeprefix("ig_") if candidate.id.startswith("ig_") else candidate.id
    return RawItem(
        reel_id=reel_id,
        candidate_id=candidate.id,
        source_url=candidate.source_url,
        thumbnail_path=thumbnail_path,
        caption=caption,
        play_count=play_count,
        like_count=like_count,
        posted_at=posted_at,
        scraped_at=candidate.scraped_at,
    )


def _merge_extraction(existing: Candidate, fresh: Candidate) -> Candidate:
    """Replace `existing`'s extraction block with `fresh`'s; keep identity,
    status, and the curator's manual-fill block intact."""
    return Candidate(
        id=existing.id,
        status=existing.status,
        source_url=existing.source_url,
        source_platform=existing.source_platform,
        scraped_at=existing.scraped_at,
        thumbnail_path=existing.thumbnail_path,
        stall_name=fresh.stall_name,
        stall_name_confidence=fresh.stall_name_confidence,
        dish_featured=fresh.dish_featured,
        viral_hook=fresh.viral_hook,
        claimed_must_order=fresh.claimed_must_order,
        halal_signals=fresh.halal_signals,
        operating_hours_mentioned=fresh.operating_hours_mentioned,
        google_maps_search_query=fresh.google_maps_search_query,
        candidate_quality_score=fresh.candidate_quality_score,
        extractor_notes=fresh.extractor_notes,
        lat=existing.lat,
        lng=existing.lng,
        area=existing.area,
        cuisine=existing.cuisine,
        price_tier=existing.price_tier,
        meal_tags=existing.meal_tags,
        indoor=existing.indoor,
        vibe_tags=existing.vibe_tags,
        halal_status=existing.halal_status,
        google_maps_link=existing.google_maps_link,
        insider_tip=existing.insider_tip,
    )


def _handle_download_error(exc: DownloadError) -> int:
    msg = str(exc).lower()
    if any(h in msg for h in _CHROME_LOCKED_HINTS):
        print(_CHROME_LOCKED_MSG, file=sys.stderr)
        return 2
    if any(h in msg for h in _COOKIE_EXPIRED_HINTS):
        print(_COOKIE_EXPIRED_MSG, file=sys.stderr)
        return 2
    raise exc


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso_or_none(timestamp) -> str | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None
