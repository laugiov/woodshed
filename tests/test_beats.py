"""Beat tracking, including the optional beat_this tracker (faked here; it needs the stems extra)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests import synth
from tests.fakes import download as fake_download
from tests.fakes import hub_dir, install_fake_torch
from woodshed import beats
from woodshed.errors import BeatError, MissingExtra, StemsError


@pytest.fixture(scope="module")
def pop(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return synth.write("pop", tmp_path_factory.mktemp("beat-songs")).wav


def install_fake_beat_this(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any], download: bool = False) -> None:
    class FakeFile2Beats:
        def __init__(self, checkpoint_path: str, device: str, dbn: bool) -> None:
            seen["init"] = (checkpoint_path, device, dbn)
            if download:
                fake_download("https://example.org/final0.ckpt")

        def __call__(self, path: str) -> tuple[list[float], list[float]]:
            seen["path"] = path
            assert Path(path).suffix == ".wav" and Path(path).exists()
            return [0.5, 1.0, 1.5, 2.0, 2.5], [0.5, 2.5]

    inference = types.ModuleType("beat_this.inference")
    inference.File2Beats = FakeFile2Beats  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "beat_this", types.ModuleType("beat_this"))
    monkeypatch.setitem(sys.modules, "beat_this.inference", inference)


def test_librosa_tracks_the_pop_song(pop: Path) -> None:
    from woodshed import audio

    tempo, times = beats.track_librosa(audio.load(pop))
    assert tempo == pytest.approx(120, rel=0.05)
    assert np.median(np.diff(times)) == pytest.approx(0.5, rel=0.05)


def test_silence_has_no_beats() -> None:
    with pytest.raises(BeatError):
        beats.track_librosa(np.zeros(22050 * 5, dtype=np.float32))


def test_beat_this_missing_gives_a_clear_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "beat_this", None)
    assert not beats.beat_this_available()
    with pytest.raises(MissingExtra, match=r"woodshed\[stems\]"):
        beats.track_beat_this(Path("song.wav"))


def test_beat_this_adapter_decodes_first_and_keeps_models_in_our_cache(
    monkeypatch: pytest.MonkeyPatch, pop: Path, tmp_path: Path
) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    install_fake_torch(monkeypatch)
    seen: dict[str, Any] = {}
    install_fake_beat_this(monkeypatch, seen)
    b, d = beats.track_beat_this(pop)
    assert seen["init"] == ("final0", "cpu", False)
    assert seen["path"] != str(pop) and not Path(str(seen["path"])).exists()  # re-encoded, then cleaned up
    assert list(d) == [0.5, 2.5] and len(b) == 5
    assert hub_dir() == "/default" and sys.modules["torch.hub"]._hub_dir is None  # torch restored as it was


def test_offline_beat_this_never_downloads(monkeypatch: pytest.MonkeyPatch, pop: Path, tmp_path: Path) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    torch_state = install_fake_torch(monkeypatch)
    install_fake_beat_this(monkeypatch, {}, download=True)
    with pytest.raises(StemsError, match="--offline"):
        beats.track_beat_this(pop, offline=True)
    assert torch_state["downloads"] == []


def test_library_failures_become_typed_errors(monkeypatch: pytest.MonkeyPatch, pop: Path, tmp_path: Path) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    install_fake_torch(monkeypatch)
    install_fake_beat_this(monkeypatch, {})

    def broken(self: object, path: str) -> None:
        raise ValueError("checkpoint mismatch")

    monkeypatch.setattr(sys.modules["beat_this.inference"].File2Beats, "__call__", broken)
    with pytest.raises(StemsError, match="checkpoint mismatch"):
        beats.track_beat_this(pop)


def test_a_refused_download_wrapped_by_beat_this_still_says_offline(
    monkeypatch: pytest.MonkeyPatch, pop: Path, tmp_path: Path
) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    install_fake_torch(monkeypatch)
    install_fake_beat_this(monkeypatch, {})
    real_init = sys.modules["beat_this.inference"].File2Beats.__init__

    def wrapping(self: object, *args: Any, **kwargs: Any) -> None:
        try:  # beat_this's load_checkpoint turns any failure into a ValueError
            fake_download("https://example.org/final0.ckpt")
        except Exception as exc:
            raise ValueError("Could not load the checkpoint given the provided name") from exc
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(sys.modules["beat_this.inference"].File2Beats, "__init__", wrapping)
    with pytest.raises(StemsError, match="--offline"):
        beats.track_beat_this(pop, offline=True)
