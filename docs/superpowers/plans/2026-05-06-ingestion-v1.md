# Ingestion v1 — Phased Implementation Plan

> **For agentic workers:** Execute one phase per session. Use `superpowers:executing-plans` when you have an isolated worktree, otherwise just work through the deliverables and run the verify step at the end. Stop the session once verify passes.

## Context

Spec: [docs/superpowers/specs/2026-05-06-ingestion-v1-design.md](../specs/2026-05-06-ingestion-v1-design.md). Builds a local-JSONL ingestion pipeline that turns Reels from a single curator IG profile (initially [@kl.foodie](https://www.instagram.com/kl.foodie/)) into rows in `data/restaurants.json`. The bot core (Phases 1–10 of the prior plan) is complete and 165 tests pass — the ingestion track adds a new top-level package (`ingest/`) without touching `bot/` runtime code.

**Outcome after Phase 5:** `python -m ingest pull-profile https://www.instagram.com/kl.foodie/ --limit 10` populates `data/candidates.jsonl` with vision-extracted Candidates. The curator hand-edits the file to fill geo / classification fields and flips `status: live` on rows they want to ship. `python -m ingest export` writes those rows into `data/restaurants.json` for the bot to read.

**Decisions baked in (from brainstorming):**
- Single source: Instagram profile feed via yt-dlp
- Cover thumbnails only (no video downloads, no ffmpeg)
- Local JSONL working surface (no Airtable)
- Manual Candidate→Restaurant fill (no Google Places enrichment)
- Default auth: `--cookies-from-browser chrome` (with `--no-cookies` opt-out)

## Approach

5 phases, each one Claude Code session (~1–2 hours). Per-session prompt template:

> "Implement Phase N from `docs/superpowers/plans/2026-05-06-ingestion-v1.md`, referencing the spec at `docs/superpowers/specs/2026-05-06-ingestion-v1-design.md`. Stop when the verification step passes."

## Pre-flight (do once, before Phase 1)

- yt-dlp will be added to `requirements.txt` in Phase 4 — installation happens then via `.venv/bin/pip install -r requirements.txt`
- For the manual smoke test in Phase 4 / 5: Chrome should be logged into Instagram and **quit** before running `pull-profile` (Chrome locks its cookie store while alive on macOS)

---

## Phase 1 — Foundation: Candidate model + JSONL store

**Goal:** Pure-data scaffolding for the ingestion package. A Candidate dataclass with serialization, an append-only JSONL store, gitignore hygiene. No network, no OpenAI, no yt-dlp yet.

**Deliverables:**
- `ingest/__init__.py` — empty package marker
- `ingest/models.py`:
  - `Candidate` dataclass with three blocks (identity / extraction / manual fill) per spec lines 213–247. Constants: `STATUS_VALUES = {"pending", "live", "rejected"}`, `HALAL_SIGNALS = {"no_pork_visible", "pork_visible", "unclear", None}`, `STALL_NAME_CONFIDENCE = {"high", "medium", "low", None}`. `from_dict` / `to_dict` round-trip (None values preserved). Validate `status`, `halal_signals`, `stall_name_confidence` enums on construction.
  - `RawItem` dataclass per spec lines 117–129 — transient (never persisted), so no from_dict / to_dict. Frozen.
- `ingest/candidates_store.py` — module-level constant `DEFAULT_PATH = data/candidates.jsonl`. Functions: `append(candidate, *, path=None)`, `iter_all(*, status=None, path=None) -> Iterator[Candidate]`, `existing_ids(*, path=None) -> set[str]`, `replace_in_place(updated, *, path=None)`. Atomic writes (`.jsonl.tmp` + `os.replace`).
- `tests/test_ingest_models.py` — Candidate round-trip dict↔dataclass; Candidate enum validation rejects bad values; None preserved through round-trip; RawItem constructs cleanly with all required fields
- `tests/test_ingest_candidates_store.py` — append + iter_all reads back; status filter; existing_ids dedup; replace_in_place swaps one row by id; missing file = empty set / empty iter; atomic write doesn't leave .tmp on success
- Update `.gitignore`: add `data/candidates.jsonl`, `data/source_archive/`, `cookies.txt`

**Reuses:** `bot/data_loader.py`'s atomic-write pattern (write to `.tmp`, `os.replace`). Same `_PROJECT_ROOT` style for default paths.

**Verify:** `.venv/bin/python -m pytest tests/test_ingest_models.py tests/test_ingest_candidates_store.py -v` passes.

---

## Phase 2 — Extractor + system prompt

**Goal:** Given a `RawItem` (image path + caption + URL), call OpenAI vision once and produce a Candidate's middle block. Mockable for tests; real call works against gpt-4o-mini.

**Deliverables:**
- `ingest/extractor.py` — `extract(raw_item, *, client=None, model=None) -> Candidate`. Imports `RawItem` and `Candidate` from `ingest.models`. Default model from env `INGEST_OPENAI_MODEL` (fallback `gpt-4o-mini`). When `client` is None, build `openai.OpenAI()` from `OPENAI_API_KEY`. Reads thumbnail file as base64, sends with caption + URL as user message. System prompt loaded from `prompts/extraction_prompt.txt`. Uses `response_format={"type": "json_object"}`. Validates extracted JSON against the middle-block keys per spec; missing/invalid → write Candidate with `extractor_notes: "extraction failed: <reason>"` and zeroed extraction fields. One retry on `RateLimitError` / 5xx with 5s backoff.
- `prompts/extraction_prompt.txt` — vision system prompt per spec lines 199–209. Pins the JSON schema; forbids inventing facts not visible in thumbnail or caption; rules for `stall_name_confidence` ∈ {high, medium, low}; `halal_signals` purely visual ∈ {no_pork_visible, pork_visible, unclear}.
- `tests/test_ingest_extractor.py` — fake OpenAI client (records the request, returns canned content). Cases:
  - Happy path: model returns valid JSON → Candidate gets all middle-block fields populated, `status="pending"`
  - Model returns malformed JSON: extraction failure recorded in `extractor_notes`, identity block still populated
  - Image is base64-encoded and sent under `image_url` content part
  - System prompt content from `prompts/extraction_prompt.txt` is in the request
  - Rate-limit error → retried once, then graceful failure
- `tests/fixtures/thumbnails/sample_dish.jpg` — a tiny placeholder image (~1KB, can be a 1×1 JPG). Used as thumbnail in tests.

**Reuses:** `bot/llm_client.py` patterns for prompt loading + OpenAI client construction (don't import; mirror the pattern so `bot/` and `ingest/` stay decoupled).

**Verify:** `.venv/bin/python -m pytest tests/test_ingest_extractor.py -v` passes.

---

## Phase 3 — Exporter (Candidate → Restaurant merge)

**Goal:** `ingest export` reads `status=live` Candidates, builds Restaurant dicts, merges into `data/restaurants.json`. Hand-curated entries are preserved untouched.

**Deliverables:**
- `ingest/exporter.py`:
  - `@dataclass(frozen=True) class ExportResult: exported: int; skipped_invalid: int; total_live: int; invalid_ids: list[str]`
  - `REQUIRED_RESTAURANT_FIELDS = ("lat", "lng", "area", "cuisine", "price_tier", "meal_tags", "indoor", "vibe_tags", "halal_status", "google_maps_link", "insider_tip")` — non-null and (for list types) non-empty
  - `_candidate_to_restaurant(candidate) -> dict` — id = candidate.id, name = candidate.stall_name, fields copied from manual block. Raises `ValueError("missing field X")` if any required field is missing/empty.
  - `export(*, candidates_path=None, restaurants_path=None) -> ExportResult` — reads live Candidates, builds Restaurant dicts, reads existing `restaurants.json`, splits into `_ig_rows` (id starts with `ig_`) + `_curated_rows`, replaces `_ig_rows` with the new export, concatenates with `_curated_rows`, sorts by id, atomic-writes. Returns `ExportResult`.
- `tests/test_ingest_exporter.py`:
  - Empty candidates.jsonl → ExportResult(0, 0, 0, [])
  - One valid live Candidate + empty restaurants.json → restaurants.json has one row with `id="ig_X"`
  - Live Candidate with same id as an existing `ig_X` row → existing row replaced
  - Hand-curated `lot10-hutong-hokkien-mee` row in restaurants.json → preserved on export
  - Live Candidate with `lat=null` → skipped, id in `invalid_ids`, exported count doesn't increment
  - Live Candidate with `meal_tags=[]` → skipped (non-empty list required)
  - `pending` and `rejected` Candidates → ignored
  - Output JSON sorted by id; atomic write (no `.tmp` left on success)

**Reuses:** `bot/data_loader.py`'s `load_restaurants` (for reading existing `restaurants.json`), atomic write pattern from Phase 1.

**Verify:** `.venv/bin/python -m pytest tests/test_ingest_exporter.py -v` passes.

---

## Phase 4 — Instagram collector (yt-dlp + thumbnails + auth)

**Goal:** `pull_profile(profile_url, ...)` returns RawItems by running yt-dlp metadata pass, ranking, and downloading cover thumbnails. `pull_url(reel_url, ...)` does the same for one URL.

**Deliverables:**
- Update `requirements.txt`: add `yt-dlp>=2024.10.0` (latest stable). `requests` already present from bot core.
- `ingest/collectors/__init__.py` — empty package marker
- `ingest/collectors/instagram.py`:
  - `@dataclass(frozen=True) class CookieAuth: cookies_file: Path | None = None; cookies_from_browser: str | None = None`. `@classmethod default()` returns `cls(cookies_from_browser="chrome")`. `@classmethod anonymous()` returns `cls()`.
  - `_yt_dlp_opts(auth, archive_dir, *, skip_download=True, playlist_end=None) -> dict` — pure helper that builds the yt-dlp options dict. Extracted so tests can introspect the cookie wiring without invoking yt-dlp.
  - `_metadata_pass(url, *, n, auth) -> list[dict]` — calls `yt_dlp.YoutubeDL(...).extract_info(url, download=False)` with the constructed opts. Returns `info["entries"]` (or `[info]` for a single-URL fetch). Wrapped so test fakes can replace it.
  - `_select(entries, *, limit, rank_by) -> list[dict]` — pure-logic ranker. `recent`: take first `limit`. `popularity`: sort by `play_count` desc, fall back to `like_count`, then `timestamp` recency, then take top `limit`.
  - `_fetch_thumbnail(url, dest_path) -> None` — `requests.get` with timeout, write to disk. Wrapped so tests can fake it.
  - `_to_raw_item(entry, archive_dir) -> RawItem` — pure: builds RawItem from yt-dlp entry dict + paths.
  - `pull_profile(profile_url, *, limit=10, rank_by="recent", window=50, archive_dir=None, auth=None, force=False) -> list[RawItem]` — wires the pieces. When `auth is None`, uses `CookieAuth.default()`. Skips entries whose `candidate_id` is in `existing_ids()` unless `force=True`. 1-second sleep between thumbnail fetches. Saves yt-dlp's full info dict to `info.json` next to `cover.jpg`.
  - `pull_url(reel_url, *, archive_dir=None, auth=None, force=False) -> RawItem` — same but single URL, no rank/select/limit logic.
- `tests/test_ingest_instagram.py` — pure-logic tests with fakes for `_metadata_pass` and `_fetch_thumbnail`:
  - `_select(rank_by="recent", limit=3)` returns first 3 entries in input order
  - `_select(rank_by="popularity")` sorts by play_count desc; missing play_count falls back to like_count; ties broken by timestamp desc
  - `_select(rank_by="popularity", limit=N)` returns at most N
  - `_to_raw_item` maps entry fields correctly: `id` → `reel_id`, `id` prefixed with `ig_` → `candidate_id`, `description` → `caption`, etc. Sets `scraped_at` to a UTC ISO timestamp.
  - `_yt_dlp_opts(auth=CookieAuth.default())` includes `cookiesfrombrowser=("chrome",)`
  - `_yt_dlp_opts(auth=CookieAuth(cookies_file=Path("cookies.txt")))` includes `cookiefile="cookies.txt"`
  - `_yt_dlp_opts(auth=CookieAuth.anonymous())` includes neither
  - `pull_profile` with fake `_metadata_pass` returning 5 entries + fake `_fetch_thumbnail` → returns 5 RawItems, thumbnails called 5 times
  - `pull_profile` with one entry already in `existing_ids` → skipped, only the rest are downloaded
  - `pull_profile(..., force=True)` with one entry already in `existing_ids` → no skipping, all 5 are downloaded

**Reuses:** `existing_ids` from Phase 1's `candidates_store`, `Candidate` (well, `RawItem`) from Phase 2's `ingest/types.py`.

**Verify:**
1. `.venv/bin/python -m pytest tests/test_ingest_instagram.py -v` passes
2. Manual smoke (optional, requires Chrome quit + IG login): `.venv/bin/python -c "from ingest.collectors.instagram import pull_profile; items = pull_profile('https://www.instagram.com/kl.foodie/', limit=2); print([i.candidate_id for i in items])"` returns 2 ids and creates 2 directories under `data/source_archive/`

---

## Phase 5 — CLI glue + end-to-end

**Goal:** Wrap everything in `python -m ingest <subcommand>`. End-to-end manual run on a real IG profile produces a Candidate that, after manual fill, exports cleanly into `data/restaurants.json`.

**Deliverables:**
- `ingest/__main__.py` — `from ingest.cli import main; main()` shim. So `python -m ingest <subcommand>` works.
- `ingest/cli.py`:
  - argparse setup with subcommands: `pull-profile`, `add-url`, `extract`, `export`
  - `pull-profile`: positional `profile_url`; flags `--limit`, `--rank-by`, `--window`, `--force`, mutually exclusive `--cookies` / `--cookies-from-browser` / `--no-cookies`. Default behavior when no auth flag: `CookieAuth.default()`. When `--no-cookies`: `CookieAuth.anonymous()`. After collecting, automatically run `extract` on each new RawItem and append the resulting Candidates to `candidates.jsonl`.
  - `add-url`: same auth flags, single URL, also chains into extract.
  - `extract`: standalone. `--id <candidate_id>` to extract one row by id (re-extract path); `--all-pending` to walk every `status=pending` Candidate and re-run extraction. Reads `thumbnail_path` from disk; doesn't re-fetch from IG. Uses `replace_in_place` to swap the row.
  - `export`: calls `exporter.export()`, prints `f"exported: {r.exported}, skipped_invalid: {r.skipped_invalid}, total_live: {r.total_live}"`. If `r.invalid_ids` is non-empty, prints them on the next line so the curator can find what's missing.
  - All subcommands log to stderr at INFO level so the curator sees per-reel progress (one line: `[3/10] ig_DCx... — extracting…`).
  - **Friendly error handling for the cookie failure modes from the spec error table.** Wrap `pull_profile` / `pull_url` calls in a try/except for `yt_dlp.utils.DownloadError` (and friends). Match against known error substrings:
    - `"login required"` / `"login_required"` / `"401"` → print to stderr: `IG session expired — re-login in Chrome, or pass --no-cookies for an anonymous run.` Exit 2.
    - `"could not copy"` / `"database is locked"` / `"unable to read browser cookies"` (Chrome's lock-on-running fingerprint on macOS) → print to stderr: `Chrome cookie store locked — quit Chrome and retry, or use --cookies-from-browser firefox / --no-cookies.` Exit 2.
    - Anything else → re-raise so the traceback shows.
- `tests/test_ingest_cli.py` — argparse glue, hermetic. Cases:
  - `pull-profile <url>` parses with `auth=CookieAuth.default()`
  - `pull-profile <url> --no-cookies` parses with `auth=CookieAuth.anonymous()`
  - `pull-profile <url> --cookies cookies.txt` parses with `auth=CookieAuth(cookies_file=Path("cookies.txt"))`
  - Mutually exclusive: `--cookies a --no-cookies` exits with non-zero
  - `extract --id ig_X` and `extract --all-pending` are mutually exclusive
  - `export` prints the ExportResult counts (mock the exporter, verify the formatting)
  - When the collector raises a `DownloadError` matching the "login required" pattern, the CLI prints the friendly cookies-expired message to stderr and exits 2
  - When the collector raises a `DownloadError` matching the "database is locked" pattern, the CLI prints the friendly Chrome-locked message to stderr and exits 2

**Reuses:** Everything from Phases 1–4. argparse is stdlib.

**Verify:**
1. `.venv/bin/python -m pytest` (full suite, including bot core) passes
2. **Manual end-to-end** (writes to disk, hits IG + OpenAI — costs ~$0.001):
   1. Quit Chrome (macOS); confirm Chrome is logged into IG
   2. `.venv/bin/python -m ingest pull-profile https://www.instagram.com/kl.foodie/ --limit 2`
   3. `cat data/candidates.jsonl` shows 2 lines with populated identity + extraction blocks; manual block all null
   4. Edit one Candidate by hand: fill `lat`, `lng`, `area`, `cuisine`, `price_tier`, `meal_tags`, `indoor`, `vibe_tags`, `halal_status`, `google_maps_link`, `insider_tip`; flip `status: live`
   5. `.venv/bin/python -m ingest export` prints `exported: 1, skipped_invalid: 1, total_live: 2` (the un-edited one is skipped on missing fields)
   6. `data/restaurants.json` now has a new row with id starting with `ig_`, alongside the original 5 hand-curated entries

---

## Out of scope (per spec § Non-goals)

- Web / YouTube / Facebook collectors
- Apify hashtag fanout
- Airtable working surface
- Google Places enrichment
- Strict verification gate (in-person visit, JAKIM lookup)
- Scheduled `run-all` cron
- Multi-curator orchestration
- Video downloads / ffmpeg frame extraction (deferred behind a future `--with-video` flag)

## Critical files

- **Spec (always reference):** [docs/superpowers/specs/2026-05-06-ingestion-v1-design.md](../specs/2026-05-06-ingestion-v1-design.md)
- **Bot core spec:** [docs/superpowers/specs/2026-05-04-locallens-design.md](../specs/2026-05-04-locallens-design.md)
- **Bot's runtime data target:** [data/restaurants.json](../../../data/restaurants.json)
- **Bot's Restaurant model (export must produce dicts compatible with this):** [bot/models.py](../../../bot/models.py)
- **Pure-logic modules (well-tested):** `ingest/models.py`, `ingest/candidates_store.py`, `ingest/exporter.py`, `ingest/collectors/instagram.py` (the `_select` / `_to_raw_item` / `_yt_dlp_opts` helpers)
- **IO-heavy modules (light tests, smoke-tested manually):** `ingest/extractor.py` (mocked OpenAI), `ingest/collectors/instagram.py::_metadata_pass` / `_fetch_thumbnail`
- **CLI surface:** `ingest/cli.py`, `ingest/__main__.py`

## End-to-end verification (after Phase 5)

1. **Anonymous run, low risk:** `.venv/bin/python -m ingest pull-profile https://www.instagram.com/kl.foodie/ --no-cookies --limit 5` produces 5 Candidates in `candidates.jsonl`. Spot-check a Candidate: `stall_name` matches what the Reel's caption says.
2. **Cookied run, deeper:** Quit Chrome (logged into IG). `.venv/bin/python -m ingest pull-profile https://www.instagram.com/kl.foodie/ --limit 30 --rank-by popularity --window 50` produces 30 Candidates ranked by view count.
3. **Round-trip to restaurants.json:** Hand-edit one Candidate to `status: live` with all required fields. `python -m ingest export` writes it into `data/restaurants.json`. Restart the bot; send `/start` and trigger a recommendation in the area of that restaurant — it should be eligible to surface.
4. **Re-extraction:** Edit `prompts/extraction_prompt.txt`. Run `python -m ingest extract --all-pending`. Each pending Candidate is re-extracted using the new prompt (no IG hits — thumbnails reused from disk).
