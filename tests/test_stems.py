"""Stem separation: caching, progress, offline mode and errors (Demucs faked); one real run when installed."""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from tests import synth
from tests.fakes import download, hub_dir, install_fake_torch
from woodshed import stems
from woodshed.errors import AudioError, MissingExtra, StemsError

RATE = 44100


class FakeLoadModelError(Exception):
    pass


def install_fake_demucs(monkeypatch: pytest.MonkeyPatch, calls: dict[str, Any], peak: float = 0.4) -> dict[str, Any]:
    torch_state = install_fake_torch(monkeypatch)

    class Separator:
        samplerate = RATE

        def __init__(self, model: str, device: str, progress: bool, callback: Callable[[dict[str, Any]], None]) -> None:
            download(f"https://example.org/{model}.th")  # as Demucs does on first use
            calls["init"] = calls.get("init", 0) + 1
            calls["model_dir"] = hub_dir()
            calls["device"] = device
            calls["model"] = model
            self.callback = callback
            self.stems = next(m.stems for m in stems.MODELS.values() if m.name == model)

        def separate_tensor(self, wav: np.ndarray, sr: int) -> tuple[np.ndarray, dict[str, np.ndarray]]:
            calls["input"] = (wav.shape, sr)
            n = RATE // 2
            for offset in (0, n // 2):
                self.callback({"segment_offset": offset, "audio_length": n, "state": "end"})
            mix = np.zeros((2, n), dtype=np.float32)
            levels = {name: peak * (i + 1) / len(self.stems) for i, name in enumerate(self.stems)}
            parts = {name: np.full((2, n), level, dtype=np.float32) for name, level in levels.items()}
            return mix, parts

    api = types.ModuleType("demucs.api")
    api.Separator = Separator  # type: ignore[attr-defined]
    api.LoadModelError = FakeLoadModelError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "demucs", types.ModuleType("demucs"))
    monkeypatch.setitem(sys.modules, "demucs.api", api)
    return torch_state


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
    first = stems.separate(song, stems.FOUR)
    assert not first.from_cache and calls["init"] == 1 and calls["device"] == "cpu"
    assert (
        calls["model_dir"] == str(cache / "models")
        and hub_dir() == "/default"
        and sys.modules["torch.hub"]._hub_dir is None
    )
    assert set(first.paths) == set(stems.FOUR.stems)
    for path in first.paths.values():
        info = sf.info(path)
        assert path.suffix == ".flac" and info.subtype == "PCM_24" and info.samplerate == RATE and info.channels == 2
        assert path.is_relative_to(cache)
    second = stems.separate(song, stems.FOUR)
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
    stems.separate(song, stems.FOUR, progress=seen.append)
    assert seen == sorted(seen) and seen[-1] == 1.0 and all(0 <= p <= 1 for p in seen)


