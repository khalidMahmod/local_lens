"""Tests for ingest.cli — argparse glue, hermetic.

The CLI's IO collaborators (`instagram.pull_profile` / `instagram.pull_url`,
`extractor.extract`, `candidates_store.*`, `exporter.export`) are monkey-
patched so each test exercises only the wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from yt_dlp.utils import DownloadError

from ingest import cli
from ingest.collectors.instagram import CookieAuth
from ingest.exporter import ExportResult
from ingest.models import Candidate, RawItem


# ---- helpers -------------------------------------------------------------

def _stub_collector(monkeypatch: pytest.MonkeyPatch, items: list[RawItem] | None = None) -> dict:
    """Replace pull_profile + pull_url + extract + append with capturing fakes."""
    captured: dict[str, Any] = {"profile_calls": [], "url_calls": [], "appended": []}

    def fake_pull_profile(profile_url, **kwargs):
        captured["profile_calls"].append({"profile_url": profile_url, **kwargs})
        return items or []

    def fake_pull_url(reel_url, **kwargs):
        captured["url_calls"].append({"reel_url": reel_url, **kwargs})
        return (items or [_dummy_raw_item()])[0]

    def fake_extract(raw_item, **_kwargs):
        return Candidate(id=raw_item.candidate_id, status="pending")

    def fake_append(candidate, **_kwargs):
        captured["appended"].append(candidate)

    monkeypatch.setattr(cli.instagram, "pull_profile", fake_pull_profile)
    monkeypatch.setattr(cli.instagram, "pull_url", fake_pull_url)
    monkeypatch.setattr(cli.extractor, "extract", fake_extract)
    monkeypatch.setattr(cli.candidates_store, "append", fake_append)
    return captured


def _dummy_raw_item(candidate_id: str = "ig_FAKE1") -> RawItem:
    return RawItem(
        reel_id=candidate_id.removeprefix("ig_"),
        candidate_id=candidate_id,
        source_url=f"https://www.instagram.com/reel/{candidate_id.removeprefix('ig_')}/",
        thumbnail_path=Path(f"/tmp/{candidate_id}/cover.jpg"),
        caption="cap",
        play_count=None,
        like_count=None,
        posted_at=None,
        scraped_at="2026-05-06T00:00:00+00:00",
    )


# ---- pull-profile auth wiring -------------------------------------------

def test_pull_profile_default_uses_chrome_cookies(monkeypatch: pytest.MonkeyPatch):
    captured = _stub_collector(monkeypatch)
    cli.main(["pull-profile", "https://www.instagram.com/kl.foodie/"])

    [call] = captured["profile_calls"]
    assert call["auth"] == CookieAuth.default()
    assert call["auth"].cookies_from_browser == "chrome"


def test_pull_profile_no_cookies_uses_anonymous(monkeypatch: pytest.MonkeyPatch):
    captured = _stub_collector(monkeypatch)
    cli.main(["pull-profile", "https://x/", "--no-cookies"])

    [call] = captured["profile_calls"]
    assert call["auth"] == CookieAuth.anonymous()


def test_pull_profile_cookies_path_wired(monkeypatch: pytest.MonkeyPatch):
    captured = _stub_collector(monkeypatch)
    cli.main(["pull-profile", "https://x/", "--cookies", "cookies.txt"])

    [call] = captured["profile_calls"]
    assert call["auth"] == CookieAuth(cookies_file=Path("cookies.txt"))


def test_pull_profile_cookies_from_browser_wired(monkeypatch: pytest.MonkeyPatch):
    captured = _stub_collector(monkeypatch)
    cli.main(["pull-profile", "https://x/", "--cookies-from-browser", "firefox"])

    [call] = captured["profile_calls"]
    assert call["auth"] == CookieAuth(cookies_from_browser="firefox")


def test_pull_profile_passes_limit_rank_window_force(monkeypatch: pytest.MonkeyPatch):
    captured = _stub_collector(monkeypatch)
    cli.main(
        [
            "pull-profile",
            "https://x/",
            "--limit", "5",
            "--rank-by", "popularity",
            "--window", "20",
            "--force",
        ]
    )

    [call] = captured["profile_calls"]
    assert call["limit"] == 5
    assert call["rank_by"] == "popularity"
    assert call["window"] == 20
    assert call["force"] is True


# ---- mutually exclusive auth flags --------------------------------------

def test_cookies_and_no_cookies_mutually_exclusive(monkeypatch: pytest.MonkeyPatch):
    _stub_collector(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["pull-profile", "https://x/", "--cookies", "a.txt", "--no-cookies"])
    assert exc.value.code != 0


def test_cookies_and_cookies_from_browser_mutually_exclusive(monkeypatch: pytest.MonkeyPatch):
    _stub_collector(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "pull-profile", "https://x/",
            "--cookies", "a.txt",
            "--cookies-from-browser", "firefox",
        ])
    assert exc.value.code != 0


# ---- pull-profile chains into extract + append --------------------------

def test_pull_profile_chains_extract_and_append(monkeypatch: pytest.MonkeyPatch):
    items = [_dummy_raw_item("ig_A"), _dummy_raw_item("ig_B")]
    captured = _stub_collector(monkeypatch, items=items)

    rc = cli.main(["pull-profile", "https://x/"])

    assert rc == 0
    assert [c.id for c in captured["appended"]] == ["ig_A", "ig_B"]


# ---- add-url -------------------------------------------------------------

def test_add_url_default_chrome_cookies(monkeypatch: pytest.MonkeyPatch):
    captured = _stub_collector(monkeypatch, items=[_dummy_raw_item("ig_X")])
    cli.main(["add-url", "https://www.instagram.com/reel/X/"])

    [call] = captured["url_calls"]
    assert call["auth"] == CookieAuth.default()
    assert [c.id for c in captured["appended"]] == ["ig_X"]


def test_add_url_no_cookies(monkeypatch: pytest.MonkeyPatch):
    captured = _stub_collector(monkeypatch, items=[_dummy_raw_item("ig_X")])
    cli.main(["add-url", "https://www.instagram.com/reel/X/", "--no-cookies"])

    [call] = captured["url_calls"]
    assert call["auth"] == CookieAuth.anonymous()


# ---- extract -------------------------------------------------------------

def test_extract_id_and_all_pending_mutually_exclusive():
    with pytest.raises(SystemExit) as exc:
        cli.main(["extract", "--id", "ig_X", "--all-pending"])
    assert exc.value.code != 0


def test_extract_requires_one_of_id_or_all_pending():
    with pytest.raises(SystemExit) as exc:
        cli.main(["extract"])
    assert exc.value.code != 0


def test_extract_id_re_runs_and_replaces_in_place(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    thumb_dir = tmp_path / "ig_X"
    thumb_dir.mkdir()
    (thumb_dir / "cover.jpg").write_bytes(b"fakejpeg")
    (thumb_dir / "info.json").write_text(
        '{"description": "caption", "play_count": 100, "like_count": 5, "timestamp": 1700000000}',
        encoding="utf-8",
    )

    existing = Candidate(
        id="ig_X",
        status="live",
        source_url="https://x/",
        scraped_at="2026-05-06T00:00:00+00:00",
        thumbnail_path=str(thumb_dir / "cover.jpg"),
        # manual block already filled
        lat=3.14,
        lng=101.7,
        area="KLCC",
        cuisine="malay",
        price_tier="$",
        meal_tags=["lunch"],
        indoor=True,
        vibe_tags=["casual"],
        halal_status="halal_certified",
        google_maps_link="https://maps/",
        insider_tip="get the rendang",
    )

    monkeypatch.setattr(cli.candidates_store, "iter_all", lambda **_: iter([existing]))

    captured: dict[str, Any] = {"raw": None, "replaced": None}

    def fake_extract(raw_item, **_kw):
        captured["raw"] = raw_item
        return Candidate(
            id=raw_item.candidate_id,
            status="pending",
            stall_name="Fresh Name",
            stall_name_confidence="high",
        )

    def fake_replace(candidate, **_kw):
        captured["replaced"] = candidate

    monkeypatch.setattr(cli.extractor, "extract", fake_extract)
    monkeypatch.setattr(cli.candidates_store, "replace_in_place", fake_replace)

    rc = cli.main(["extract", "--id", "ig_X"])
    assert rc == 0

    raw = captured["raw"]
    assert isinstance(raw, RawItem)
    assert raw.candidate_id == "ig_X"
    assert raw.caption == "caption"
    assert raw.play_count == 100

    replaced = captured["replaced"]
    # extraction block updated
    assert replaced.stall_name == "Fresh Name"
    # status + manual block preserved
    assert replaced.status == "live"
    assert replaced.lat == 3.14
    assert replaced.insider_tip == "get the rendang"


def test_extract_id_unknown_returns_1(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cli.candidates_store, "iter_all", lambda **_: iter([]))
    rc = cli.main(["extract", "--id", "ig_NOPE"])
    assert rc == 1


def test_extract_all_pending_iterates_pending_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    thumb_dir = tmp_path / "ig_P"
    thumb_dir.mkdir()
    (thumb_dir / "cover.jpg").write_bytes(b"fakejpeg")

    pending = Candidate(
        id="ig_P",
        status="pending",
        source_url="https://x/",
        scraped_at="2026-05-06T00:00:00+00:00",
        thumbnail_path=str(thumb_dir / "cover.jpg"),
    )

    seen_filters: list[Any] = []

    def fake_iter_all(*, status=None, **_kw):
        seen_filters.append(status)
        return iter([pending] if status == "pending" else [])

    monkeypatch.setattr(cli.candidates_store, "iter_all", fake_iter_all)
    monkeypatch.setattr(cli.extractor, "extract", lambda raw, **_kw: Candidate(id=raw.candidate_id))

    replaced: list[Candidate] = []
    monkeypatch.setattr(
        cli.candidates_store, "replace_in_place", lambda c, **_kw: replaced.append(c)
    )

    rc = cli.main(["extract", "--all-pending"])
    assert rc == 0
    assert seen_filters == ["pending"]
    assert [c.id for c in replaced] == ["ig_P"]


# ---- export --------------------------------------------------------------

def test_export_prints_counts(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    monkeypatch.setattr(
        cli.exporter,
        "export",
        lambda: ExportResult(exported=2, skipped_invalid=1, total_live=3, invalid_ids=["ig_BAD"]),
    )

    rc = cli.main(["export"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "exported: 2, skipped_invalid: 1, total_live: 3" in out
    assert "ig_BAD" in out


def test_export_no_invalid_ids_skips_invalid_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    monkeypatch.setattr(
        cli.exporter,
        "export",
        lambda: ExportResult(exported=1, skipped_invalid=0, total_live=1, invalid_ids=[]),
    )

    cli.main(["export"])
    out = capsys.readouterr().out
    assert "exported: 1, skipped_invalid: 0, total_live: 1" in out
    # No second-line "invalid: ig_..." block when there are no invalid ids.
    assert "\ninvalid:" not in out


# ---- friendly cookie error handling -------------------------------------

def test_login_required_prints_friendly_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    def boom(*_a, **_kw):
        raise DownloadError("ERROR: Login required to access this content (401)")

    monkeypatch.setattr(cli.instagram, "pull_profile", boom)

    rc = cli.main(["pull-profile", "https://x/"])
    assert rc == 2

    err = capsys.readouterr().err
    assert "IG session expired" in err
    assert "--no-cookies" in err


def test_chrome_locked_prints_friendly_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    def boom(*_a, **_kw):
        raise DownloadError(
            "ERROR: Could not copy Chrome cookie database file: database is locked"
        )

    monkeypatch.setattr(cli.instagram, "pull_profile", boom)

    rc = cli.main(["pull-profile", "https://x/"])
    assert rc == 2

    err = capsys.readouterr().err
    assert "Chrome cookie store locked" in err
    assert "quit Chrome" in err


def test_unknown_download_error_re_raises(monkeypatch: pytest.MonkeyPatch):
    def boom(*_a, **_kw):
        raise DownloadError("ERROR: some other yt-dlp failure")

    monkeypatch.setattr(cli.instagram, "pull_profile", boom)

    with pytest.raises(DownloadError):
        cli.main(["pull-profile", "https://x/"])


def test_add_url_friendly_cookie_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    def boom(*_a, **_kw):
        raise DownloadError("ERROR: login_required")

    monkeypatch.setattr(cli.instagram, "pull_url", boom)

    rc = cli.main(["add-url", "https://x/"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "IG session expired" in err
