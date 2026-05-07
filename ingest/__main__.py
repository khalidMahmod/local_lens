"""Module entry point so `python -m ingest <subcommand>` works."""

from __future__ import annotations

import sys

from ingest.cli import main


if __name__ == "__main__":
    sys.exit(main())