def test_offline_mode_refuses_to_download(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    torch_state = install_fake_demucs(monkeypatch, {})
    with pytest.raises(StemsError, match="--offline"):
        stems.separate(song, stems.FOUR, offline=True)
    assert torch_state["downloads"] == []
    assert not any(cache.rglob("*.flac")) and list((cache / "stems").iterdir()) == []  # nothing half-written


def test_a_failed_separation_leaves_no_partial_cache(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    install_fake_demucs(monkeypatch, {})

    def boom(self: object, wav: object, sr: int) -> None:
        raise RuntimeError("out of memory")

    monkeypatch.setattr(sys.modules["demucs.api"].Separator, "separate_tensor", boom)
    with pytest.raises(StemsError, match="out of memory"):
        stems.separate(song, stems.FOUR)
    assert list((cache / "stems").iterdir()) == []


def test_ctrl_c_during_separation_leaves_no_temp_folder(
    monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path
) -> None:
    install_fake_demucs(monkeypatch, {})

    def interrupted(self: object, wav: object, sr: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(sys.modules["demucs.api"].Separator, "separate_tensor", interrupted)
    with pytest.raises(KeyboardInterrupt):
        stems.separate(song, stems.FOUR)
    assert list((cache / "stems").iterdir()) == []


def test_a_model_load_error_is_typed(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    install_fake_demucs(monkeypatch, {})

    def broken(self: object, *args: Any, **kwargs: Any) -> None:
        raise FakeLoadModelError("unknown model")

    monkeypatch.setattr(sys.modules["demucs.api"].Separator, "__init__", broken)
    with pytest.raises(StemsError, match="unknown model"):
        stems.separate(song, stems.FOUR)


def test_a_concurrent_run_that_finished_first_is_reused(
    monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path
) -> None:
    calls: dict[str, Any] = {}
    install_fake_demucs(monkeypatch, calls)
    winner = stems.separate(song, stems.FOUR)
    real_separate = sys.modules["demucs.api"].Separator.separate_tensor

    def racing(self: Any, wav: Any, sr: int) -> Any:
        # The other run publishes its folder while this one is still separating.
        for p in winner.paths.values():
            sf.write(p, np.zeros((10, 2)), RATE, subtype="PCM_24")
        return real_separate(self, wav, sr)

    for p in winner.paths.values():
        p.unlink()
    monkeypatch.setattr(sys.modules["demucs.api"].Separator, "separate_tensor", racing)
    again = stems.separate(song, stems.FOUR)
    assert not again.from_cache and all(p.exists() for p in again.paths.values())
    assert [p.name for p in (cache / "stems").iterdir()] == [winner.folder.name]


def test_missing_extra_explains_the_cpu_install(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    monkeypatch.setitem(sys.modules, "demucs", None)
    monkeypatch.setitem(sys.modules, "demucs.api", None)
    with pytest.raises(MissingExtra) as exc:
        stems.separate(song, stems.FOUR)
    message = str(exc.value)
    assert "woodshed[stems]" in message and "cpu" in message.lower()


def test_cache_dir_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from woodshed import cache

    monkeypatch.delenv("WOODSHED_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    expected = {
        "linux": tmp_path / "xdg" / "woodshed",
        "win32": tmp_path / "local" / "woodshed" / "Cache",
        "darwin": Path.home() / "Library" / "Caches" / "woodshed",
    }
    for platform, folder in expected.items():  # the module's view of the platform only, not the process's
        monkeypatch.setattr(cache, "sys", types.SimpleNamespace(platform=platform))
        assert cache.cache_dir() == folder


def test_a_stale_incomplete_cache_folder_is_replaced(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    install_fake_demucs(monkeypatch, {})
    first = stems.separate(song, stems.FOUR)
    first.paths["vocals"].unlink()  # deleted by hand, or left by an interrupted older version
    again = stems.separate(song, stems.FOUR)
    assert not again.from_cache and all(p.exists() for p in again.paths.values())
    assert [p.name for p in (cache / "stems").iterdir()] == [first.folder.name]


def test_stems_louder_than_full_scale_share_one_gain(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    install_fake_demucs(monkeypatch, {}, peak=1.5)  # Demucs output is not limited to [-1, 1]
    result = stems.separate(song, stems.FOUR)
    assert result.gain == pytest.approx(stems.CEILING / 1.5)
    levels = [float(sf.read(result.paths[name])[0].max()) for name in stems.FOUR.stems]
    # Nothing clipped: the stems keep their proportions, so they still add up to the mix.
    assert levels == pytest.approx([1.5 * (i + 1) / 4 * result.gain for i in range(4)], abs=1e-6)
    assert stems.separate(song, stems.FOUR).gain == result.gain  # remembered with the cached stems


def test_quiet_stems_are_written_unchanged(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    install_fake_demucs(monkeypatch, {})
    assert stems.separate(song, stems.FOUR).gain == 1.0


def test_a_file_longer_than_the_limit_is_not_separated(
    monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path
) -> None:
    calls: dict[str, Any] = {}
    install_fake_demucs(monkeypatch, calls)
    monkeypatch.setattr("woodshed.audio.MAX_SECONDS", 1)
    with pytest.raises(AudioError, match="limit"):
        stems.separate(song, stems.FOUR)
    assert "init" not in calls


def test_demucs_gets_our_decoded_audio_never_the_file(monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path) -> None:
    calls: dict[str, Any] = {}
    install_fake_demucs(monkeypatch, calls)
    stems.separate(song, stems.FOUR)
    shape, sr = calls["input"]
    assert sr == stems.RATE and shape[0] == 2  # stereo, decoded by audio.load


def test_a_disguised_concat_list_never_reaches_demucs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cache: Path
) -> None:
    import shutil

    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    calls: dict[str, Any] = {}
    install_fake_demucs(monkeypatch, calls)
    secret = tmp_path / "secret.wav"
    sf.write(secret, np.full(22050, 0.5), 22050)
    disguised = tmp_path / "song.mp3"
    disguised.write_text(f"ffconcat version 1.0\nfile {secret.name}\n")
    with pytest.raises(AudioError, match="not supported"):
        stems.separate(disguised, stems.FOUR)
    assert "init" not in calls


@pytest.mark.parametrize("xdg", ["", "relative/cache"])
def test_an_empty_or_relative_xdg_cache_home_is_ignored(monkeypatch: pytest.MonkeyPatch, xdg: str) -> None:
    from woodshed.cache import cache_dir

    monkeypatch.delenv("WOODSHED_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", xdg)
    if sys.platform == "linux":
        assert cache_dir() == Path.home() / ".cache" / "woodshed"


def test_a_relative_woodshed_cache_is_made_absolute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from woodshed.cache import cache_dir

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WOODSHED_CACHE", "cache")
    assert cache_dir() == tmp_path.resolve() / "cache"


@pytest.mark.parametrize("content", ["not json", '{"gain": "loud"}', '{"gain": 3}', "{}"])
def test_a_corrupt_gain_file_means_separating_again(
    monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path, content: str
) -> None:
    calls: dict[str, Any] = {}
    install_fake_demucs(monkeypatch, calls)
    first = stems.separate(song, stems.FOUR)
    (first.folder / stems.GAIN_FILE).write_text(content)
    again = stems.separate(song, stems.FOUR)
    assert not again.from_cache and calls["init"] == 2 and again.gain == 1.0
    assert stems.separate(song, stems.FOUR).from_cache and calls["init"] == 2  # the bad entry was replaced


def test_a_missing_extra_is_reported_before_any_decoding(
    monkeypatch: pytest.MonkeyPatch, song: Path, cache: Path
) -> None:
    monkeypatch.setitem(sys.modules, "demucs", None)
    monkeypatch.setitem(sys.modules, "demucs.api", None)

    def no_decode(*args: object, **kwargs: object) -> None:
        raise AssertionError("decoded before checking the extra")

    monkeypatch.setattr("woodshed.audio.load", no_decode)
    with pytest.raises(MissingExtra):
        stems.separate(song, stems.FOUR)
