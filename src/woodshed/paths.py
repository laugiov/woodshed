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


def chosen_tools() -> Path | None:
    """WOODSHED_TOOLS when it names a folder on its own: absolute, or under the home folder (~ or ~/...). A
    relative value would depend on where woodshed started, and ~user is not expanded by the installers' shells:
    both are ignored, as XDG ignores a relative XDG_DATA_HOME."""
    value = os.environ.get("WOODSHED_TOOLS", "")
    if value == "~" or value.startswith(("~/", "~\\")):
        return Path.home() / value[2:] if len(value) > 2 else Path.home()
    return Path(value) if value and Path(value).is_absolute() else None


def default_tools_dir(system: str | None = None) -> Path:
    system = system or sys.platform
    if system == "win32":
        return local_appdata() / "woodshed" / "tools"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "woodshed" / "tools"
    return data_home() / "woodshed" / "tools"


def tools_dir(system: str | None = None) -> Path:
    """WOODSHED_TOOLS (see chosen_tools), else ~/Library/Application Support/woodshed/tools (Mac),
    %LOCALAPPDATA%\\woodshed\\tools (Windows) or $XDG_DATA_HOME/woodshed/tools (Linux)."""
    return chosen_tools() or default_tools_dir(system)


# The Rubber Band files the installers put in the tools folder (breakfastquay.com's 4.0.0 builds), by sha256:
# the uninstall removes a file of these names only when it is this one. install.sh (get_rubberband) and
# install.ps1 (Get-Rubberband) pin the same values (tests/test_paths.py checks).
RUBBER_BAND_SHA256 = {
    "rubberband": "bffe8a37f204958352e768fc4a751d3dbce18e3b42c2a3427a80498e7d8cee79",  # macOS
    "rubberband.exe": "d26d81e20f48ea33070e638f58bdeb6a61ce7f0946d8f2629f30441caa2905d1",  # Windows
    "sndfile.dll": "4e3bd2de8e1485110eaebef8e1239471f73d608773831c323bf528e05645655e",  # Windows, beside it
}
