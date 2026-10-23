"""The recording in another key, rendered by the library (spec 007, the singer's key).

Rubber Band (GPL: always a separate program, never linked), as ffmpeg's `rubberband` filter or else as its own
command-line program (spec 017: the installers fetch it on Mac and Windows), shifts a page's track by whole
semitones, the same length to the sample, so the beats, the click and the chart stay where they are. A Python
pass then sets the level back to the original's, under the tracks' common peak ceiling, and writes the same 24-bit
FLAC the page's other files are. The page plays it like any other track.
"""

from __future__ import annotations

import contextlib
import functools
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from woodshed.errors import WoodshedError
from woodshed.paths import tools_dir as tools_dir  # one folder for the app, the installers and the uninstall
from woodshed.stems import CEILING

KEY_DIR = "key"  # <page>/audio/key/up2/mix.flac
UNPITCHED = frozenset({"solo-drums"})  # nothing to transpose: plays as recorded
# Tracks that hold the voice keep its formants (a voice shifted keeps its timbre); the others are shifted with
# their pitch. One table, to change after a listening test.
FORMANTS_KEPT = frozenset(
    {"mix", "solo-vocals", "minus-bass", "minus-drums", "minus-other", "minus-guitar", "minus-keys"}
)
BLOCK = 1 << 18
SLOWEST = 10.0  # a render longer than 10x the track's duration is stuck: killed
LEAST = 60.0  # seconds a render may always take
PROGRAM_SINCE = (3, 2)
# The program clamps what goes over 1.0 where ffmpeg's filter keeps it for the level step: it gets the source a
# quarter down (a power of two: exact in float), the level step gives the quarter back.
PRESCALE = 0.25
CLAMPED = 0.99  # a program's peak this high was clamped (4x the source's at most): refused, never a silent clip


class Cancelled(Exception):
    """The render is not wanted any more (a stop, a page rebuilt): nothing is written."""


@functools.cache
def available() -> bool:
    """ffmpeg is installed with the Rubber Band filter (Ubuntu's, Debian's, Gyan's full build; not Homebrew's)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[1:2] == ["rubberband"] for line in out.stdout.splitlines())


def _version(path: str) -> tuple[int, int] | None:
    try:
        out = subprocess.run([path, "-V"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"(\d+)\.(\d+)", out.stdout + out.stderr) if out.returncode == 0 else None
    return (int(found[1]), int(found[2])) if found else None


@functools.cache
def program() -> str | None:
    """The Rubber Band program, 3.2 or newer (the R3 engine, a mono-compatible centre focus): the tools
    folder's first (the installers' pinned build), then the PATH's (Ubuntu 22.04's 2.0.2 is not used)."""
    name = "rubberband.exe" if sys.platform == "win32" else "rubberband"
    for found in (tools_dir() / name, shutil.which("rubberband")):
        if found is not None and Path(found).is_file() and (_version(str(found)) or (0, 0)) >= PROGRAM_SINCE:
            return str(found)
    return None


def blocked() -> bool:
    """The installers' program is in the tools folder but does not run (Smart App Control, an antivirus,
    Gatekeeper) and nothing else renders: running the installer again would not help."""
    name = "rubberband.exe" if sys.platform == "win32" else "rubberband"
    return tool() is None and (tools_dir() / name).is_file()


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def tool() -> tuple[str, str] | None:
    """What renders a key: ffmpeg with its filter (as before 017), else the Rubber Band program, else nothing."""
    if available():
        return "ffmpeg", shutil.which("ffmpeg") or "ffmpeg"
    found = program()
    return ("rubberband", found) if found else None


def key_dir(semitones: int) -> str:
    """The folder of one key, without a `+` in the URL: up2, down3."""
    return f"up{semitones}" if semitones > 0 else f"down{-semitones}"


def fingerprint(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_size, st.st_mtime_ns


def _low_priority() -> tuple[list[str], int]:
    """The ffmpeg child runs below the library and the band's playback: nice on POSIX, below normal on Windows."""
    if os.name == "nt":
        return [], getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    nice = shutil.which("nice")
    return ([nice, "-n", "10"] if nice else []), 0


def _rms_and_peak(path: Path) -> tuple[float, float]:
    total, count, peak = 0.0, 0, 0.0
    with sf.SoundFile(path) as f:
        for block in f.blocks(blocksize=BLOCK, dtype="float32", always_2d=True):
            total += float(np.sum(np.square(block, dtype=np.float64)))
            count += block.size
            peak = max(peak, float(np.max(np.abs(block), initial=0.0)))
    return (float(np.sqrt(total / count)) if count else 0.0), peak


