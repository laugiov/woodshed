"""Stem separation with Demucs (stems extra), cached by audio content, stored as lossless FLAC."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from woodshed.beats import MissingExtra

STEM_NAMES = ("drums", "bass", "other", "vocals")
MODEL = "htdemucs"
CPU_HINT = (
    'stem separation needs the stems extra: pipx install "woodshed[stems]". '
    "To avoid a 5 GB CUDA download, install PyTorch for CPU: "
    'uv tool install "woodshed[stems]" --torch-backend=cpu, '
    "or pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu first"
)


class StemsError(Exception):
    """Separation failed or could not start."""


@dataclass(frozen=True)
class Stems:
    folder: Path
    paths: dict[str, Path]
    from_cache: bool


def cache_dir() -> Path:
    """WOODSHED_CACHE, else the platform cache folder."""
    if override := os.environ.get("WOODSHED_CACHE"):
        return Path(override)
    if sys.platform == "win32" and (local := os.environ.get("LOCALAPPDATA")):
        return Path(local) / "woodshed" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "woodshed"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "woodshed"


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:20]


def _as_array(x: Any) -> np.ndarray:
    return np.asarray(x.detach().cpu().numpy() if hasattr(x, "detach") else x, dtype=np.float32)


def separate(
    path: str | Path,
    *,
    offline: bool = False,
    progress: Callable[[float], None] | None = None,
    model: str = MODEL,
) -> Stems:
    """Separate drums, bass, other and vocals. Cached: a song is only separated once."""
    src = Path(path).expanduser().resolve()
    folder = cache_dir() / "stems" / f"{model}-{fingerprint(src)}"
    paths = {name: folder / f"{name}.flac" for name in STEM_NAMES}
    if all(p.exists() for p in paths.values()):
        if progress:
            progress(1.0)
        return Stems(folder, paths, from_cache=True)

    try:
        from demucs.api import LoadModelError, Separator
    except ImportError as exc:
        raise MissingExtra(CPU_HINT) from exc

    def on_progress(info: dict[str, Any]) -> None:
        if progress and info.get("audio_length"):
            progress(min(1.0, float(info["segment_offset"]) / float(info["audio_length"])))

    previous = os.environ.get("HF_HUB_OFFLINE")
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        separator = Separator(model=model, device="cpu", progress=False, callback=on_progress)
    except LoadModelError as exc:
        hint = " The model is not downloaded yet: run once without --offline." if offline else ""
        raise StemsError(f"could not load the {model} model ({exc}).{hint}") from exc
    finally:
        if offline:
            if previous is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous

    folder.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=folder.name + ".", dir=folder.parent))
    try:
        _, separated = separator.separate_audio_file(src)
        for name in STEM_NAMES:
            # Lossless 24-bit FLAC: the stems are what the musician hears, quality is not traded.
            sf.write(tmp / f"{name}.flac", _as_array(separated[name]).T, separator.samplerate, subtype="PCM_24")
        tmp.replace(folder)
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise StemsError(f"separation failed: {exc}") from exc
    if progress:
        progress(1.0)
    return Stems(folder, paths, from_cache=False)
