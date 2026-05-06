# LocalLens — Ingestion v1 Design

## Goal

Grow `data/restaurants.json` beyond the 5 hand-written fixtures by pulling Reels from a curator's Instagram profile (initially `https://www.instagram.com/kl.foodie/`), running each through a vision-extractor to produce a structured Candidate, and exporting human-reviewed Candidates into the bot's runtime data.

This is a strict subset of the v1 ingestion track described in [the bot core spec](2026-05-04-locallens-design.md) (lines 400–499): Instagram-only, profile-feed pull (yt-dlp), local JSONL working surface (no Airtable), manual review, simple export. The spec's other sources (web RSS, YouTube, Apify, Facebook) and the verification gate (in-person visit, JAKIM check) are out of scope here — they can be added later without redesigning what's below.

## Non-goals

- Web / YouTube / Facebook collectors (single-profile IG only)
- Apify hashtag fanout (no automated discovery beyond one curator)
- Airtable working surface (local JSONL is the surface)
- Automatic geo / area / price-tier enrichment via Google Places (manual fill)
- Strict spec verification gate (in-person visit, JAKIM lookup) — v1 trusts the curator + manual review
- Scheduled `run-all` cron — v1 is on-demand only
- Multi-curator orchestration — one profile at a time

## Architecture

```
┌──────────────────────┐
│  ingest pull-profile │  yt-dlp metadata pass (no video download);
│  ingest add-url      │  fetch each cover thumbnail (~100 KB) into
│                      │  data/source_archive/{id}/
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  ingest extract      │  OpenAI vision: cover thumbnail + caption
│  (per reel)          │  → Candidate dict
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  data/candidates.    │  one Candidate per line; status=pending
│      jsonl           │  curator edits by hand, flips status=live
└──────────┬───────────┘
           ▼  (only status=live rows)
┌──────────────────────┐
│  ingest export       │  Candidate → Restaurant; merge by id
│                      │  into data/restaurants.json
└──────────────────────┘
```

New top-level package `ingest/`, peer to `bot/`. Same convention used in the bot core: pure-logic modules unit-tested, IO-heavy modules (yt-dlp, OpenAI) tested via fakes/fixtures. **No ffmpeg in the ingest path** — we work from cover thumbnails only, not video frames.

## Modules

### `ingest/cli.py`

`argparse` entry point. Subcommands:

```
python -m ingest pull-profile <profile_url>
    [--limit N] [--rank-by recent|popularity] [--window M] [--force]
    [--cookies PATH | --cookies-from-browser BROWSER | --no-cookies]

python -m ingest add-url <reel_url>
    [--force]
    [--cookies PATH | --cookies-from-browser BROWSER | --no-cookies]

python -m ingest extract [--id <candidate_id> | --all-pending]
python -m ingest export
```

`pull-profile` and `add-url` chain into `extract` automatically by default — pulling and extracting feel like one operation to the curator. `extract` is exposed standalone so failed extractions can be retried without re-fetching the thumbnail.

Defaults:
- `--limit`: 10
- `--rank-by`: `recent`
- `--window`: 50 (only meaningful when `--rank-by popularity`)
- `--force`: re-extract / re-download even if `id` already exists in `candidates.jsonl`
- **Auth: `--cookies-from-browser chrome`** is applied by default. yt-dlp reads the curator's logged-in IG session from Chrome's local profile so deeper pagination just works.

**Auth flags (mutually exclusive overrides of the default):**
- `--cookies PATH` — Netscape-format `cookies.txt` file. Get one via the "Get cookies.txt LOCALLY" Chrome extension or the Firefox equivalent: log into IG in the browser, click the extension on instagram.com, export. Save the file outside the repo or as `./cookies.txt` (gitignored).
- `--cookies-from-browser BROWSER` — explicitly point yt-dlp at a different browser: `firefox` / `chrome` / `safari` / `edge` / `brave`.
- `--no-cookies` — opt out of cookies entirely. Anonymous mode; capped at ~30–50 reels by IG's public pagination limits. Use this when Chrome isn't available or you specifically want a low-risk trial run.

**Chrome on macOS caveat:** Chrome locks its cookie store while running, so yt-dlp can't read it from a live process. **Quit Chrome before running `pull-profile`** (or use `--cookies-from-browser firefox` / a `cookies.txt` file instead). Linux Chrome and most other browsers don't have this restriction.

