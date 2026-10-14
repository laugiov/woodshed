"""Stem separation: caching, progress, offline mode and errors (Demucs faked); one real run when installed."""

from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from tests import synth
from woodshed import stems
from woodshed.beats import MissingExtra

RATE = 44100


class FakeLoadModelError(Exception):
    pass


def install_fake_demucs(monkeypatch: pytest.MonkeyPatch, calls: dict[str, Any], fail_offline: bool = False) -> None:
    class Separator:
        samplerate = RATE

        def __init__(self, model: str, device: str, progress: bool, callback: Callable[[dict[str, Any]], None]) -> None:
            import os

            if fail_offline and os.environ.get("HF_HUB_OFFLINE") == "1":
                raise FakeLoadModelError("model not cached")
            calls["init"] = calls.get("init", 0) + 1
            calls["device"] = device
            self.callback = callback

        def separate_audio_file(self, file: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
            calls["file"] = file
            n = RATE // 2
            for offset in (0, n // 2):
                self.callback({"segment_offset": offset, "audio_length": n, "state": "end"})
            mix = np.zeros((2, n), dtype=np.float32)
            parts = {name: np.full((2, n), 0.1 * (i + 1), dtype=np.float32) for i, name in enumerate(stems.STEM_NAMES)}
            return mix, parts

    api = types.ModuleType("demucs.api")
    api.Separator = Separator  # type: ignore[attr-defined]
    api.LoadModelError = FakeLoadModelError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "demucs", types.ModuleType("demucs"))
    monkeypatch.setitem(sys.modules, "demucs.api", api)


@pytest.fixture
def song(tmp_path: Path) -> Path:
    return synth.write("pop", tmp_path / "in").wav


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "cache"
    monkeypatch.setenv("WOODSHED_CACHE", str(folder))
    return folder


def test_separation_writes_lossless_stems_and_reuses_the_cache(
    monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path
) -> None:
    calls: dict[str, Any] = {}
    install_fake_demucs(monkeypatch, calls)
    first = stems.separate(song)
    assert not first.from_cache and calls["init"] == 1 and calls["device"] == "cpu"
    assert set(first.paths) == set(stems.STEM_NAMES)
    for path in first.paths.values():
        info = sf.info(path)
        assert path.suffix == ".flac" and info.subtype == "PCM_24" and info.samplerate == RATE and info.channels == 2
        assert path.is_relative_to(cache)
    second = stems.separate(song)
    assert second.from_cache and calls["init"] == 1  # Demucs not run again


def test_cache_key_follows_the_file_content(tmp_path: Path) -> None:
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    a.write_bytes(b"one"), b.write_bytes(b"one")
    assert stems.fingerprint(a) == stems.fingerprint(b)
    b.write_bytes(b"two")
    assert stems.fingerprint(a) != stems.fingerprint(b)


def test_progress_is_reported_up_to_one(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    install_fake_demucs(monkeypatch, {})
    seen: list[float] = []
    stems.separate(song, progress=seen.append)
    assert seen == sorted(seen) and seen[-1] == 1.0 and all(0 <= p <= 1 for p in seen)


def test_offline_mode_refuses_to_download(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    install_fake_demucs(monkeypatch, {}, fail_offline=True)
    with pytest.raises(stems.StemsError, match="--offline"):
        stems.separate(song, offline=True)
    assert not any(cache.rglob("*.flac"))  # nothing half-written


def test_a_failed_separation_leaves_no_partial_cache(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    install_fake_demucs(monkeypatch, {})

    def boom(self: object, file: Path) -> None:
        raise RuntimeError("out of memory")

    monkeypatch.setattr(sys.modules["demucs.api"].Separator, "separate_audio_file", boom)
    with pytest.raises(stems.StemsError, match="out of memory"):
        stems.separate(song)
    assert not any(cache.rglob("*.flac"))


def test_missing_extra_explains_the_cpu_install(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    monkeypatch.setitem(sys.modules, "demucs", None)
    monkeypatch.setitem(sys.modules, "demucs.api", None)
    with pytest.raises(MissingExtra) as exc:
        stems.separate(song)
    message = str(exc.value)
    assert "woodshed[stems]" in message and "cpu" in message.lower()


def test_cache_dir_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WOODSHED_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert stems.cache_dir() == tmp_path / "xdg" / "woodshed"


@pytest.mark.skipif(importlib.util.find_spec("demucs") is None, reason="needs the stems extra")
def test_real_separation_on_a_synthetic_song(song: Path, cache: Path) -> None:
    result = stems.separate(song)
    drums, _ = sf.read(result.paths["drums"], always_2d=True)
    truth = synth.render("pop").stems["drums"]
    assert abs(drums.shape[0] / RATE - truth.size / synth.SR) < 0.05
