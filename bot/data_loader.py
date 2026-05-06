"""Load JSON data files into typed dataclasses; persist per-user sessions to disk."""

from __future__ import annotations

import json
import os
from pathlib import Path

from bot.models import Location, Package, Restaurant, Session


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _PROJECT_ROOT / "data"
SESSIONS_DIR = DATA_DIR / "sessions"


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_restaurants(path: Path | None = None) -> list[Restaurant]:
    target = path or (DATA_DIR / "restaurants.json")
    raw = _read_json(target)
    if not isinstance(raw, list):
        raise ValueError(f"{target} must contain a JSON list")
    return [Restaurant.from_dict(item) for item in raw]


def load_locations(path: Path | None = None) -> list[Location]:
    target = path or (DATA_DIR / "locations.json")
    raw = _read_json(target)
    if not isinstance(raw, list):
        raise ValueError(f"{target} must contain a JSON list")
    return [Location.from_dict(item) for item in raw]


def load_packages(path: Path | None = None) -> list[Package]:
    target = path or (DATA_DIR / "packages.json")
    raw = _read_json(target)
    if not isinstance(raw, list):
        raise ValueError(f"{target} must contain a JSON list")
    return [Package.from_dict(item) for item in raw]


def _session_path(user_id: str | int, sessions_dir: Path | None = None) -> Path:
    base = sessions_dir or SESSIONS_DIR
    return base / f"{user_id}.json"


def load_session(user_id: str | int, sessions_dir: Path | None = None) -> Session | None:
    path = _session_path(user_id, sessions_dir)
    if not path.exists():
        return None
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return Session.from_dict(raw)


def iter_sessions(sessions_dir: Path | None = None) -> list[Session]:
    """Read every session file in `sessions_dir`. Skips `.json.tmp` artifacts
    left over from interrupted writes. Used by the follow-up scheduler."""
    base = sessions_dir or SESSIONS_DIR
    if not base.exists():
        return []
    sessions: list[Session] = []
    for path in sorted(base.glob("*.json")):
        if path.name.endswith(".json.tmp"):
            continue
        raw = _read_json(path)
        if not isinstance(raw, dict):
            continue
        sessions.append(Session.from_dict(raw))
    return sessions


def save_session(session: Session, sessions_dir: Path | None = None) -> Path:
    base = sessions_dir or SESSIONS_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = _session_path(session.telegram_user_id, base)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)
    return path
