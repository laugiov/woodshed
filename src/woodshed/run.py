"""The `woodshed SONG` pipeline: analyse, build the page, open it, then add the stems.

With the stems extra and stems not yet in the cache, the page is built twice: first from the mix
alone (it opens at once, with a banner), then with the stems once they are separated.
"""

from __future__ import annotations

import json
import math
import sys
import time
import webbrowser
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TextIO

from woodshed import __version__, audio, songbook, stems, theory
from woodshed.analysis import REVISION as ANALYSIS_REVISION
from woodshed.analysis import analyze
from woodshed.build import build as build_page
from woodshed.build import folder_name, page_revision, refresh_code
from woodshed.errors import WoodshedError
from woodshed.model import Song

BPM_TOLERANCE = 0.15  # a --bpm hint further than this from the result gets a note
SEPARATION_SPEED = 1.5  # seconds of CPU separation per second of audio, measured (a 4-minute song, laptop)
EXTRA_HINT = 'instrument tracks and parts need the stems extra: pipx install "woodshed[stems]"'


@dataclass(frozen=True)
class Options:
    out: Path | None = None
    use_stems: bool = True
    offline: bool = False
    open_page: bool = True
    title: str | None = None
    beats_per_bar: int = 4
    sevenths: bool = False
    bpm: float | None = None
    bar_phase: int | None = None  # the bar lines the band chose: beats before the first bar line; automatic if None
    pitch: bool = True  # woodshed app renders a song's tracks in another key when asked (ffmpeg with Rubber Band)


