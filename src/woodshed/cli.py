"""Command-line interface."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from woodshed import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="woodshed",
        description="Turn a song file into a local practice room.",
    )
    parser.add_argument("--version", action="version", version=f"woodshed {__version__}")
    parser.add_argument("song", help="audio or video file to analyse")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.exit(2, "woodshed: analysis is not implemented yet\n")
