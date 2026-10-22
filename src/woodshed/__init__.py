"""woodshed: turn any song file into a local practice room."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.3.0"
__all__ = ["__version__", "analyze"]

if TYPE_CHECKING:
    from woodshed.analysis import analyze


def __getattr__(name: str) -> Any:
    # Imported on first use: `woodshed --version` must not wait for librosa to load.
    if name == "analyze":
        from woodshed.analysis import analyze

        return analyze
    raise AttributeError(f"module 'woodshed' has no attribute {name!r}")
