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


@dataclass(frozen=True)
class Model:
    """A Demucs separation: its key in woodshed's settings, its Demucs name, the stems it writes."""

    key: str
    name: str
    stems: tuple[str, ...]
    signature: str  # the checkpoint's id: a file named after it in the model cache means downloaded
    hub: str  # its Hugging Face repository


FOUR = Model("four", "htdemucs", ("drums", "bass", "other", "vocals"), "955717e8", "adefossez/HTDemucs")
# The guitar in its own stem; the piano too, though weak: the keys part is piano + other (spec 010).
SIX = Model(
    "six", "htdemucs_6s", ("drums", "bass", "other", "vocals", "guitar", "piano"), "5c90dfd2", "adefossez/HTDemucs-6s"
)
MODELS = {m.key: m for m in (FOUR, SIX)}
DEFAULT = SIX  # for a new page; a page keeps the model it was separated with


def model_of(settings: dict[str, Any]) -> Model:
    """The model a page was separated with: written as `separation` since six stems; absent means four."""
    return MODELS.get(str(settings.get("separation")), FOUR)


def downloaded(model: Model) -> bool:
    """The model's weights are in woodshed's model cache: a torch hub checkpoint or a Hugging Face snapshot file
    named after its signature."""
    partial = (".partial", ".incomplete", ".lock")  # a download cut short is not the model
    return any(not p.name.endswith(partial) for p in (cache_dir() / "models").rglob(f"{model.signature}*"))


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
    model: Model = FOUR


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


def folder_of(source: str, model: Model) -> Path:
    """The cache folder of a recording's stems, by its fingerprint and the model that separated it."""
    return cache_dir() / "stems" / f"{model.name}-{source}"


def _folder(src: Path, model: Model) -> Path:
    return folder_of(fingerprint(src), model)


def cached(path: str | Path, model: Model) -> Stems | None:
    """The stems of this recording if they are already separated, else None (nothing is computed)."""
    folder = _folder(Path(path).expanduser().resolve(), model)
    paths = {name: folder / f"{name}.flac" for name in model.stems}
    if not _usable(folder, paths):
        return None
    return Stems(folder, paths, from_cache=True, gain=_read_gain(folder) or 1.0, model=model)


def separate(
    path: str | Path,
    model: Model,
    *,
    offline: bool = False,
    progress: Callable[[float], None] | None = None,
) -> Stems:
    """Separate the model's stems (drums, bass, other, vocals; guitar and piano too with six). Cached: a song is
    only separated once per model."""
    src = Path(path).expanduser().resolve()
    hit = cached(src, model)
    if hit is not None:
        if progress:
            progress(1.0)
        return hit
    folder = _folder(src, model)
    paths = {name: folder / f"{name}.flac" for name in model.stems}
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
            separator = Separator(model=model.name, device="cpu", progress=False, callback=on_progress)
            import torch

            _, separated = separator.separate_tensor(torch.from_numpy(stereo), RATE)
        signals = {name: _as_array(separated[name]) for name in model.stems}
        gain = common_gain(signals)
        for name, signal in signals.items():
            # Lossless 24-bit FLAC: the stems are what the musician hears, quality is not traded.
            sf.write(tmp / f"{name}.flac", (signal * gain).T, separator.samplerate, subtype="PCM_24")
        (tmp / GAIN_FILE).write_text(json.dumps({"gain": gain}), encoding="utf-8")
        _publish(tmp, folder, paths)
    except Exception as exc:  # Demucs and torch raise plain RuntimeError, OSError...
        refusal = offline_cause(exc)
        if refusal is not None:  # Demucs wraps a refused download in LoadModelError
            other = "" if model is FOUR else " (or --separation four: the four-instrument model, if it is on disk)"
            raise StemsError(f"{refusal}{other}") from exc
        if isinstance(exc, LoadModelError):
            raise StemsError(f"could not load the {model.name} model: {exc}") from exc
        raise StemsError(f"separation failed: {exc}") from exc
    finally:  # also on Ctrl-C, the likely way to stop a long CPU separation
        shutil.rmtree(tmp, ignore_errors=True)
    if progress:
        progress(1.0)
    return Stems(folder, paths, from_cache=False, gain=_read_gain(folder) or 1.0, model=model)


def _usable(folder: Path, paths: dict[str, Path]) -> bool:
    """All the model's stems and a readable gain: an entry the cache can serve."""
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
