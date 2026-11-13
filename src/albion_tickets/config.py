"""Fixed settings. Nothing personal lives here: the points total is in data/."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_URL = "https://www.brightonandhovealbion.com"
ALLOWED_HOST = "www.brightonandhovealbion.com"
USER_AGENT = "albion-tickets/0.1 (personal reminder tool)"
REQUEST_TIMEOUT = 20
REQUEST_PAUSE_S = 2

# Set from the source recon (docs/superpowers/notes/2026-11-13-source-recon.md).
LISTING_PATHS: list[str] = ["/all-latest-news"]

TZ = ZoneInfo("Europe/London")
CALENDAR_NAME = "Albion tickets"

REPO_DIR = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """Where all local state lives. ALBION_DATA_DIR overrides (used by tests)."""
    override = os.environ.get("ALBION_DATA_DIR")
    return Path(override) if override else REPO_DIR / "data"
