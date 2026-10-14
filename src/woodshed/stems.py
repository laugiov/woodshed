"""Stem separation with Demucs (stems extra), cached by audio content, stored as lossless FLAC."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from woodshed import audio
from woodshed.cache import cache_dir
from woodshed.errors import MissingExtra, StemsError

STEM_NAMES = ("drums", "bass", "other", "vocals")
MODEL = "htdemucs"
CPU_HINT = (
    'stem separation needs the stems extra: pipx install "woodshed[stems]". '
    "To avoid a 5 GB CUDA download, install PyTorch for CPU: "
    'uv tool install "woodshed[stems]" --torch-backend=cpu, '
    "or pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu first"
)


@dataclass(frozen=True)
class Stems:
    folder: Path
    paths: dict[str, Path]
    from_cache: bool
    # Common gain applied so that no stem clips in 24-bit FLAC (Demucs output can exceed full
    # scale). Playing the stems at 1 / gain restores the original level.
    gain: float = 1.0


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:20]


def _as_array(x: Any) -> np.ndarray:
    return np.asarray(x.detach().cpu().numpy() if hasattr(x, "detach") else x, dtype=np.float32)


GAIN_FILE = "gain.json"
RATE = 44100  # Demucs models work at 44.1 kHz
CEILING = 0.999  # peak level of the loudest stem after the common gain


def _complete(paths: dict[str, Path]) -> bool:
    return all(p.exists() for p in paths.values())


def _read_gain(folder: Path) -> float | None:
    """The stored gain, or None when the file is unreadable (the entry is then separated again)."""
    try:
        gain = float(json.loads((folder / GAIN_FILE).read_text(encoding="utf-8"))["gain"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return gain if 0 < gain <= 1 else None


def common_gain(signals: dict[str, np.ndarray]) -> float:
    """1, or less when a stem peaks above full scale: one gain for all, so they still add up."""
    peak = max(float(np.max(np.abs(s))) if s.size else 0.0 for s in signals.values())
    return 1.0 if peak <= CEILING else CEILING / peak


def _folder(src: Path, model: str) -> Path:
    return cache_dir() / "stems" / f"{model}-{fingerprint(src)}"


def cached(path: str | Path, model: str = MODEL) -> Stems | None:
    """The stems of this recording if they are already separated, else None (nothing is computed)."""
    folder = _folder(Path(path).expanduser().resolve(), model)
    paths = {name: folder / f"{name}.flac" for name in STEM_NAMES}
    if not _usable(folder, paths):
        return None
    return Stems(folder, paths, from_cache=True, gain=_read_gain(folder) or 1.0)


def separate(
    path: str | Path,
    *,
    offline: bool = False,
    progress: Callable[[float], None] | None = None,
    model: str = MODEL,
) -> Stems:
    """Separate drums, bass, other and vocals. Cached: a song is only separated once."""
    src = Path(path).expanduser().resolve()
    hit = cached(src, model)
    if hit is not None:
        if progress:
            progress(1.0)
        return hit
    folder = _folder(src, model)
    paths = {name: folder / f"{name}.flac" for name in STEM_NAMES}
    try:  # before decoding: a missing extra must not cost a long decode first
        from demucs.api import LoadModelError, Separator
    except ImportError as exc:
        raise MissingExtra(CPU_HINT) from exc
    # Decoded by our own hardened decoder, never by Demucs's (which runs ffmpeg unrestricted).
    stereo = audio.load(src, sr=RATE, channels=2)
    from woodshed.models import offline_cause, torch_models

    def on_progress(info: dict[str, Any]) -> None:
        if progress and info.get("audio_length"):
            progress(min(1.0, float(info["segment_offset"]) / float(info["audio_length"])))

    folder.parent.mkdir(parents=True, exist_ok=True)
    # Written to a private folder, then renamed in one step: an interrupted or failed run never
    # leaves a half-written cache entry behind.
    tmp = Path(tempfile.mkdtemp(prefix=folder.name + ".", dir=folder.parent))
    try:
        with torch_models(offline):
            separator = Separator(model=model, device="cpu", progress=False, callback=on_progress)
            import torch

            _, separated = separator.separate_tensor(torch.from_numpy(stereo), RATE)
        signals = {name: _as_array(separated[name]) for name in STEM_NAMES}
        gain = common_gain(signals)
        for name, signal in signals.items():
            # Lossless 24-bit FLAC: the stems are what the musician hears, quality is not traded.
            sf.write(tmp / f"{name}.flac", (signal * gain).T, separator.samplerate, subtype="PCM_24")
        (tmp / GAIN_FILE).write_text(json.dumps({"gain": gain}), encoding="utf-8")
        _publish(tmp, folder, paths)
    except Exception as exc:  # Demucs and torch raise plain RuntimeError, OSError...
        refusal = offline_cause(exc)
        if refusal is not None:  # Demucs wraps a refused download in LoadModelError
            raise StemsError(str(refusal)) from exc
        if isinstance(exc, LoadModelError):
            raise StemsError(f"could not load the {model} model: {exc}") from exc
        raise StemsError(f"separation failed: {exc}") from exc
    finally:  # also on Ctrl-C, the likely way to stop a long CPU separation
        shutil.rmtree(tmp, ignore_errors=True)
    if progress:
        progress(1.0)
    return Stems(folder, paths, from_cache=False, gain=_read_gain(folder) or 1.0)


def _usable(folder: Path, paths: dict[str, Path]) -> bool:
    """All four stems and a readable gain: an entry the cache can serve."""
    return _complete(paths) and _read_gain(folder) is not None


def _publish(tmp: Path, folder: Path, paths: dict[str, Path]) -> None:
    try:
        tmp.replace(folder)
        return
    except OSError:
        # Another run on the same song finished first: its stems are as good as ours.
        if _usable(folder, paths):
            return
    # An incomplete folder (an interrupted older version, a stem deleted by hand) is moved aside,
    # never trusted and never left blocking the cache.
    stale = folder.with_name(f"{folder.name}.stale-{tmp.name.rsplit('.', 1)[-1]}")
    try:
        folder.replace(stale)
        tmp.replace(folder)
    except OSError:
        if not _usable(folder, paths):  # a concurrent run published in between: fine if usable
            raise
    finally:
        shutil.rmtree(stale, ignore_errors=True)