class Reporter:
    """Progress on stderr: one line per step with its time."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr
        self.started = time.monotonic()
        self.step: str | None = None
        self.step_started = self.started
        self.stems_shown = -1

    def say(self, text: str) -> None:
        print(text, file=self.stream, flush=True)

    def stems(self, fraction: float) -> None:
        """Separation progress: a line every 10 %."""
        pct = int(fraction * 100)
        if pct // 10 != self.stems_shown // 10:
            self.say(f"  stems      {pct:3d} %")
            self.stems_shown = pct

    def progress(self, step: str, fraction: float) -> None:
        if step == self.step:
            return
        now = time.monotonic()
        if self.step is not None and self.step != "done":
            self.say(f"  {self.step:<10} {now - self.step_started:5.1f} s")
        self.step = step
        self.step_started = now


def stems_extra_installed() -> bool:
    try:
        import demucs.api  # noqa: F401
    except ImportError:
        return False
    return True


def _size_mb(folder: Path) -> float:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6


def _analyze(src: Path, opts: Options, report: Reporter, use_stems: bool, separated: stems.Stems | None) -> Song:
    report.step = None
    return analyze(
        src,
        use_stems=use_stems,
        stems_result=separated,
        sevenths=opts.sevenths,
        title=opts.title,
        beats_per_bar=opts.beats_per_bar,
        offline=opts.offline,
        bpm=opts.bpm,
        bar_phase=opts.bar_phase,
        progress=report.progress,
    )


MANIFEST = "woodshed.json"  # in each page folder: what the page was built from, to skip it next time


def _settings(src: Path, opts: Options, use_stems: bool) -> dict[str, Any]:
    return {
        "version": __version__,
        "analysis": ANALYSIS_REVISION,
        "page": page_revision(),
        "source": stems.fingerprint(src),
        "stems": use_stems,
        "title": opts.title,
        "beats_per_bar": opts.beats_per_bar,
        "sevenths": opts.sevenths,
        "bpm": opts.bpm,
        # Only when chosen: every page built before stays up to date.
        **({"bar_phase": opts.bar_phase} if opts.bar_phase is not None else {}),
    }


def summary(song: Song, page: Path) -> dict[str, Any]:
    """What the songbook index shows for a page."""
    key = theory.Key(song.key.tonic, song.key.mode)
    doubts = len({c.doubt.id for b in song.structure.bars for c in b.chords if c.doubt and c.doubt.counts})
    return {
        "title": song.title,
        "folder": page.name,
        "key": theory.spell(key.tonic, key) + ("" if key.mode == "maj" else "m"),
        "bpm": math.floor(song.bpm + 0.5),
        "meter": f"{song.beats_per_bar}/4",
        "duration": math.floor(round(song.duration, 2) + 0.5),  # as the page rounds it (halves up)
        "doubts": doubts,
        "stems": song.analysis.stems,
    }


def _record(page: Path, settings: dict[str, Any], info: dict[str, Any], complete: bool) -> None:
    text = json.dumps({"settings": settings, "summary": info, "complete": complete}, indent=1, ensure_ascii=False)
    (page / MANIFEST).write_text(text + "\n", encoding="utf-8")


def up_to_date(page: Path, settings: dict[str, Any]) -> dict[str, Any] | None:
    """The page's summary when it was fully built from this file with these options, else None."""
    try:
        manifest = json.loads((page / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("settings") != settings or manifest.get("complete") is not True:
        return None
    info = manifest.get("summary")
    # A manifest says what was built; the page itself must still be there (a sync tool may have
    # removed part of it).
    if not isinstance(info, dict) or not (page / "index.html").is_file() or not (page / "audio" / "mix.flac").is_file():
        return None
    return info


def _note_older_pages(out: Path, page: Path, source: str, report: Reporter) -> None:
    """A renamed song gets a new page: say where its older pages are (they are not deleted)."""
    if not out.is_dir():
        return
    for other in out.glob("*.woodshed"):
        if other == page:
            continue
        try:
            manifest = json.loads((other / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(manifest, dict)
            and isinstance(manifest.get("settings"), dict)
            and manifest["settings"].get("source") == source
        ):
            report.say(f"  note: an older page of this recording is left at {other}")


def _source(path: str | Path) -> Path:
    src = Path(path).expanduser()
    if not src.is_file():
        raise audio.AudioError(f"{src}: file not found")
    return src.resolve()


@dataclass
class Pass:
    """One song's first pass: its page, its summary, and whether stems are still to come."""

    src: Path
    out: Path
    page: Path
    info: dict[str, Any]
    settings: dict[str, Any]
    stems_to_come: bool
    opts: Options  # as used for this song (its title included), for the second pass
    mix_song: Song | None = None  # to drop the "reload later" banner if the stems fail


def titles(paths: Sequence[str | Path]) -> dict[str, str]:
    """A page title per file, unique once turned into a folder name (case-insensitively, as on
    macOS and Windows): the name without its extension; then with the extension ("pop (mp3)",
    "pop (wav)"); then with its folder ("pop (wav, takes)"); then numbered."""
    shown = {str(p): Path(p).expanduser() for p in paths}

    def key(title: str) -> str:
        return folder_name(title).lower()

    def unique_by(make: Callable[[Path], str], current: dict[str, str]) -> dict[str, str]:
        count = Counter(key(t) for t in current.values())
        return {k: make(shown[k]) if count[key(t)] > 1 else t for k, t in current.items()}

    named = {k: s.stem for k, s in shown.items()}
    named = unique_by(lambda s: f"{s.stem} ({s.suffix.lstrip('.').lower()})", named)
    named = unique_by(lambda s: f"{s.stem} ({s.suffix.lstrip('.').lower()}, {s.resolve().parent.name})", named)
    seen: Counter[str] = Counter()
    for k, t in named.items():  # still equal (same names in same-named folders): numbered
        seen[key(t)] += 1
        if seen[key(t)] > 1:
            named[k] = f"{t} {seen[key(t)]}"
    return named


def _check_bpm(song: Song, report: Reporter) -> None:
    hint = song.analysis.bpm_hint
    if hint and abs(song.bpm / hint - 1) > BPM_TOLERANCE:
        report.say(
            f"  note: the tempo found is {song.bpm:.0f} BPM; --bpm {hint:g} could not be reached by halving or doubling"
        )


def update_page_code(page: Path, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """A complete page built by older page code, its code updated in place (no new analysis).

    With `settings`, only when the page was built with these settings but another page revision.
    Returns the page's summary when updated, else None (up to date, incomplete, or needing a rebuild).
    """
    try:
        manifest = json.loads((page / MANIFEST).read_text(encoding="utf-8"))
        before, info = manifest["settings"], manifest["summary"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(before, dict) or not isinstance(info, dict) or manifest.get("complete") is not True:
        return None
    if before.get("page") == page_revision():
        return None

    def others(s: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in s.items() if k != "page"}

    if settings is not None and others(before) != others(settings):
        return None
    if not (page / "audio" / "mix.flac").is_file() or not refresh_code(page):
        return None
    _record(page, {**before, "page": page_revision()}, info, complete=True)
    return info


def first_pass(
    path: str | Path, opts: Options, report: Reporter, out: Path | None = None, title: str | None = None
) -> Pass:
    """Build the best page possible now: the full page if the stems are cached or not wanted,
    else the mix-only page with a 'reload later' banner. A page already up to date is kept."""
    src = _source(path)
    # Named as the user named it: a link "Morning Song.wav" to "take3.wav" gives "Morning Song".
    shown = Path(path).expanduser()
    opts = replace(opts, title=opts.title or title or shown.stem)
    assert opts.title is not None
    out = (out or opts.out or shown.parent).expanduser().resolve()
    report.say(shown.name)
    use_stems = opts.use_stems and stems_extra_installed()
    if opts.use_stems and not use_stems:
        report.say("  note: " + EXTRA_HINT)
    settings = _settings(src, opts, use_stems)
    page = out / folder_name(opts.title)
    _note_older_pages(out, page, settings["source"], report)
    known = up_to_date(page, settings)
    if known is not None:
        report.say(f"  up to date {page}")
        return Pass(src, out, page, known, settings, False, opts)
    known = update_page_code(page, settings)
    if known is not None:  # built by an older woodshed, same analysis: its page code only
        report.say(f"  page code updated {page}")
        return Pass(src, out, page, known, settings, False, opts)
    cached = stems.cached(src) if use_stems else None
    if use_stems and cached is None:
        seconds = audio.duration(src) * SEPARATION_SPEED
        song = _analyze(src, opts, report, False, None)
        _check_bpm(song, report)
        page = build_page(song, src, out, None, seconds)
        info = summary(song, page)
        _record(page, settings, info, complete=False)
        report.say(f"  page       {page}  (mix only for now)")
        return Pass(src, out, page, info, settings, True, opts, song)
    song = _analyze(src, opts, report, use_stems, cached)
    _check_bpm(song, report)
    page = build_page(song, src, out, cached)
    info = summary(song, page)
    _record(page, settings, info, complete=True)
    report.say(f"  page       {page}  ({_size_mb(page):.1f} MB)")
    return Pass(src, out, page, info, settings, False, opts)


def second_pass(first: Pass, report: Reporter) -> Pass:
    """Separate the stems and rebuild the page with them. If that fails, the page keeps the mix
    and loses its "reload later" banner, and the error goes on."""
    opts = first.opts
    seconds = audio.duration(first.src) * SEPARATION_SPEED
    report.say(
        f"{first.src.name}: separating the instruments, about {max(1, round(seconds / 60))} min on this computer"
    )
    try:
        separated = stems.separate(first.src, offline=opts.offline, progress=report.stems)
        song = _analyze(first.src, opts, report, True, separated)
        page = build_page(song, first.src, first.out, separated)
    except WoodshedError:
        if first.mix_song is not None:
            kept = build_page(first.mix_song, first.src, first.out, None)
            _record(kept, first.settings, summary(first.mix_song, kept), complete=False)
        raise
    info = summary(song, page)
    _record(page, first.settings, info, complete=True)
    report.say(f"  stems ready: reload the page  ({_size_mb(page):.1f} MB)")
    return Pass(first.src, first.out, page, info, first.settings, False, opts)


def run_songs(paths: Sequence[str | Path], opts: Options, report: Reporter) -> list[Path]:
    """A page per song; each opens as soon as it exists, then gets its stems.

    A song that fails is reported and skipped; the others are built, and the run then fails.
    """
    paths = list(dict.fromkeys(paths))  # the same file named twice is one song
    named = titles(paths)
    pages, failed = [], []
    for path in paths:
        if len(paths) == 1:  # one song: its error is the run's error, on one line
            done = first_pass(path, opts, report, title=named[str(path)])
            _open(done.page, opts)
            if done.stems_to_come:
                done = second_pass(done, report)
            report.say(f"done in {time.monotonic() - report.started:.0f} s")
            return [done.page]
        try:
            done = first_pass(path, opts, report, title=named[str(path)])
            _open(done.page, opts)
            if done.stems_to_come:
                done = second_pass(done, report)
            pages.append(done.page)
        except (WoodshedError, OSError) as exc:
            report.say(f"  error: {exc}")
            failed.append(Path(path).name)
    report.say(f"done in {time.monotonic() - report.started:.0f} s")
    if failed:
        raise WoodshedError(f"{len(failed)} of {len(paths)} songs failed: {', '.join(failed)}")
    return pages


def run_song(path: str | Path, opts: Options, report: Reporter) -> Path:
    return run_songs([path], opts, report)[0]


def media_files(root: Path) -> list[Path]:
    """The audio and video files of a folder, without hidden files (macOS "._" copies included)."""
    return sorted(
        (p for p in root.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in audio.MEDIA),
        key=lambda p: p.name.lower(),
    )


def run_folder(folder: str | Path, opts: Options, report: Reporter, out: Path | None = None) -> Path:
    """A songbook: a page for every audio or video file of the folder, and an index page.

    Every mix-only page comes first, so the whole setlist can be opened at once; the stems
    follow song by song, and the index is rewritten as they come. A song that fails is reported
    and left out; the others go on.
    """
    root = Path(folder).expanduser().resolve()
    files = media_files(root)
    if not files:
        raise audio.AudioError(f"{root}: no audio or video file in this folder")
    out = (out or opts.out or root).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    named = titles(files)
    passes: list[Pass] = []
    failed: list[str] = []

    def attempt(name: str, fn: Callable[[], Pass]) -> Pass | None:
        try:
            return fn()
        except (WoodshedError, OSError) as exc:
            report.say(f"  error: {exc}")
            failed.append(name)
            return None

    for f in files:
        done = attempt(f.name, lambda f=f: first_pass(f, opts, report, out, named[str(f)]))  # type: ignore[misc]
        if done is not None:
            passes.append(done)
    index = songbook.write_index(out, root.name, [p.info for p in passes])
    report.say(f"index      {index}")
    _open_file(index, opts)
    for i, p in enumerate(passes):
        if p.stems_to_come:
            done = attempt(p.src.name, lambda p=p: second_pass(p, report))  # type: ignore[misc]
            if done is not None:
                passes[i] = done
                songbook.write_index(out, root.name, [q.info for q in passes])
    report.say(f"done in {time.monotonic() - report.started:.0f} s: {index}")
    if failed:
        raise WoodshedError(f"{len(failed)} of {len(files)} songs failed: {', '.join(failed)}")
    return index


def _open(page: Path, opts: Options) -> None:
    _open_file(page / "index.html", opts)


def _open_file(path: Path, opts: Options) -> None:
    if opts.open_page:
        webbrowser.open(path.as_uri())


__all__ = ["Options", "Reporter", "run_folder", "run_song", "run_songs"]