**With cookies (default):** profile pagination reaches the full archive (kl.foodie has ~1.5–2k posts). Slower — expect 30–60 min for the whole archive's metadata; yt-dlp paces requests to avoid IG flagging the session.

**Without cookies (`--no-cookies`):** capped at ~30–50 reels but lower-risk. Useful as a first run to validate extraction quality before pulling deeper, or for a fallback if Chrome isn't accessible.

**Security:** any cookie source is a live IG session. Anyone with the file (or browser profile) can act as you on IG. **Gitignore `cookies.txt`.** Sessions expire every 30–90 days — when yt-dlp starts failing on auth, re-login in Chrome (or re-export the file). Consider a dedicated IG account for ingestion if isolating risk from your personal account matters.

### `ingest/collectors/instagram.py`

Thin wrapper over yt-dlp. Two callables:

```python
@dataclass(frozen=True)
class CookieAuth:
    """At most one of cookies_file or cookies_from_browser is set.
    Both None → anonymous mode (no cookies passed to yt-dlp)."""
    cookies_file: Path | None = None
    cookies_from_browser: str | None = None  # "firefox", "chrome", etc.

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
    archive_dir: Path | None = None,    # defaults to data/source_archive/
    auth: CookieAuth | None = None,     # None → CookieAuth.default()
) -> list[RawItem]: ...


def pull_url(
    reel_url: str,
    *,
    archive_dir: Path | None = None,    # defaults to data/source_archive/
    auth: CookieAuth | None = None,     # None → CookieAuth.default()
) -> RawItem: ...
```

`RawItem` (dataclass, returned to the caller — never persisted):

```python
@dataclass(frozen=True)
class RawItem:
    reel_id: str             # e.g. "DCxAbc123" — Instagram shortcode
    candidate_id: str        # "ig_DCxAbc123"
    source_url: str
    thumbnail_path: Path     # data/source_archive/{reel_id}/cover.jpg
    caption: str             # full caption text from yt-dlp's info.json
    play_count: int | None
    like_count: int | None
    posted_at: str | None    # ISO timestamp from yt-dlp
    scraped_at: str          # ISO timestamp, set by collector
```

**Two-stage flow** (no video downloads):

1. **Metadata pass.** `yt-dlp --skip-download --print-json --playlist-end {N}` against the profile (or single URL). Returns one JSON object per post including `thumbnail` URL, `play_count`, `like_count`, `description` (caption), `timestamp`. For `popularity` ranking, `N = window`; for `recent`, `N = limit`. yt-dlp uses the cookies (if any) on this call.
2. **Rank + select.** For `popularity`: sort by `play_count` desc (fall back to `like_count`, then recency, on missing values), take top `limit`. For `recent`: take the first `limit` results as returned.
3. **Thumbnail fetch.** For each selected post, GET the `thumbnail` URL with `requests` and save to `data/source_archive/{reel_id}/cover.jpg`. Also save the post's full info JSON to `info.json` in the same directory for audit. Each thumbnail is ~50–200 KB.

