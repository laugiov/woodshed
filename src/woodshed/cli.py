"""Command-line interface.

woodshed SONG [SONG ...]   build a practice page per song and open it
woodshed chart SONG        the text chart (timeline and bar grid)
woodshed cache             where the stems and models are; clear them
woodshed uninstall         remove woodshed from this computer (the songs stay)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from woodshed import __version__
from woodshed.errors import WoodshedError

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
COMMANDS = ("chart", "cache", "app", "lyrics", "uninstall")


def _meter(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--beats-per-bar", type=int, default=4, metavar="N", help="beats per bar: 3 for a waltz (default 4)"
    )
    parser.add_argument("--sevenths", action="store_true", help="also detect 7 and m7 chords (less reliable)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="woodshed",
        description="Turn a song file into a local practice room: chart, parts and play-along, offline.",
        epilog="Other commands: 'woodshed app' opens your library in the browser; 'woodshed chart SONG' prints"
        " the text chart; 'woodshed lyrics PAGE WORDS.txt' puts the words on a page; 'woodshed cache' manages"
        " the cache; 'woodshed uninstall' removes woodshed (your songs stay).",
    )
    parser.add_argument("--version", action="version", version=f"woodshed {__version__}")
    parser.add_argument(
        "songs", nargs="+", metavar="SONG", help="audio or video files, or a folder of them (a songbook)"
    )
    parser.add_argument(
        "-o", "--out", type=Path, metavar="DIR", help="where the page folders go (default: next to each song)"
    )
    parser.add_argument("--no-stems", action="store_true", help="analyse the mix only: no instrument tracks or parts")
    parser.add_argument(
        "--separation", choices=("four", "six"),
        help="six: guitar and keys apart (default for a new page); four: together, the model of pages made before",
    )  # fmt: skip
    parser.add_argument("--offline", action="store_true", help="never download models (they must be in the cache)")
    parser.add_argument("--no-open", action="store_true", help="do not open the page in the browser")
    parser.add_argument("--title", help="page title (one song only)")
    parser.add_argument("--bpm", type=float, help="the tempo you hear: settles half or double time")
    parser.add_argument(
        "--bar-phase",
        type=int,
        metavar="N",
        help="the song's beats before its first bar line, a pickup (0 to beats-per-bar - 1); automatic if absent",
    )
    _meter(parser)
    parser.add_argument("--debug", action="store_true", help="show the full error trace")
    return parser


def chart_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="woodshed chart", description="Print the chords as a timeline and a bar grid."
    )
    parser.add_argument("song", metavar="SONG")
    _meter(parser)
    parser.add_argument(
        "--offset",
        type=int,
        help="empty beats drawn before the song's first beat (0 to beats-per-bar - 1); automatic if absent",
    )
    parser.add_argument("--json", type=Path, metavar="FILE", help="also write the result as JSON")
    parser.add_argument("--txt", type=Path, metavar="FILE", help="also write the text chart")
    parser.add_argument("--debug", action="store_true", help="show the full error trace")
    return parser


def cache_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="woodshed cache", description="Show or clear the stems and models cache.")
    parser.add_argument("--clear", action="store_true", help="delete the separated stems")
    parser.add_argument("--models", action="store_true", help="with --clear, also delete the downloaded models")
    return parser


def lyrics_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="woodshed lyrics",
        description="Place the words of a song on its page: each chord above the syllable where it changes.",
        epilog="The words are placed by MMS, a speech model by Meta (CC-BY-NC 4.0: for non-commercial use),"
        " run on this computer and downloaded once (1.2 GB). You are responsible for the texts you paste.",
    )
    parser.add_argument("page", type=Path, help="the song's page folder (NAME.woodshed)")
    parser.add_argument("text", type=Path, help="a text file with the words, as pasted from anywhere")
    parser.add_argument("--offline", action="store_true", help="never download the speech model")
    parser.add_argument("--debug", action="store_true", help="show the full error trace")
    return parser


def app_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="woodshed app", description="A home page for your songs, in the browser: list, add, play."
    )
    parser.add_argument(
        "library", nargs="?", type=Path, default=Path("~/woodshed"), help="the songs folder (default ~/woodshed)"
    )
    parser.add_argument("--port", type=int, default=8000, help="port on this computer (default 8000)")
    parser.add_argument(
        "--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1: this computer only)"
    )
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    parser.add_argument("--no-stems", action="store_true", help="analyse the mix only")
    parser.add_argument(
        "--separation", choices=("four", "six"),
        help="six: guitar and keys apart (default for a new page); four: together, the model of pages made before",
    )  # fmt: skip
    parser.add_argument(
        "--no-pitch", action="store_true", help="never render a song's tracks in another key (the singer's key)"
    )
    parser.add_argument("--offline", action="store_true", help="never download models")
    parser.add_argument(
        "--allow-network", action="store_true",
        help="needed with a --host other than this computer: anyone who reaches the port can use the library",
    )  # fmt: skip
    parser.add_argument(
        "--uploads-from-network", action="store_true",
        help="let other devices add songs too (in Docker: the published port comes through the network)",
    )  # fmt: skip
    parser.add_argument(
        "--cert", type=Path, default=os.environ.get("WOODSHED_CERT") or None, metavar="FILE",
        help="serve the band's phones over HTTPS with this certificate (made with mkcert, say); with --key",
    )  # fmt: skip
    parser.add_argument(
        "--key", type=Path, default=os.environ.get("WOODSHED_KEY") or None, metavar="FILE",
        help="the certificate's private key, outside the library folder; with --cert",
    )  # fmt: skip
    return parser


def run_app(argv: Sequence[str]) -> int:
    parser = app_parser()
    args = parser.parse_args(argv)
    from woodshed.app import LOOPBACK, serve

    if args.host not in LOOPBACK and not args.allow_network:
        parser.error(f"--host {args.host} opens the library to the network: add --allow-network if that is meant")
    if (args.cert is None) != (args.key is None):
        parser.error("--cert and --key go together (or WOODSHED_CERT and WOODSHED_KEY)")
    from woodshed.run import Options

    opts = Options(
        use_stems=not args.no_stems, offline=args.offline, open_page=False, pitch=not args.no_pitch,
        separation=args.separation,
    )  # fmt: skip
    try:
        serve(
            args.library, opts, args.host, args.port, open_browser=not args.no_open,
            uploads_from_network=args.uploads_from_network, tls=(args.cert, args.key) if args.cert else None,
        )  # fmt: skip
    except KeyboardInterrupt:
        print("woodshed app: stopped", file=sys.stderr)
    except WoodshedError as exc:  # a certificate that cannot be used: said before anything starts
        print(f"woodshed app: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:  # the port is taken, the folder cannot be written...
        print(f"woodshed app: {exc}", file=sys.stderr)
        if isinstance(exc, PermissionError) and os.environ.get("WOODSHED_CONTAINER") == "1":
            # Docker created the missing library folder for root: the container's user cannot write it.
            print(
                "woodshed app: create the library folder before starting the container (mkdir woodshed),"
                " or give it to the container's user: sudo chown 1000:1000 woodshed",
                file=sys.stderr,
            )
        return EXIT_ERROR
    return EXIT_OK


def _check_meter(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not 2 <= args.beats_per_bar <= 12:
        parser.error("--beats-per-bar must be between 2 and 12")


def _guarded(debug: bool, fn: Callable[[], int]) -> int:
    try:
        return fn()
    except KeyboardInterrupt:
        print("woodshed: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except (WoodshedError, OSError) as exc:  # OSError: an output folder that is a file, read-only...
        if debug:
            traceback.print_exc()
        print(f"woodshed: {exc}", file=sys.stderr)
        return EXIT_ERROR


def run_pages(argv: Sequence[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _check_meter(parser, args)
    if args.title and (len(args.songs) > 1 or Path(args.songs[0]).is_dir()):
        parser.error("--title needs a single song")
    if args.bpm is not None and not 30 <= args.bpm <= 300:
        parser.error("--bpm must be between 30 and 300")
    if args.bar_phase is not None and not 0 <= args.bar_phase < args.beats_per_bar:
        parser.error("--bar-phase must be between 0 and beats-per-bar - 1")
    from woodshed.run import Options, Reporter, run_folder, run_songs

    opts = Options(
        out=args.out, use_stems=not args.no_stems, offline=args.offline, open_page=not args.no_open, title=args.title,
        separation=args.separation,
        beats_per_bar=args.beats_per_bar, sevenths=args.sevenths, bpm=args.bpm, bar_phase=args.bar_phase,
    )  # fmt: skip

    def work() -> int:
        folders = [s for s in args.songs if Path(s).is_dir()]  # a folder is a songbook
        files = [s for s in args.songs if not Path(s).is_dir()]
        failures = []
        jobs: list[tuple[str, Callable[[], object]]] = []
        if files:
            jobs.append((", ".join(files), lambda: run_songs(files, opts, Reporter())))
        for folder in folders:
            # With -o and several songbooks, each gets its own folder: their index pages differ.
            sub = args.out / Path(folder).resolve().name if args.out and len(folders) > 1 else None
            jobs.append((folder, partial(run_folder, folder, opts, Reporter(), sub)))
        for name, job in jobs:  # one failing part does not stop the others
            try:
                job()
            except (WoodshedError, OSError) as exc:
                if len(jobs) == 1:
                    raise
                print(f"woodshed: {exc}", file=sys.stderr)
                failures.append(name)
        return EXIT_ERROR if failures else EXIT_OK

    return _guarded(args.debug, work)


def run_chart(argv: Sequence[str]) -> int:
    parser = chart_parser()
    args = parser.parse_args(argv)
    _check_meter(parser, args)
    if args.offset is not None and not 0 <= args.offset < args.beats_per_bar:
        parser.error("--offset must be between 0 and beats-per-bar - 1")
    from woodshed.chart import chart

    def work() -> int:
        result = chart(args.song, args.sevenths, args.beats_per_bar, args.offset)
        print(result.text, end="")
        if args.txt:
            args.txt.write_text(result.text, encoding="utf-8")
        if args.json:
            args.json.write_text(json.dumps(result.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return EXIT_OK

    return _guarded(args.debug, work)


def run_lyrics(argv: Sequence[str]) -> int:
    args = lyrics_parser().parse_args(argv)
    from woodshed import lyrics

    def work() -> int:
        page = args.page.expanduser()
        raw = args.text.expanduser().read_bytes()
        try:
            # Notepad's "Unicode" is UTF-16; its UTF-8 starts with a mark.
            text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")  # older Windows text files
        from woodshed import app

        notes: list[str] = []  # the band's fixes on the sheet, carried as the library carries them
        say = lambda line: print(line, file=sys.stderr)  # noqa: E731
        data = lyrics.add_to_page(page, text, args.offline, say=say, commit=app.lyrics_commit(page, notes))
        lines = data["lines"]
        sung = sum(ln["sung"] for ln in lines)
        print(f"{sung} of {len(lines)} lines placed on the voice; lyrics in {page / lyrics.LYRICS}")
        for note in notes:
            print("  " + note)
        if data.get("sections"):
            print("  parts named by the words: " + ", ".join(sec["name"] for sec in data["sections"]))
        for k, ln in enumerate(lines):
            if ln["check"]:
                print(f"  line {k + 1}: {ln['check']}: {ln['text'][:50]}")
        return EXIT_OK

    return _guarded(args.debug, work)


def _size(folder: Path) -> str:
    total = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) if folder.exists() else 0
    return f"{total / 1e6:.1f} MB"


def run_cache(argv: Sequence[str]) -> int:
    parser = cache_parser()
    args = parser.parse_args(argv)
    if args.models and not args.clear:
        parser.error("--models goes with --clear")
    from woodshed.cache import cache_dir

    root = cache_dir()
    if args.clear:
        shutil.rmtree(root / "stems", ignore_errors=True)
        if args.models:
            shutil.rmtree(root / "models", ignore_errors=True)
    print(f"cache: {root}")
    print(f"  stems   {_size(root / 'stems')}")
    print(f"  models  {_size(root / 'models')}")
    return EXIT_OK


def run_uninstall(argv: Sequence[str]) -> int:
    from woodshed import uninstall

    return uninstall.main(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # "chart" and "cache" are commands, unless a file of that name is meant.
    if args and args[0] in COMMANDS and not Path(args[0]).exists():
        commands = {
            "chart": run_chart,
            "cache": run_cache,
            "app": run_app,
            "lyrics": run_lyrics,
            "uninstall": run_uninstall,
        }
        return commands[args[0]](args[1:])
    return run_pages(args)
