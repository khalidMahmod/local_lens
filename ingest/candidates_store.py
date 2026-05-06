"""Append-only JSONL working surface for ingestion Candidates.

One Candidate per line, gitignored. The curator edits the file by hand to fill
the manual block and flip `status: live`. Atomic writes use the same
`.tmp` + `os.replace` pattern as `bot.data_loader` so concurrent reads never
see a partial file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from ingest.models import Candidate


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = _PROJECT_ROOT / "data" / "candidates.jsonl"


def _resolve(path: Path | None) -> Path:
    return path if path is not None else DEFAULT_PATH


def append(candidate: Candidate, *, path: Path | None = None) -> None:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(candidate.to_dict(), ensure_ascii=False)
    with target.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def iter_all(
    *, status: str | None = None, path: Path | None = None
) -> Iterator[Candidate]:
    target = _resolve(path)
    if not target.exists():
        return
    with target.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            candidate = Candidate.from_dict(data)
            if status is not None and candidate.status != status:
                continue
            yield candidate


def existing_ids(*, path: Path | None = None) -> set[str]:
    target = _resolve(path)
    if not target.exists():
        return set()
    ids: set[str] = set()
    with target.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if "id" in data:
                ids.add(str(data["id"]))
    return ids


def replace_in_place(updated: Candidate, *, path: Path | None = None) -> None:
    """Swap one row by id, keeping every other row's bytes unchanged.

    Reads the whole file, rewrites it. Inefficient at scale, fine for the MVP
    envelope (≤1k candidates). Atomic via .tmp + os.replace.
    """
    target = _resolve(path)
    if not target.exists():
        raise FileNotFoundError(target)
    rows: list[dict] = []
    found = False
    with target.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if data.get("id") == updated.id:
                rows.append(updated.to_dict())
                found = True
            else:
                rows.append(data)
    if not found:
        raise KeyError(f"Candidate id {updated.id!r} not found in {target}")
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, target)
