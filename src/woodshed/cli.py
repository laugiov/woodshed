"""Command-line interface.

woodshed SONG [SONG ...]   build a practice page per song and open it
woodshed chart SONG        the text chart (timeline and bar grid)
woodshed cache             where the stems and models are; clear them
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from woodshed import __version__
from woodshed.errors import WoodshedError

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
COMMANDS = ("chart", "cache")


def _meter(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--beats-per-bar", type=int, default=4, metavar="N", help="beats per bar: 3 for a waltz (default 4)"
    )
    parser.add_argument("--sevenths", action="store_true", help="also detect 7 and m7 chords (less reliable)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="woodshed",
        description="Turn a song file into a local practice room: chart, parts and play-along, offline.",
        epilog="Other commands: 'woodshed chart SONG' prints the text chart; 'woodshed cache' manages the cache.",
    )
    parser.add_argument("--version", action="version", version=f"woodshed {__version__}")
    parser.add_argument(
        "songs", nargs="+", metavar="SONG", help="audio or video files, or a folder of them (a songbook)"
    )
    parser.add_argument(
        "-o", "--out", type=Path, metavar="DIR", help="where the page folders go (default: next to each song)"
    )
    parser.add_argument("--no-stems", action="store_true", help="analyse the mix only: no instrument tracks or parts")
    parser.add_argument("--offline", action="store_true", help="never download models (they must be in the cache)")
    parser.add_argument("--no-open", action="store_true", help="do not open the page in the browser")
    parser.add_argument("--title", help="page title (one song only)")
    parser.add_argument("--bpm", type=float, help="the tempo you hear: settles half or double time")
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
        "--offset", type=int, help="beats before the first bar line (0 to beats-per-bar - 1); automatic if absent"
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
    from woodshed.run import Options, Reporter, run_folder, run_songs

    opts = Options(
        out=args.out, use_stems=not args.no_stems, offline=args.offline, open_page=not args.no_open, title=args.title,
        beats_per_bar=args.beats_per_bar, sevenths=args.sevenths, bpm=args.bpm,
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


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # "chart" and "cache" are commands, unless a file of that name is meant.
    if args and args[0] in COMMANDS and not Path(args[0]).exists():
        return {"chart": run_chart, "cache": run_cache}[args[0]](args[1:])
    return run_pages(args)
