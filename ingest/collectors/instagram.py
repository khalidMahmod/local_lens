"""Instagram profile / single-Reel collector.

yt-dlp does the metadata pass (no video download), we then GET the cover
thumbnail for each selected post. Cookies default to Chrome's logged-in
session so deep pagination works; `--no-cookies` opts back into anonymous
mode.

The pure-logic helpers (`_select`, `_to_raw_item`, `_yt_dlp_opts`) are
exposed for testing — the tests fake `_metadata_pass` and `_fetch_thumbnail`
to avoid hitting the network.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

import requests

from ingest import candidates_store
from ingest.models import RawItem

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_ARCHIVE_DIR = _PROJECT_ROOT / "data" / "source_archive"
_THUMBNAIL_FETCH_SLEEP_SECONDS = 1.0


@dataclass(frozen=True)
class CookieAuth:
    """At most one of cookies_file / cookies_from_browser is set.
    Both None → anonymous mode (no cookies passed to yt-dlp)."""

    cookies_file: Path | None = None
    cookies_from_browser: str | None = None  # "firefox", "chrome", etc.

    def __post_init__(self) -> None:
        if self.cookies_file is not None and self.cookies_from_browser is not None:
            raise ValueError(
                "CookieAuth: pick at most one of cookies_file or cookies_from_browser"
            )

    @classmethod
    def default(cls) -> "CookieAuth":
        """The pipeline's default: read cookies from Chrome's profile."""
        return cls(cookies_from_browser="chrome")

    @classmethod
    def anonymous(cls) -> "CookieAuth":
        return cls()


def pull_profile(
    profile_url: str,
    *,
    limit: int = 10,
    rank_by: Literal["recent", "popularity"] = "recent",
    window: int = 50,
    archive_dir: Path | None = None,
    auth: CookieAuth | None = None,
    force: bool = False,
    candidates_path: Path | None = None,
) -> list[RawItem]:
    archive = _resolve_archive_dir(archive_dir)
    auth = auth if auth is not None else CookieAuth.default()

    n = window if rank_by == "popularity" else limit
    entries = _metadata_pass(profile_url, n=n, auth=auth)

    selected = _select(entries, limit=limit, rank_by=rank_by)

    if not force:
        skip_ids = candidates_store.existing_ids(path=candidates_path)
        before = len(selected)
        selected = [e for e in selected if f"ig_{e.get('id', '')}" not in skip_ids]
        if before != len(selected):
            logger.info(
                "Skipping %d already-known reels; %d to process",
                before - len(selected),
                len(selected),
            )

    items: list[RawItem] = []
    scraped_at = _utc_now_iso()
    for entry in selected:
        try:
            item = _to_raw_item(entry, archive_dir=archive, scraped_at=scraped_at)
            _fetch_thumbnail(entry, dest_dir=archive / item.reel_id)
        except Exception:
            logger.exception("Failed to materialize reel %s", entry.get("id"))
            continue
        items.append(item)
        time.sleep(_THUMBNAIL_FETCH_SLEEP_SECONDS)
    return items


def pull_url(
    reel_url: str,
    *,
    archive_dir: Path | None = None,
    auth: CookieAuth | None = None,
    force: bool = False,
    candidates_path: Path | None = None,
) -> RawItem:
    archive = _resolve_archive_dir(archive_dir)
    auth = auth if auth is not None else CookieAuth.default()

    [entry] = _metadata_pass(reel_url, n=1, auth=auth)

    if not force:
        skip_ids = candidates_store.existing_ids(path=candidates_path)
        if f"ig_{entry.get('id', '')}" in skip_ids:
            raise FileExistsError(
                f"Candidate ig_{entry.get('id')} already present; pass force=True to re-extract"
            )

    item = _to_raw_item(entry, archive_dir=archive, scraped_at=_utc_now_iso())
    _fetch_thumbnail(entry, dest_dir=archive / item.reel_id)
    return item


# ---- pure helpers (heavily tested) ---------------------------------------

def _yt_dlp_opts(
    auth: CookieAuth,
    *,
    skip_download: bool = True,
    playlist_end: int | None = None,
) -> dict[str, Any]:
    """Build the options dict passed to yt_dlp.YoutubeDL.

    Kept pure / dependency-free so tests can introspect the cookie wiring
    without spinning up yt-dlp or hitting the network.
    """
    opts: dict[str, Any] = {
        "skip_download": skip_download,
        "extract_flat": False,  # we want full per-post metadata
        "quiet": True,
        "no_warnings": True,
    }
    if playlist_end is not None:
        opts["playlist_end"] = playlist_end

    if auth.cookies_file is not None:
        opts["cookiefile"] = str(auth.cookies_file)
    elif auth.cookies_from_browser is not None:
        # yt-dlp accepts a tuple: (browser, profile, keyring, container).
        # We only need the browser name; the rest defaults.
        opts["cookiesfrombrowser"] = (auth.cookies_from_browser,)

    return opts


def _select(
    entries: Iterable[dict[str, Any]],
    *,
    limit: int,
    rank_by: Literal["recent", "popularity"],
) -> list[dict[str, Any]]:
    """Pick `limit` entries from the metadata batch.

    `recent`: take entries in the order yt-dlp returned them (newest first).
    `popularity`: sort by play_count desc, fall back to like_count, then
    timestamp desc; missing values rank lowest.
    """
    items = list(entries)
    if rank_by == "popularity":
        items.sort(key=_popularity_sort_key, reverse=True)
    return items[:limit]


def _popularity_sort_key(entry: dict[str, Any]) -> tuple[int, int, int]:
    # Missing metrics fall to the bottom — use 0 instead of None so the sort
    # is total. timestamp goes last as a tiebreaker (UNIX seconds).
    play = entry.get("play_count") or 0
    likes = entry.get("like_count") or 0
    ts = entry.get("timestamp") or 0
    return (int(play), int(likes), int(ts))


def _to_raw_item(
    entry: dict[str, Any],
    *,
    archive_dir: Path,
    scraped_at: str,
) -> RawItem:
    reel_id = str(entry.get("id") or "").strip()
    if not reel_id:
        raise ValueError(f"yt-dlp entry missing id: {entry!r}")
    candidate_id = f"ig_{reel_id}"
    source_url = (
        entry.get("webpage_url")
        or f"https://www.instagram.com/reel/{reel_id}/"
    )
    return RawItem(
        reel_id=reel_id,
        candidate_id=candidate_id,
        source_url=source_url,
        thumbnail_path=archive_dir / reel_id / "cover.jpg",
        caption=str(entry.get("description") or "").strip(),
        play_count=_int_or_none(entry.get("play_count")),
        like_count=_int_or_none(entry.get("like_count")),
        posted_at=_iso_or_none(entry.get("timestamp")),
        scraped_at=scraped_at,
    )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso_or_none(timestamp: Any) -> str | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_archive_dir(archive_dir: Path | None) -> Path:
    return archive_dir if archive_dir is not None else _DEFAULT_ARCHIVE_DIR


# ---- IO wrappers (lightly tested, mocked at the boundary) ----------------

def _metadata_pass(url: str, *, n: int, auth: CookieAuth) -> list[dict[str, Any]]:
    """Run yt-dlp's metadata-only extraction. Returns one dict per post.

    Tests replace this function via monkeypatch so unit tests don't hit the
    network or require yt-dlp to be installed.
    """
    import yt_dlp  # imported lazily so unit tests can run without it

    opts = _yt_dlp_opts(auth, skip_download=True, playlist_end=n)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        return []
    if "entries" in info and info["entries"] is not None:
        return [e for e in info["entries"] if e is not None]
    return [info]


def _fetch_thumbnail(
    entry: dict[str, Any],
    *,
    dest_dir: Path,
    http_get: Callable[..., requests.Response] = requests.get,
) -> Path:
    """Download the cover thumbnail to `{dest_dir}/cover.jpg`. Also writes
    the full yt-dlp entry to `{dest_dir}/info.json` for audit."""
    thumbnail_url = entry.get("thumbnail")
    if not thumbnail_url:
        # Some Reels expose a `thumbnails` list; pick the largest.
        candidates = entry.get("thumbnails") or []
        if candidates:
            thumbnail_url = candidates[-1].get("url")
    if not thumbnail_url:
        raise ValueError(f"yt-dlp entry has no thumbnail: id={entry.get('id')!r}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    cover = dest_dir / "cover.jpg"
    response = http_get(thumbnail_url, timeout=15)
    response.raise_for_status()
    cover.write_bytes(response.content)

    # info.json is purely for audit; never read by the bot.
    import json

    (dest_dir / "info.json").write_text(json.dumps(entry, default=str), encoding="utf-8")
    return cover