Rate limits: 1-second sleep between thumbnail fetches (much lighter than the previous video-download path; thumbnails go through IG's CDN with normal caching behaviour). yt-dlp's metadata pagination is paced internally.

`pull_profile` skips reels whose `candidate_id` already lives in `candidates.jsonl`, unless `--force`. Skip-list is computed before the metadata pass — but yt-dlp returns the metadata page as a unit, so we filter post-fetch and only thumbnail-download the unskipped subset.

### `ingest/extractor.py`

```python
def extract(raw_item: RawItem, *, client=None, model=...) -> Candidate: ...
```

Steps:
1. **Image source.** Use the cover thumbnail at `data/source_archive/{reel_id}/cover.jpg`, already on disk after the collector ran. The cover is creator-chosen and on a food account is reliably the dish hero shot — for kl.foodie's content shape it's functionally equivalent to a middle frame, often more informative.
2. **Vision call.** Single call to OpenAI's chat completions API with the thumbnail (base64, `detail: low`) + the caption + the source URL as the user message. System prompt loaded from `prompts/extraction_prompt.txt`. Uses `response_format={"type": "json_object"}` so the parse never fails. Cost: ~$0.00025 per Candidate (gpt-4o-mini vision, ~750 input + 200 output tokens).
3. **Validation.** After parsing, check required keys + enum-ish fields (e.g., `halal_signals` ∈ `{no_pork_visible, pork_visible, unclear}`, `stall_name_confidence` ∈ `{high, medium, low}`). Missing/invalid → log a warning, write the Candidate with `extractor_notes` flagged for review.
4. **Output.** Returns a `Candidate` dataclass; the caller appends to `candidates.jsonl`.

Retry policy: one retry on OpenAI `RateLimitError` / 5xx with 5s backoff. Then write a stub Candidate with empty extracted fields and `extractor_notes: "extraction failed: <reason>"` — the run continues, the Candidate is visible in JSONL for inspection, and `--force` can re-extract later.

### `ingest/candidates_store.py`

JSONL append-only working surface at `data/candidates.jsonl` (gitignored — per-curator local state).

```python
# All paths default to data/candidates.jsonl when path is None.
def append(candidate: Candidate, *, path: Path | None = None) -> None: ...
def iter_all(*, status: str | None = None, path: Path | None = None) -> Iterator[Candidate]: ...
def existing_ids(*, path: Path | None = None) -> set[str]: ...
def replace_in_place(updated: Candidate, *, path: Path | None = None) -> None: ...
```

`replace_in_place` exists for the rare case where `extract` re-runs on a `--force` pull and we want to swap one row for another. Implementation: read all rows, replace by id, atomic write to `.jsonl.tmp` + `os.replace`. Inefficient at scale, fine for the MVP envelope (≤1,000 Candidates).

### `ingest/exporter.py`

```python
@dataclass(frozen=True)
class ExportResult:
    exported: int
    skipped_invalid: int
    total_live: int
    invalid_ids: list[str]

def export(
    *,
    candidates_path: Path | None = None,   # defaults to data/candidates.jsonl
    restaurants_path: Path | None = None,  # defaults to data/restaurants.json
) -> ExportResult: ...
```

Steps:
1. Read `candidates.jsonl`, filter `status == "live"`.
2. **Validate** each: required fields for the bot's `Restaurant` schema must be non-null:
   `lat`, `lng`, `area`, `cuisine`, `price_tier`, `meal_tags` (non-empty list), `indoor`, `vibe_tags` (non-empty list), `halal_status`, `google_maps_link`, `insider_tip`.
   No fallback for `insider_tip` — leaving it null forces the curator to engage with the differentiator field rather than silently shipping the model's `viral_hook` text. The curator can copy `viral_hook` into `insider_tip` deliberately if they want.
   Invalid rows: increment `skipped_invalid`, append id to `invalid_ids`, skip.
3. Build `Restaurant` dicts. `id = candidate.id` (e.g., `ig_DCxAbc123`). `name = stall_name`.
4. Read existing `restaurants.json`, merge by id: live Candidate row wins over an existing `ig_*` row; non-`ig_*` rows are preserved untouched (hand-curated entries are immune to ingestion).
5. Atomic write (`.json.tmp` + `os.replace`). Pretty-printed (2-space indent, sorted by id) so diffs are readable.
6. Return `ExportResult` for the CLI to print.

**Idempotency:** re-running `export` after editing a Candidate updates the corresponding Restaurant in place. To remove a place from the bot, set `status: rejected` (not enough — export only adds/updates, never deletes); also delete the row from `restaurants.json` by hand. This protects against accidental deletes from a typo'd status.

### `prompts/extraction_prompt.txt`

System prompt that:
- Defines the Candidate JSON schema the model must return
- Forbids inventing facts not visible in the cover thumbnail or caption
- Sets confidence fields (`stall_name_confidence`) to `low` when the name is ambiguous (caption mentions multiple, or none)
- Forbids guessing halal status — `halal_signals` is purely visual (no_pork_visible / pork_visible / unclear). The firm enum (`halal_status`) is left for the curator to fill.

Example (full version goes in the file):

> You are an extractor that turns Instagram Reels about Kuala Lumpur food spots into structured Candidate JSON. Given a single cover thumbnail and the post's caption, identify the stall/restaurant featured. Never invent details not present in the thumbnail or caption. Return JSON matching this schema: { ... }

## Data model

### Candidate (one JSONL line)

```json
{
  "id": "ig_DCxAbc123",
  "status": "pending",
  "source_url": "https://www.instagram.com/reel/DCxAbc123/",
  "source_platform": "instagram",
  "scraped_at": "2026-05-06T14:30:00+08:00",
  "thumbnail_path": "data/source_archive/DCxAbc123/cover.jpg",

  "stall_name": "Restoran Win Heng Seng",
  "stall_name_confidence": "high",
  "dish_featured": "Char kuey teow",
  "viral_hook": "Wok hei shot at 0:08, queue out the door",
  "claimed_must_order": "Char kuey teow with extra duck egg",
  "halal_signals": "no_pork_visible",
  "operating_hours_mentioned": "Closes 1pm",
  "google_maps_search_query": "Restoran Win Heng Seng Jalan Imbi",
  "candidate_quality_score": 8,
  "extractor_notes": "Caption inconsistent on stall name",

  "lat": null,
  "lng": null,
  "area": null,
  "cuisine": null,
  "price_tier": null,
  "meal_tags": null,
  "indoor": null,
  "vibe_tags": null,
  "halal_status": null,
  "google_maps_link": null,
  "insider_tip": null
}
```

Three blocks:

| Block | Source | Contents |
|---|---|---|
| Identity / provenance | Collector | `id`, `status`, `source_url`, `source_platform`, `scraped_at`, `thumbnail_path` |
| Extraction | OpenAI vision | `stall_name` … `extractor_notes` |
| Manual fill | Curator | `lat` … `insider_tip` |

`status` values: `pending` (just extracted), `live` (review complete, eligible for export), `rejected` (won't export, won't re-extract on `--force`).

### Storage layout

| Path | Contents | Committed? |
|---|---|---|
| `data/candidates.jsonl` | Working surface; one Candidate per line | No (gitignored) |
| `data/source_archive/{reel_id}/cover.jpg` | Reel cover thumbnail | No |
| `data/source_archive/{reel_id}/info.json` | yt-dlp metadata for the post | No |
| `cookies.txt` | Optional IG session cookies for deeper pagination | No (must be gitignored) |
| `data/restaurants.json` | What the bot reads | Yes |
| `prompts/extraction_prompt.txt` | Vision prompt | Yes |
| `ingest/**/*.py` | Pipeline modules | Yes |
| `tests/test_ingest_*.py` | Tests | Yes |

## CLI usage examples

```bash
# Default: 10 most recent reels, cookies pulled from Chrome's logged-in IG session.
# (Quit Chrome first on macOS — it locks its cookie store while running.)
python -m ingest pull-profile https://www.instagram.com/kl.foodie/

# Top 30 by views from the last 50 reels (still using Chrome cookies by default)
python -m ingest pull-profile https://www.instagram.com/kl.foodie/ \
    --limit 30 --rank-by popularity --window 50

# Override the default with a cookies.txt file
python -m ingest pull-profile https://www.instagram.com/kl.foodie/ \
    --cookies cookies.txt --limit 50

# Override with Firefox (e.g., on macOS while Chrome is open)
python -m ingest pull-profile https://www.instagram.com/kl.foodie/ \
    --cookies-from-browser firefox --limit 50

# Anonymous trial run — no cookies, capped at IG's public-pagination limit
python -m ingest pull-profile https://www.instagram.com/kl.foodie/ --no-cookies

# Re-extract after editing the prompt (uses thumbnails already on disk — no IG hit)
python -m ingest extract --all-pending

# After hand-editing candidates.jsonl to flip status=live on rows you've reviewed:
python -m ingest export
# → "exported: 7, skipped_invalid: 2, total_live: 9"
# (skipped rows have a missing required field — fix and re-run)
```

## Configuration

New optional env var:
- `INGEST_OPENAI_MODEL` — default `gpt-4o-mini`. Override for testing or upgrading.

Reused:
- `OPENAI_API_KEY` — same one the bot uses

System deps: yt-dlp is added to `requirements.txt`. **No ffmpeg required for the ingest path** (we work from cover thumbnails). The Phase 10 Dockerfile already installs ffmpeg for future video work — leave it; harmless.

Update `.gitignore` to add `cookies.txt` so a session file dropped in the project root never gets committed.

## Testing strategy

Pure-logic, hermetic, in pytest:

- `tests/test_ingest_candidates_store.py` — append, iter with status filter, dedup, atomic write, replace_in_place
- `tests/test_ingest_exporter.py` — fixture Candidates → assert restaurants.json delta. Cover: id collision overwrites, non-`ig_*` entries preserved, validation rejects rows missing required fields, deterministic sort
- `tests/test_ingest_extractor.py` — mock the OpenAI client; assert prompt + image are wired correctly; assert JSON parse errors land in `extractor_notes`; one happy-path test against a fixture cover image

Smoke-tested manually (no unit tests):
- `ingest.collectors.instagram.pull_profile` — real yt-dlp run against a real IG profile
- `ingest.cli` — argparse glue

## Error handling

| Scenario | Behaviour |
|---|---|
| yt-dlp can't fetch one reel's metadata | Log + skip; continue the batch |
| Thumbnail GET fails (CDN 404, network blip) | Log + skip; the Candidate stays out of JSONL |
| Cookies expired (yt-dlp 401 / login redirect) | Fail fast with a clear message: "IG session expired — re-login in Chrome, or pass `--no-cookies` for an anonymous run" |
| Chrome locked on macOS (default path can't read cookies) | Fail fast with: "Chrome cookie store locked — quit Chrome and retry, or use `--cookies-from-browser firefox` / `--no-cookies`" |
| OpenAI rate limit / 5xx | One retry @ 5s backoff; on second failure, write Candidate with empty extraction block + `extractor_notes` |
| `--limit` too aggressive | Default is low (10) — no hard cap, but the default protects from accidents |
| Candidate malformed JSON from model | `response_format=json_object` makes this rare; if it still happens, fall back to empty extraction block + `extractor_notes` |
| `export` finds invalid live row | Skip that row, surface its id in `ExportResult.invalid_ids` |
| Concurrent `pull-profile` runs | Out of scope — assume one curator on one machine. Atomic writes prevent corruption but races on `existing_ids` could double-extract; live with it for v1 |

## Compliance notes

- **ToS — cookied mode (default).** Using a logged-in session via Chrome / cookies.txt is what makes deep pagination possible, and it's also what IG's ToS technically prohibits for automated access. The default is set this way because the curator's intent is to grow the bot's data, not to spike anonymously. Mitigations: yt-dlp paces requests, single-profile usage on demand, no parallelism. Using a dedicated throwaway IG account is recommended if isolating risk from your personal account matters.
- **ToS — anonymous mode (`--no-cookies`).** yt-dlp metadata pass + thumbnail fetch on a public IG profile without auth is functionally indistinguishable from a power user browsing the app. Capped naturally by IG's public pagination limit (~30–50 posts). Lowest-risk path; use for trial runs or when cookies aren't accessible.
- **Source attribution:** every Candidate has `source_url` + `scraped_at`; every exported Restaurant carries its `ig_*` id back to the original Reel.
- **Republishing:** the bot describes places in its own words. Source thumbnails + captions are research input only; `data/source_archive/` never gets surfaced to users.
- **Halal:** `halal_signals` from the model is a hint only. The firm `halal_status` enum is curator-set; `halal_certified` should still mean JAKIM-verified per the bot core spec.

## Open questions / future work

- **Google Places enrichment** (option 2 from brainstorming): when manual fill becomes the bottleneck, add `ingest enrich <id>` that calls Google Places API for `lat` / `lng` / `area` / `google_maps_link`. Drops in cleanly because the manual block of the Candidate schema is field-by-field nullable.
- **Multi-source.** When a second curator profile or a YouTube / RSS feed is needed, add a sibling collector under `ingest/collectors/`. The Candidate schema already abstracts `source_platform`.
- **Airtable** for verification triage. When manual editing in `candidates.jsonl` feels slow, swap `candidates_store` for a pyairtable-backed implementation. The interface (`append`, `iter_all`, `existing_ids`, `replace_in_place`) is small and provider-agnostic.
- **Re-extract sweep.** A `ingest reverify --older-than 90d` to refresh stale Candidates (per the bot core spec's update cadence). Out of scope for v1.
- **Video frames.** If thumbnail-only ever leaves a quality gap (e.g., signboards revealed only mid-video, voiceover content), add `--with-video` to the collector to download the video and re-introduce ffmpeg frame extraction in the extractor. Whole opt-in path, doesn't disturb the default.

## Critical files

- This spec
- The bot core spec — [docs/superpowers/specs/2026-05-04-locallens-design.md](2026-05-04-locallens-design.md)
- Bot's restaurant schema — [bot/models.py](../../../bot/models.py)
- The bot's data file the export writes to — [data/restaurants.json](../../../data/restaurants.json)
