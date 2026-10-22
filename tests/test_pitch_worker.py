"""The library's renders (spec 007): queue, limits, cancels and pruning, with a fake ffmpeg (fast, everywhere)."""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from woodshed import pitch
from woodshed.errors import WoodshedError

FAKE = """#!{python}
import os, sys, time
import soundfile as sf
args = sys.argv[1:]
if "-filters" in args:
    if os.environ.get("FAKE_RUBBERBAND", "1") == "1":
        print(" ..C rubberband        A->A       Apply time-stretching and pitch-shifting.")
    sys.exit(0)
if not any("rubberband" in a for a in args):  # decoding a song: the real ffmpeg, when there is one
    real = os.environ.get("FAKE_REAL_FFMPEG")
    if not real:
        sys.exit(1)
    os.execv(real, [real, *args])
log = os.environ.get("FAKE_FFMPEG_LOG")
src = args[args.index("-i") + 1]
if log:
    with open(log, "a") as f:
        page = os.path.basename(os.path.dirname(os.path.dirname(src)))
        f.write(page + " " + os.path.basename(src) + "\\n")
time.sleep(float(os.environ.get("FAKE_FFMPEG_SECONDS", "0")))
if os.environ.get("FAKE_FFMPEG_FAIL"):
    sys.stderr.write("Error opening " + src + ": broken\\n")
    sys.exit(1)
if os.environ.get("FAKE_FFMPEG_GARBAGE"):
    open(args[-1], "wb").write(b"not a wav file")
    sys.exit(0)
data, rate = sf.read(src, dtype="float32")
sf.write(args[-1], data, rate, subtype="FLOAT", format="WAV")
"""


@pytest.fixture
def fake_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "ffmpeg"
    shim.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    shim.chmod(0o755)
    log = tmp_path / "ffmpeg.log"
    monkeypatch.setenv("FAKE_REAL_FFMPEG", shutil.which("ffmpeg") or "")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))
    pitch.available.cache_clear()
    yield log
    pitch.available.cache_clear()


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake ffmpeg is a script with a shebang")

TRACKS = ("mix", "solo-vocals", "minus-vocals", "solo-drums", "solo-bass")


def library(root: Path, pages: tuple[str, ...] = ("One.woodshed",)) -> Path:
    tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(22050) / 44100)
    for page in pages:
        audio = root / page / "audio"
        audio.mkdir(parents=True)
        for track in TRACKS:
            sf.write(audio / f"{track}.flac", np.stack([tone, tone], 1), 44100, subtype="PCM_24", format="FLAC")
    return root


