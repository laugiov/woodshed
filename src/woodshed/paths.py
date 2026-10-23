"""Where woodshed keeps the programs it adds: one tools folder for the installers, the singer's key (the Rubber
Band program, spec 017) and the uninstall (spec 018). scripts/install.sh (woodshed_tools_dir) and
scripts/install.ps1 (Get-WoodshedTools) compute the same folder."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def absolute_env(name: str) -> Path | None:
    """A folder named by the environment, if absolute: a relative one would depend on where woodshed started
    (the XDG spec ignores it too)."""
    value = os.environ.get(name, "")
    return Path(value) if value and Path(value).is_absolute() else None


def data_home() -> Path:
    return absolute_env("XDG_DATA_HOME") or Path.home() / ".local" / "share"


def local_appdata() -> Path:
    return absolute_env("LOCALAPPDATA") or Path.home() / "AppData" / "Local"


def tools_dir(system: str | None = None) -> Path:
    """WOODSHED_TOOLS, else ~/Library/Application Support/woodshed/tools (Mac),
    %LOCALAPPDATA%\\woodshed\\tools (Windows) or $XDG_DATA_HOME/woodshed/tools (Linux)."""
    if override := os.environ.get("WOODSHED_TOOLS"):
        return Path(override).expanduser()
    system = system or sys.platform
    if system == "win32":
        return local_appdata() / "woodshed" / "tools"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "woodshed" / "tools"
    return data_home() / "woodshed" / "tools"
