"""Where woodshed keeps stems and models."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from woodshed.paths import local_appdata


def cache_dir() -> Path:
    """WOODSHED_CACHE, else the platform cache folder."""
    if override := os.environ.get("WOODSHED_CACHE"):
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return local_appdata() / "woodshed" / "Cache"  # a missing or relative LOCALAPPDATA: the user's own
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "woodshed"
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    # The XDG spec ignores an empty or relative value.
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".cache"
    return base / "woodshed"