def until(check: Callable[[], bool], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "still false"
        time.sleep(0.05)


@pytest.fixture
def renders(tmp_path: Path, fake_ffmpeg: Path) -> Iterator[pitch.Renders]:
    r = pitch.Renders(library(tmp_path / "lib", ("One.woodshed", "Two.woodshed")))
    yield r
    r.stop()


def rendered(r: pitch.Renders, page: str, key: str, track: str) -> Path:
    return r.root / page / "audio" / pitch.KEY_DIR / key / f"{track}.flac"


def test_a_track_asked_is_rendered_and_said_ready(renders: pitch.Renders) -> None:
    assert pitch.available()
    assert renders.ask("One.woodshed", "mix", 2) == "queued"
    until(lambda: rendered(renders, "One.woodshed", "up2", "mix").is_file())
    assert renders.ask("One.woodshed", "mix", 2) == "ready"
    assert renders.state("One.woodshed")["keys"] == {"up2": {"mix": "ready"}}
    assert renders.state("Two.woodshed")["keys"] == {}  # another page's renders are its own


def test_the_track_a_page_waits_for_goes_first(
    renders: pitch.Renders, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_SECONDS", "0.3")
    renders.ask("One.woodshed", "mix", 1, pitch.PREFETCH)
    until(lambda: renders.running is not None)  # rendering: the others wait
    renders.ask("One.woodshed", "solo-vocals", 1, pitch.PREFETCH)
    renders.ask("Two.woodshed", "mix", 3, pitch.ROLE)
    renders.ask("Two.woodshed", "solo-bass", 3, pitch.WAITED)  # a page waits for it: ahead of the others
    until(lambda: len(fake_ffmpeg.read_text().splitlines()) == 4 if fake_ffmpeg.exists() else False, 20)
    order = fake_ffmpeg.read_text().split("\n")[:4]
    assert order[1:] == ["Two.woodshed solo-bass.flac", "Two.woodshed mix.flac", "One.woodshed solo-vocals.flac"]
    eta = renders.state("One.woodshed")["eta"]
    assert all(isinstance(v, int) for v in eta.values())


def test_too_many_renders_are_refused(renders: pitch.Renders, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_SECONDS", "5")
    renders.ask("One.woodshed", "mix", 6)  # running, the others wait
    for semitones in (-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5):
        for track in ("solo-vocals", "minus-vocals"):
            if len(renders.queue) < pitch.MAX_QUEUED:
                renders.ask("Two.woodshed", track, semitones)
    with pytest.raises(pitch.Full):
        renders.ask("One.woodshed", "solo-bass", 3)


def test_a_page_rebuilt_loses_its_renders_at_once(renders: pitch.Renders, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_SECONDS", "30")
    renders.ask("One.woodshed", "mix", 2)
    renders.ask("One.woodshed", "solo-vocals", 2)
    renders.ask("Two.woodshed", "mix", 2)
    until(lambda: renders.child is not None)
    started = time.monotonic()
    renders.cancel_page("One.woodshed")
    until(lambda: renders.running is None or renders.running.page == "Two.woodshed", 5)
    assert time.monotonic() - started < 5  # the ffmpeg child is killed, not waited for
    assert [r.page for r in renders.queue] in ([], ["Two.woodshed"])
    assert not rendered(renders, "One.woodshed", "up2", "mix").exists()
    assert not list((renders.root / "One.woodshed" / "audio" / pitch.KEY_DIR / "up2").glob(".*"))


def test_renders_wait_while_an_analysis_runs(tmp_path: Path, fake_ffmpeg: Path) -> None:
    analysing = [True]
    r = pitch.Renders(library(tmp_path / "lib"), busy=lambda: analysing[0])
    try:
        r.ask("One.woodshed", "mix", 2)
        time.sleep(1.5)
        assert not rendered(r, "One.woodshed", "up2", "mix").exists()  # the analysis first
        analysing[0] = False
        until(lambda: rendered(r, "One.woodshed", "up2", "mix").is_file())
    finally:
        r.stop()


def test_a_stop_kills_the_render(renders: pitch.Renders, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_SECONDS", "30")
    renders.ask("One.woodshed", "mix", 2)
    until(lambda: renders.child is not None)
    child = renders.child
    renders.stop()
    assert child is not None
    until(lambda: child.poll() is not None, 5)


def test_a_failed_render_says_why_without_this_computer_s_paths(
    renders: pitch.Renders, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_FAIL", "1")
    renders.ask("One.woodshed", "mix", 2)
    until(lambda: bool(renders.state("One.woodshed")["failed"]))
    state = renders.state("One.woodshed")
    assert state["keys"]["up2"]["mix"] == "failed"
    why = state["failed"]["up2"]["mix"]
    assert "broken" in why and str(renders.root) not in why
    monkeypatch.delenv("FAKE_FFMPEG_FAIL")
    assert renders.ask("One.woodshed", "mix", 2) == "queued"  # Retry


def test_old_keys_go_the_band_key_and_the_recent_ones_stay(
    renders: pitch.Renders, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pitch, "RECENT", 0.0)
    renders.set_band_key("One.woodshed", -2, ["mix"])
    for semitones in (1, 2, 3, 4):
        renders.ask("One.woodshed", "mix", semitones)
        done = rendered(renders, "One.woodshed", pitch.key_dir(semitones), "mix")
        until(done.is_file)
    renders.ask("One.woodshed", "mix", 5)  # a new key: the oldest other keys go
    until(lambda: rendered(renders, "One.woodshed", "up5", "mix").is_file())
    kept = sorted(p.name for p in (renders.root / "One.woodshed" / "audio" / pitch.KEY_DIR).iterdir())
    assert kept == ["down2", "up4", "up5"]  # the band's key, and the two most recent others


def test_the_band_key_is_prefetched_and_a_new_one_cancels_the_old(
    renders: pitch.Renders, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_SECONDS", "0.5")
    monkeypatch.setattr(pitch, "RECENT", 0.0)
    renders.ask("Two.woodshed", "mix", 6)  # something running first
    renders.set_band_key("One.woodshed", 2, ["mix", "solo-vocals", "minus-vocals"])
    assert {(r.track, r.semitones) for r in renders.queue if r.page == "One.woodshed"} == {
        ("mix", 2), ("solo-vocals", 2), ("minus-vocals", 2)
    }  # fmt: skip
    renders.set_band_key("One.woodshed", 3, ["mix"])
    assert {(r.track, r.semitones) for r in renders.queue if r.page == "One.woodshed"} == {("mix", 3)}


def test_no_render_without_disk_room(renders: pitch.Renders, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**9, 10**9, 10))
    with pytest.raises(WoodshedError, match="free disk"):
        renders.ask("One.woodshed", "mix", 2)


def test_without_the_rubberband_filter_there_is_no_render(fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_RUBBERBAND", "0")
    pitch.available.cache_clear()
    assert not pitch.available()


def test_an_unreadable_render_fails_and_the_worker_lives_on(
    renders: pitch.Renders, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_GARBAGE", "1")
    renders.ask("One.woodshed", "mix", 2)
    until(lambda: bool(renders.state("One.woodshed")["failed"]))
    monkeypatch.delenv("FAKE_FFMPEG_GARBAGE")
    renders.ask("One.woodshed", "mix", 2)  # Retry: the worker is still there
    until(lambda: rendered(renders, "One.woodshed", "up2", "mix").is_file())


def test_a_stuck_render_is_killed(renders: pitch.Renders, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_SECONDS", "30")
    monkeypatch.setattr(pitch, "LEAST", 1.0)
    monkeypatch.setattr(pitch, "SLOWEST", 0.1)
    started = time.monotonic()
    renders.ask("One.woodshed", "mix", 2)
    until(lambda: bool(renders.state("One.woodshed")["failed"]), 15)
    assert time.monotonic() - started < 10
    assert "too long" in renders.state("One.woodshed")["failed"]["up2"]["mix"]


def test_a_file_the_browser_cannot_play_is_rendered_again_when_asked(renders: pitch.Renders) -> None:
    dst = rendered(renders, "One.woodshed", "up2", "mix")
    dst.parent.mkdir(parents=True)
    dst.write_bytes(b"broken")
    assert renders.ask("One.woodshed", "mix", 2) == "ready"
    assert renders.ask("One.woodshed", "mix", 2, force=True) == "queued"
    until(lambda: dst.is_file() and dst.read_bytes()[:4] == b"fLaC")