def _decode(src: Path, wav: Path, should_stop: Callable[[], bool]) -> None:
    """The source as a float WAV for the program, a quarter down (PRESCALE)."""
    with sf.SoundFile(src) as f, sf.SoundFile(wav, "w", f.samplerate, f.channels, "FLOAT", format="WAV") as out:
        for block in f.blocks(blocksize=BLOCK, dtype="float32", always_2d=True):
            if should_stop():
                raise Cancelled("stopped")
            out.write(block * np.float32(PRESCALE))


def render(
    src: Path,
    dst: Path,
    semitones: int,
    track: str,
    before: tuple[int, int],
    should_stop: Callable[[], bool] = lambda: False,
    on_child: Callable[[subprocess.Popen[bytes] | None], None] = lambda child: None,
    using: tuple[str, str] | None = None,
) -> None:
    """Render `src` `semitones` away into `dst` (`<page>/audio/key/<dir>/<track>.flac`). `before`: the source's
    fingerprint when the render was asked; a source changed since (the page rebuilt) cancels it. `using`: the
    tool (`tool()`'s answer when not given)."""
    if track in UNPITCHED or not -6 <= semitones <= 6 or semitones == 0:
        raise WoodshedError(f"{track} is not rendered {semitones:+d}")
    kind, path = using or tool() or ("ffmpeg", shutil.which("ffmpeg") or "ffmpeg")
    audio_dir = dst.parents[2]
    if not audio_dir.is_dir():  # never created above the page's own audio folder
        raise Cancelled("the page is gone")
    (audio_dir / KEY_DIR).mkdir(exist_ok=True)
    dst.parent.mkdir(exist_ok=True)
    token = secrets.token_hex(4)
    wav = dst.with_name(f".{dst.stem}.{token}.wav")  # dotted: never served, removed at start if left over
    part = dst.with_name(f".{dst.stem}.{token}.part")
    decoded = dst.with_name(f".{dst.stem}.{token}.in.wav")  # the program's input
    prefix, flags = _low_priority()
    cwd: Path | None = None
    if kind == "ffmpeg":
        ffmpeg = path
        formant = "preserved" if track in FORMANTS_KEPT else "shifted"
        shift = f"rubberband=pitch={2 ** (semitones / 12):.10f}:pitchq=quality:channels=together:formant={formant}"
        cmd = [*prefix, ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-threads", "1"]
        cmd += ["-i", str(src.resolve()), "-af", shift, "-threads", "1", "-c:a", "pcm_f32le", str(wav.resolve())]
    else:
        # The R3 engine, the centre's focus kept (and mono compatibility, 3.2+), formants as ffmpeg's. Relative
        # ASCII names in the key's folder: libsndfile opens ANSI paths on Windows, and no folder in an error.
        formants = ["-F"] if track in FORMANTS_KEPT else []
        cmd = [*prefix, path, "-3", "--centre-focus", *formants, "-p", str(semitones), "-q", "--ignore-clipping"]
        cmd += [decoded.name, wav.name]
        cwd = dst.parent
    log = dst.with_name(f".{dst.stem}.{token}.log")  # the child's errors: a file, never a pipe that fills up
    try:
        deadline = time.monotonic() + max(LEAST, SLOWEST * sf.info(str(src)).duration)
        if kind != "ffmpeg":
            _decode(src, decoded, should_stop)
        with open(log, "wb") as errors:
            child = subprocess.Popen(
                cmd, stdin=None if kind == "ffmpeg" else subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                creationflags=flags, cwd=cwd,
            )  # fmt: skip
        on_child(child)
        while True:
            try:
                child.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if should_stop() or time.monotonic() > deadline:
                    child.kill()
                    child.wait()
                    if should_stop():
                        raise Cancelled("stopped") from None
                    raise WoodshedError("changing the key took too long") from None
        if child.returncode != 0:
            error = log.read_text(encoding="utf-8", errors="replace")
            last = (error.strip().splitlines() or ["no reason given"])[-1]
            last = re.sub(r"(?:[A-Za-z]:)?[\\/]\S*[\\/]", "", last)  # file names, never this computer's folders
            if kind == "ffmpeg":
                raise WoodshedError(f"ffmpeg could not change the key: {last}")
            print(f"woodshed: Rubber Band could not change the key: {last}", file=sys.stderr)  # the console only
            raise WoodshedError("could not change the key")
        # The level back to the original's, never above the common ceiling: no clipped sample.
        source_rms, _ = _rms_and_peak(src)
        rendered_rms, rendered_peak = _rms_and_peak(wav)
        if kind != "ffmpeg" and rendered_peak >= CLAMPED:
            raise WoodshedError("could not change the key: the render would clip")
        gain = source_rms / rendered_rms if rendered_rms > 0 else 1.0
        if rendered_peak * gain > CEILING:
            gain = CEILING / rendered_peak
        info = sf.info(str(wav))
        frames = sf.info(str(src)).frames  # the source's length to the sample: the beats stay where they are
        with (
            sf.SoundFile(wav) as f,
            sf.SoundFile(part, "w", info.samplerate, info.channels, "PCM_24", format="FLAC") as out,
        ):
            written = 0
            for block in f.blocks(blocksize=BLOCK, dtype="float32", always_2d=True):
                if should_stop():
                    raise Cancelled("stopped")
                block = block[: frames - written]
                out.write(block * gain)
                written += len(block)
            if written < frames:
                out.write(np.zeros((frames - written, info.channels), dtype="float32"))
        if fingerprint(src) != before:
            raise Cancelled("the page changed while its track was rendered")
        os.replace(part, dst)
    except Cancelled:
        raise
    except Exception as exc:
        # A source that no longer reads (or a child that failed on it) because the page was rebuilt meanwhile:
        # nothing failed. The same error on an unchanged source is a real one.
        if not _same(src, before):
            raise Cancelled("the page changed while its track was rendered") from exc
        raise
    finally:
        on_child(None)
        for leftover in (wav, part, log, decoded):
            with contextlib.suppress(OSError):
                leftover.unlink()


def _same(src: Path, before: tuple[int, int]) -> bool:
    try:
        return fingerprint(src) == before
    except OSError:
        return False


def prune(audio_dir: Path, keep: set[str]) -> list[str]:
    """Remove the rendered keys not in `keep` (folder names); a file in use (Windows) stays for the next time."""
    removed = []
    for folder in sorted((audio_dir / KEY_DIR).glob("*")):
        if folder.is_dir() and folder.name not in keep:
            try:
                shutil.rmtree(folder)
                removed.append(folder.name)
            except OSError:
                pass
    return removed


def clean_leftovers(root: Path) -> None:
    """Temporary files of renders cut by a stop: removed at start."""
    for leftover in root.glob(f"*.woodshed/audio/{KEY_DIR}/*/.*"):
        with contextlib.suppress(OSError):
            leftover.unlink()


# The renders of a library: one at a time, the track a page waits for first.
WAITED, ROLE, PREFETCH = 0, 1, 2  # priorities
MAX_QUEUED = 16
RECENT = 600.0  # seconds: an old key's prefetch asked this recently is kept when the band changes key
PLAYING = 60.0  # seconds: a key served this recently is playing somewhere: never pruned under it
FORCE_EVERY = 60.0  # seconds between two re-renders of one file asked by a page (`force`)
OTHER_KEYS = 2  # kept per page besides the band's key
SPEED = 5.5  # seconds of audio rendered per second until measured (3:43 in 40 s on a laptop core)


@dataclass
class Render:
    page: str
    track: str
    semitones: int
    priority: int
    before: tuple[int, int]
    seconds: float
    asked: float = field(default_factory=time.monotonic)


class Full(Exception):
    """Too many renders asked: try again later."""


class Renders:
    """The renders asked by the pages of one library, rendered one at a time on their own thread."""

    def __init__(self, root: Path, busy: Callable[[], bool] = lambda: False, free_margin: int = 0) -> None:
        self.root = root
        self.busy = busy  # an analysis runs: the renders wait (rare, and wanted more)
        self.free_margin = free_margin
        self.cond = threading.Condition()
        self.queue: list[Render] = []
        self.running: Render | None = None
        self.child: subprocess.Popen[bytes] | None = None
        self.failed: dict[tuple[str, str, str], str] = {}  # (page, key dir, track) -> reason
        self.used: dict[tuple[str, str], float] = {}  # (page, key dir) -> last asked or served
        self.band: dict[str, str] = {}  # page -> the band's key dir
        self.speed = SPEED
        self.stopping = False
        self.cancelled: set[str] = set()  # pages whose running render must stop
        self.forced: dict[tuple[str, str, str], float] = {}
        self.played: dict[
            tuple[str, str], float
        ] = {}  # (page, key dir) -> last served  # (page, key dir, track) -> last re-render asked
        clean_leftovers(root)
        threading.Thread(target=self._work, name="woodshed-renders", daemon=True).start()

    # What the pages ask.

    def ask(self, page: str, track: str, semitones: int, priority: int = WAITED, force: bool = False) -> str:
        """Queue one track in one key; its state now: ready, queued, running. `force`: render it again (a
        file the browser could not play)."""
        audio_dir = self.root / page / "audio"
        src, dst = audio_dir / f"{track}.flac", audio_dir / KEY_DIR / key_dir(semitones) / f"{track}.flac"
        key = key_dir(semitones)
        try:  # read before taking the lock: the pages' polls need it
            seconds = sf.info(str(src)).duration
            before = fingerprint(src)
        except (RuntimeError, OSError):
            raise WoodshedError("this track cannot be read") from None
        # The float WAV in the middle is about four times the FLAC; the program's path has two (its input).
        using = tool()
        times = 9 if using is not None and using[0] == "rubberband" else 5
        room = shutil.disk_usage(self.root).free >= before[0] * times + self.free_margin
        with self.cond:
            now = time.monotonic()
            self.used[(page, key)] = now
            self.failed.pop((page, key, track), None)
            # Again, for a file a browser could not play; once a minute at most: a phone looping on it
            # would delete the file the band is playing.
            again = force and now - self.forced.get((page, key, track), -FORCE_EVERY) >= FORCE_EVERY
            if again and dst.is_file() and not (self.running and self.running.page == page):
                self.forced[(page, key, track)] = now
                with contextlib.suppress(OSError):
                    dst.unlink()
            if dst.is_file():
                return "ready"
            if self.running and (self.running.page, self.running.track, self.running.semitones) == (
                page,
                track,
                semitones,
            ):
                return "running"
            for r in self.queue:
                if (r.page, r.track, r.semitones) == (page, track, semitones):
                    r.priority = min(r.priority, priority)  # waited for now: ahead
                    return "queued"
            if len(self.queue) >= MAX_QUEUED:
                raise Full("too many renders asked: try again in a minute")
            if not room:
                raise WoodshedError("not enough free disk to render this track")
            self.queue.append(Render(page, track, semitones, priority, before, seconds))
            keep = self._keep(page, key)
            self.cond.notify_all()
        prune(audio_dir, keep)  # outside the lock: folders removed while the pages poll
        return "queued"

    def wanted(self) -> bool:
        """A render runs, or a page waits for one: a background job of the library lets it through."""
        with self.cond:
            return self.running is not None or any(r.priority == WAITED for r in self.queue)

    def touch(self, page: str, key: str) -> None:
        """A rendered file served: its key is playing somewhere."""
        with self.cond:
            self.played[(page, key)] = time.monotonic()

    def set_band_key(self, page: str, semitones: int, tracks: list[str]) -> None:
        """The band saved a key: its mix and voice tracks are prefetched; the old key's unasked prefetch goes."""
        key = key_dir(semitones) if semitones else ""
        with self.cond:
            old = self.band.get(page)
            if key:
                self.band[page] = key
            else:
                self.band.pop(page, None)
            now = time.monotonic()
            self.queue = [
                r for r in self.queue
                if not (r.page == page and r.priority == PREFETCH and key_dir(r.semitones) == old
                        and now - self.used.get((page, old), 0.0) > RECENT)
            ]  # fmt: skip
        for track in tracks if key else []:
            with contextlib.suppress(Full, WoodshedError, OSError):
                self.ask(page, track, semitones, PREFETCH)

    def cancel_page(self, page: str) -> None:
        """The page is rebuilt (an analysis, the bar lines): its renders are of the old files."""
        with self.cond:
            self.queue = [r for r in self.queue if r.page != page]
            self.failed = {k: v for k, v in self.failed.items() if k[0] != page}
            if self.running and self.running.page == page:
                self.cancelled.add(page)
            # The render stops before the page's folder is replaced (Windows will not remove an open file).
            self.cond.wait_for(lambda: not (self.running and self.running.page == page), timeout=10)

    def state(self, page: str) -> dict[str, Any]:
        """For the page: each key's tracks, ready, queued, running or failed, and when each key's queue ends."""
        with self.cond:
            keys: dict[str, dict[str, str]] = {}
            versions: dict[str, dict[str, int]] = {}  # a file rendered again gets a new URL: no browser's old copy
            folder = self.root / page / "audio" / KEY_DIR
            for d in sorted(folder.glob("*")) if folder.is_dir() else []:
                for f in d.glob("*.flac"):
                    keys.setdefault(d.name, {})[f.stem] = "ready"
                    with contextlib.suppress(OSError):
                        versions.setdefault(d.name, {})[f.stem] = f.stat().st_mtime_ns // 1_000_000
            ahead = 0.0
            eta: dict[str, float] = {}
            if self.running:
                ahead = self.running.seconds / self.speed
                if self.running.page == page:
                    keys.setdefault(key_dir(self.running.semitones), {})[self.running.track] = "running"
                    eta[key_dir(self.running.semitones)] = ahead
            for r in sorted(self.queue, key=lambda r: (r.priority, r.asked)):
                ahead += r.seconds / self.speed
                if r.page == page:
                    keys.setdefault(key_dir(r.semitones), {})[r.track] = "queued"
                    eta[key_dir(r.semitones)] = ahead
            failed: dict[str, dict[str, str]] = {}
            for (p, key, track), why in self.failed.items():
                if p == page:
                    keys.setdefault(key, {})[track] = "failed"
                    failed.setdefault(key, {})[track] = why
            return {"keys": keys, "versions": versions, "failed": failed, "eta": {k: round(v) for k, v in eta.items()}}

    def stop(self) -> None:
        with self.cond:
            self.stopping = True
            self.queue.clear()
            self.cond.notify_all()
            child = self.child
        if child is not None and child.poll() is None:
            child.kill()

    # The work.

    def _keep(self, page: str, keep_also: str) -> set[str]:
        """Under the lock: the keys of a page that stay, the band's key, the two most recently asked
        others, any key queued or rendering and any key a device played in the last minute."""
        now = time.monotonic()
        busy = {key_dir(r.semitones) for r in self.queue if r.page == page}
        if self.running and self.running.page == page:
            busy.add(key_dir(self.running.semitones))
        recent = sorted(
            (k for (p, k) in self.used if p == page and k != self.band.get(page)),
            key=lambda k: self.used[(page, k)],
            reverse=True,
        )
        keep = {keep_also, self.band.get(page, "")} | busy | set(recent[:OTHER_KEYS])
        keep |= {k for (p, k), at in self.played.items() if p == page and now - at < PLAYING}
        return keep

    def _next(self) -> Render | None:
        with self.cond:
            while not self.stopping and (not self.queue or self.busy()):
                self.cond.wait(timeout=1.0)
            if self.stopping:
                return None
            self.queue.sort(key=lambda r: (r.priority, r.asked))
            self.running = self.queue.pop(0)
            self.cancelled.discard(self.running.page)
            return self.running

    def _set_child(self, child: subprocess.Popen[bytes] | None) -> None:
        with self.cond:
            self.child = child

    def _work(self) -> None:
        while (job := self._next()) is not None:
            audio_dir = self.root / job.page / "audio"
            dst = audio_dir / KEY_DIR / key_dir(job.semitones) / f"{job.track}.flac"
            started = time.monotonic()
            try:
                render(
                    audio_dir / f"{job.track}.flac", dst, job.semitones, job.track, job.before,
                    should_stop=lambda: self.stopping or job.page in self.cancelled, on_child=self._set_child,
                )  # fmt: skip
                took = time.monotonic() - started
                if took > 0:
                    self.speed = 0.7 * self.speed + 0.3 * (job.seconds / took)
            except Cancelled:
                pass
            except (WoodshedError, OSError) as exc:
                if job.page in self.cancelled or not _same(audio_dir / f"{job.track}.flac", job.before):
                    continue  # the page was rebuilt under it: nothing failed, nothing to say
                reason = str(exc).replace(str(self.root), "the library").replace(str(Path.home()), "~")
                with self.cond:
                    self.failed[(job.page, key_dir(job.semitones), job.track)] = reason
            except Exception:  # a bug, or a file soundfile cannot read: this render fails, the worker lives on
                traceback.print_exc()
                with self.cond:
                    self.failed[(job.page, key_dir(job.semitones), job.track)] = "unexpected error"
            finally:
                with self.cond:
                    self.running = None
                    self.cond.notify_all()
