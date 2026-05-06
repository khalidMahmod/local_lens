"""Tests for ingest.collectors.instagram — pure helpers + IO wrappers faked."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ingest import candidates_store
from ingest.collectors import instagram
from ingest.collectors.instagram import CookieAuth
from ingest.models import Candidate


# ---- CookieAuth ---------------------------------------------------------

def test_cookie_auth_default_uses_chrome():
    auth = CookieAuth.default()
    assert auth.cookies_from_browser == "chrome"
    assert auth.cookies_file is None


def test_cookie_auth_anonymous():
    auth = CookieAuth.anonymous()
    assert auth.cookies_from_browser is None
    assert auth.cookies_file is None


def test_cookie_auth_rejects_both_set():
    with pytest.raises(ValueError):
        CookieAuth(cookies_file=Path("a.txt"), cookies_from_browser="chrome")


# ---- _yt_dlp_opts -------------------------------------------------------

def test_opts_default_chrome_includes_cookiesfrombrowser():
    opts = instagram._yt_dlp_opts(CookieAuth.default())
    assert opts["cookiesfrombrowser"] == ("chrome",)
    assert "cookiefile" not in opts


def test_opts_with_file_path():
    opts = instagram._yt_dlp_opts(CookieAuth(cookies_file=Path("/tmp/cookies.txt")))
    assert opts["cookiefile"] == "/tmp/cookies.txt"
    assert "cookiesfrombrowser" not in opts


def test_opts_anonymous_has_no_cookie_keys():
    opts = instagram._yt_dlp_opts(CookieAuth.anonymous())
    assert "cookiesfrombrowser" not in opts
    assert "cookiefile" not in opts


def test_opts_includes_skip_download_by_default():
    opts = instagram._yt_dlp_opts(CookieAuth.anonymous())
    assert opts["skip_download"] is True


def test_opts_playlist_end_set_when_provided():
    opts = instagram._yt_dlp_opts(CookieAuth.anonymous(), playlist_end=42)
    assert opts["playlist_end"] == 42


def test_opts_playlist_end_omitted_when_none():
    opts = instagram._yt_dlp_opts(CookieAuth.anonymous(), playlist_end=None)
    assert "playlist_end" not in opts


def test_opts_explicit_browser_other_than_chrome():
    opts = instagram._yt_dlp_opts(CookieAuth(cookies_from_browser="firefox"))
    assert opts["cookiesfrombrowser"] == ("firefox",)


# ---- _select ranking ----------------------------------------------------

def test_select_recent_takes_first_n():
    entries = [{"id": str(i), "play_count": 10 - i} for i in range(5)]
    out = instagram._select(entries, limit=3, rank_by="recent")
    assert [e["id"] for e in out] == ["0", "1", "2"]


def test_select_recent_does_not_reorder():
    entries = [
        {"id": "low", "play_count": 1},
        {"id": "high", "play_count": 1000},
        {"id": "mid", "play_count": 50},
    ]
    out = instagram._select(entries, limit=10, rank_by="recent")
    assert [e["id"] for e in out] == ["low", "high", "mid"]


def test_select_popularity_sorts_by_play_count_desc():
    entries = [
        {"id": "low", "play_count": 100},
        {"id": "high", "play_count": 5000},
        {"id": "mid", "play_count": 800},
    ]
    out = instagram._select(entries, limit=10, rank_by="popularity")
    assert [e["id"] for e in out] == ["high", "mid", "low"]


def test_select_popularity_falls_back_to_likes_when_play_count_missing():
    entries = [
        {"id": "no-views", "like_count": 500},
        {"id": "many-views", "play_count": 800, "like_count": 5},
        {"id": "no-metrics"},
    ]
    out = instagram._select(entries, limit=10, rank_by="popularity")
    # play_count beats likes-only; likes-only beats nothing.
    assert [e["id"] for e in out] == ["many-views", "no-views", "no-metrics"]


def test_select_popularity_uses_timestamp_as_final_tiebreaker():
    entries = [
        {"id": "older", "play_count": 100, "like_count": 10, "timestamp": 1000},
        {"id": "newer", "play_count": 100, "like_count": 10, "timestamp": 2000},
    ]
    out = instagram._select(entries, limit=10, rank_by="popularity")
    assert [e["id"] for e in out] == ["newer", "older"]


def test_select_popularity_caps_at_limit():
    entries = [{"id": str(i), "play_count": i} for i in range(10)]
    out = instagram._select(entries, limit=3, rank_by="popularity")
    assert len(out) == 3
    assert [e["id"] for e in out] == ["9", "8", "7"]


def test_select_returns_empty_when_input_empty():
    assert instagram._select([], limit=5, rank_by="recent") == []
    assert instagram._select([], limit=5, rank_by="popularity") == []


# ---- _to_raw_item -------------------------------------------------------

def test_to_raw_item_maps_yt_dlp_entry():
    entry = {
        "id": "DCxAbc123",
        "webpage_url": "https://www.instagram.com/reel/DCxAbc123/",
        "description": "char kuey teow @ Jalan Imbi",
        "play_count": 12000,
        "like_count": 400,
        "timestamp": 1746000000,
    }
    archive = Path("/tmp/archive")
    item = instagram._to_raw_item(entry, archive_dir=archive, scraped_at="now")

    assert item.reel_id == "DCxAbc123"
    assert item.candidate_id == "ig_DCxAbc123"
    assert item.source_url == "https://www.instagram.com/reel/DCxAbc123/"
    assert item.thumbnail_path == archive / "DCxAbc123" / "cover.jpg"
    assert item.caption == "char kuey teow @ Jalan Imbi"
    assert item.play_count == 12000
    assert item.like_count == 400
    # timestamp 1746000000 → some 2025-04-30 UTC ISO string
    assert item.posted_at is not None
    assert item.posted_at.startswith("2025-04-30")
    assert item.scraped_at == "now"


def test_to_raw_item_falls_back_to_canonical_url_when_webpage_url_missing():
    entry = {"id": "ABC", "description": ""}
    item = instagram._to_raw_item(
        entry, archive_dir=Path("/tmp"), scraped_at="x"
    )
    assert item.source_url == "https://www.instagram.com/reel/ABC/"


def test_to_raw_item_handles_missing_play_and_like_counts():
    entry = {"id": "X", "description": ""}
    item = instagram._to_raw_item(entry, archive_dir=Path("/tmp"), scraped_at="x")
    assert item.play_count is None
    assert item.like_count is None
    assert item.posted_at is None


def test_to_raw_item_strips_caption_whitespace():
    entry = {"id": "X", "description": "  hello world  \n"}
    item = instagram._to_raw_item(entry, archive_dir=Path("/tmp"), scraped_at="x")
    assert item.caption == "hello world"


def test_to_raw_item_raises_when_id_missing():
    with pytest.raises(ValueError):
        instagram._to_raw_item(
            {"description": "no id"}, archive_dir=Path("/tmp"), scraped_at="x"
        )


def test_to_raw_item_handles_garbage_play_count_gracefully():
    entry = {"id": "X", "play_count": "not-a-number"}
    item = instagram._to_raw_item(entry, archive_dir=Path("/tmp"), scraped_at="x")
    assert item.play_count is None


# ---- pull_profile (with fakes) ------------------------------------------

def _fake_entry(id_: str, **overrides) -> dict[str, Any]:
    base = {
        "id": id_,
        "webpage_url": f"https://www.instagram.com/reel/{id_}/",
        "description": f"caption for {id_}",
        "thumbnail": f"https://cdn.example.com/{id_}.jpg",
        "play_count": 100,
        "like_count": 10,
        "timestamp": 1746000000,
    }
    base.update(overrides)
    return base


@pytest.fixture
def patched_io(monkeypatch: pytest.MonkeyPatch):
    """Replace _metadata_pass and _fetch_thumbnail with recorders."""
    state: dict[str, Any] = {"entries": [], "metadata_calls": [], "thumbnails": []}

    def fake_metadata(url, *, n, auth):
        state["metadata_calls"].append({"url": url, "n": n, "auth": auth})
        return list(state["entries"])

    def fake_fetch(entry, *, dest_dir, http_get=None):
        state["thumbnails"].append({"id": entry["id"], "dest_dir": dest_dir})
        dest_dir.mkdir(parents=True, exist_ok=True)
        cover = dest_dir / "cover.jpg"
        cover.write_bytes(b"FAKE-JPG-BYTES")
        return cover

    monkeypatch.setattr(instagram, "_metadata_pass", fake_metadata)
    monkeypatch.setattr(instagram, "_fetch_thumbnail", fake_fetch)
    monkeypatch.setattr(instagram, "_THUMBNAIL_FETCH_SLEEP_SECONDS", 0)
    return state


def test_pull_profile_returns_raw_items_for_each_selected(
    patched_io, tmp_path: Path
):
    patched_io["entries"] = [_fake_entry(f"id{i}") for i in range(5)]
    items = instagram.pull_profile(
        "https://instagram.com/test/",
        limit=5,
        archive_dir=tmp_path / "archive",
        candidates_path=tmp_path / "candidates.jsonl",
    )
    assert [i.reel_id for i in items] == ["id0", "id1", "id2", "id3", "id4"]
    assert len(patched_io["thumbnails"]) == 5


def test_pull_profile_thumbnails_land_under_archive_dir(
    patched_io, tmp_path: Path
):
    patched_io["entries"] = [_fake_entry("X")]
    archive = tmp_path / "archive"
    items = instagram.pull_profile(
        "https://instagram.com/test/",
        archive_dir=archive,
        candidates_path=tmp_path / "candidates.jsonl",
    )
    [item] = items
    assert item.thumbnail_path == archive / "X" / "cover.jpg"
    assert (archive / "X" / "cover.jpg").exists()


def test_pull_profile_metadata_pass_uses_window_for_popularity(
    patched_io, tmp_path: Path
):
    patched_io["entries"] = [_fake_entry(f"id{i}", play_count=i) for i in range(50)]
    instagram.pull_profile(
        "https://instagram.com/test/",
        limit=3,
        rank_by="popularity",
        window=50,
        archive_dir=tmp_path / "archive",
        candidates_path=tmp_path / "candidates.jsonl",
    )
    [call] = patched_io["metadata_calls"]
    assert call["n"] == 50  # window, not limit


def test_pull_profile_metadata_pass_uses_limit_for_recent(
    patched_io, tmp_path: Path
):
    patched_io["entries"] = [_fake_entry(f"id{i}") for i in range(7)]
    instagram.pull_profile(
        "https://instagram.com/test/",
        limit=7,
        rank_by="recent",
        archive_dir=tmp_path / "archive",
        candidates_path=tmp_path / "candidates.jsonl",
    )
    [call] = patched_io["metadata_calls"]
    assert call["n"] == 7


def test_pull_profile_default_auth_is_chrome(patched_io, tmp_path: Path):
    patched_io["entries"] = [_fake_entry("X")]
    instagram.pull_profile(
        "https://instagram.com/test/",
        archive_dir=tmp_path / "archive",
        candidates_path=tmp_path / "candidates.jsonl",
    )
    [call] = patched_io["metadata_calls"]
    assert call["auth"].cookies_from_browser == "chrome"


def test_pull_profile_explicit_anonymous_auth_passed_through(
    patched_io, tmp_path: Path
):
    patched_io["entries"] = [_fake_entry("X")]
    instagram.pull_profile(
        "https://instagram.com/test/",
        archive_dir=tmp_path / "archive",
        candidates_path=tmp_path / "candidates.jsonl",
        auth=CookieAuth.anonymous(),
    )
    [call] = patched_io["metadata_calls"]
    assert call["auth"].cookies_from_browser is None
    assert call["auth"].cookies_file is None


def test_pull_profile_skips_existing_candidates_by_default(
    patched_io, tmp_path: Path
):
    candidates = tmp_path / "candidates.jsonl"
    # Pre-populate the store with one of the reels we're about to "pull".
    candidates_store.append(
        Candidate(id="ig_id1", status="pending"), path=candidates
    )
    patched_io["entries"] = [_fake_entry(f"id{i}") for i in range(5)]

    items = instagram.pull_profile(
        "https://instagram.com/test/",
        archive_dir=tmp_path / "archive",
        candidates_path=candidates,
    )
    ids = [i.reel_id for i in items]
    assert "id1" not in ids
    assert len(ids) == 4
    # Thumbnail not fetched for the skipped reel.
    fetched_ids = [t["id"] for t in patched_io["thumbnails"]]
    assert "id1" not in fetched_ids


def test_pull_profile_force_disables_skip(patched_io, tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    candidates_store.append(
        Candidate(id="ig_id1", status="pending"), path=candidates
    )
    patched_io["entries"] = [_fake_entry(f"id{i}") for i in range(5)]

    items = instagram.pull_profile(
        "https://instagram.com/test/",
        archive_dir=tmp_path / "archive",
        candidates_path=candidates,
        force=True,
    )
    assert len(items) == 5
    assert "id1" in [i.reel_id for i in items]
    assert "id1" in [t["id"] for t in patched_io["thumbnails"]]


def test_pull_profile_continues_when_one_thumbnail_fetch_fails(
    monkeypatch: pytest.MonkeyPatch, patched_io, tmp_path: Path
):
    # Override _fetch_thumbnail to fail for one specific id.
    def fail_for_id1(entry, *, dest_dir, http_get=None):
        if entry["id"] == "id1":
            raise RuntimeError("CDN 404")
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "cover.jpg").write_bytes(b"x")

    monkeypatch.setattr(instagram, "_fetch_thumbnail", fail_for_id1)
    patched_io["entries"] = [_fake_entry(f"id{i}") for i in range(3)]

    items = instagram.pull_profile(
        "https://instagram.com/test/",
        archive_dir=tmp_path / "archive",
        candidates_path=tmp_path / "candidates.jsonl",
    )
    ids = [i.reel_id for i in items]
    assert ids == ["id0", "id2"]


# ---- pull_url (with fakes) ----------------------------------------------

def test_pull_url_returns_one_raw_item(patched_io, tmp_path: Path):
    patched_io["entries"] = [_fake_entry("DCxAbc123")]
    item = instagram.pull_url(
        "https://www.instagram.com/reel/DCxAbc123/",
        archive_dir=tmp_path / "archive",
        candidates_path=tmp_path / "candidates.jsonl",
    )
    assert item.reel_id == "DCxAbc123"
    assert item.candidate_id == "ig_DCxAbc123"
    assert (tmp_path / "archive" / "DCxAbc123" / "cover.jpg").exists()


def test_pull_url_raises_when_already_present_without_force(
    patched_io, tmp_path: Path
):
    candidates = tmp_path / "candidates.jsonl"
    candidates_store.append(Candidate(id="ig_DCxAbc123", status="pending"), path=candidates)
    patched_io["entries"] = [_fake_entry("DCxAbc123")]

    with pytest.raises(FileExistsError):
        instagram.pull_url(
            "https://www.instagram.com/reel/DCxAbc123/",
            archive_dir=tmp_path / "archive",
            candidates_path=candidates,
        )


def test_pull_url_force_overrides_existing(patched_io, tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    candidates_store.append(Candidate(id="ig_DCxAbc123", status="pending"), path=candidates)
    patched_io["entries"] = [_fake_entry("DCxAbc123")]

    item = instagram.pull_url(
        "https://www.instagram.com/reel/DCxAbc123/",
        archive_dir=tmp_path / "archive",
        candidates_path=candidates,
        force=True,
    )
    assert item.reel_id == "DCxAbc123"


# ---- _fetch_thumbnail (with fake http_get) ------------------------------

class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_fetch_thumbnail_writes_cover_and_info(tmp_path: Path):
    captured: dict = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse(b"JPEG-BYTES")

    entry = {"id": "X", "thumbnail": "https://cdn/x.jpg", "description": "hi"}
    cover = instagram._fetch_thumbnail(
        entry, dest_dir=tmp_path / "X", http_get=fake_get
    )
    assert cover == tmp_path / "X" / "cover.jpg"
    assert cover.read_bytes() == b"JPEG-BYTES"
    info = json.loads((tmp_path / "X" / "info.json").read_text(encoding="utf-8"))
    assert info["id"] == "X"
    assert captured["url"] == "https://cdn/x.jpg"


def test_fetch_thumbnail_falls_back_to_thumbnails_list(tmp_path: Path):
    entry = {
        "id": "X",
        "thumbnails": [
            {"url": "https://cdn/small.jpg"},
            {"url": "https://cdn/large.jpg"},
        ],
    }
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        return _FakeResponse(b"x")

    instagram._fetch_thumbnail(entry, dest_dir=tmp_path / "X", http_get=fake_get)
    # Picks the last (largest) entry.
    assert captured["url"] == "https://cdn/large.jpg"


def test_fetch_thumbnail_raises_when_no_thumbnail_available(tmp_path: Path):
    entry = {"id": "X"}  # no thumbnail key
    with pytest.raises(ValueError):
        instagram._fetch_thumbnail(
            entry, dest_dir=tmp_path / "X", http_get=lambda *a, **kw: _FakeResponse(b"")
        )


def test_fetch_thumbnail_raises_on_http_error(tmp_path: Path):
    entry = {"id": "X", "thumbnail": "https://cdn/x.jpg"}
    with pytest.raises(RuntimeError):
        instagram._fetch_thumbnail(
            entry,
            dest_dir=tmp_path / "X",
            http_get=lambda *a, **kw: _FakeResponse(b"", status_code=500),
        )
