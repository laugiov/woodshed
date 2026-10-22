"""Moving the bar lines: the bar phase chosen by the band (the beat the band counts "one" on)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import synth
from woodshed import analysis, cli
from woodshed.model import Song
from woodshed.run import MANIFEST, Options, Reporter, first_pass


@pytest.fixture(scope="module")
def pop(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return synth.write("pop", tmp_path_factory.mktemp("offset")).wav


def phase(song: Song) -> int:
    per = song.beats_per_bar
    return int(song.structure.first_beat % per)


def test_the_offset_chosen_is_where_the_bars_start_and_the_beats_do_not_move(pop: Path) -> None:
    auto = analysis.analyze(pop, use_stems=False)
    for shift in (1, 2, 3):
        wanted = (phase(auto) + shift) % auto.beats_per_bar
        moved = analysis.analyze(pop, use_stems=False, offset=wanted)
        assert phase(moved) == wanted
        assert moved.beats == auto.beats  # typed chords stay on their beats
    assert phase(analysis.analyze(pop, use_stems=False, offset=phase(auto))) == phase(auto)


def test_the_offset_is_kept_with_the_page_and_only_when_chosen(pop: Path, tmp_path: Path) -> None:
    out = tmp_path / "lib"
    first_pass(pop, Options(out=out, use_stems=False, open_page=False), Reporter(), out)
    settings = json.loads((out / "pop.woodshed" / MANIFEST).read_text(encoding="utf-8"))["settings"]
    assert "offset" not in settings  # every page built before stays up to date
    first_pass(pop, Options(out=out, use_stems=False, open_page=False, offset=1), Reporter(), out)
    settings = json.loads((out / "pop.woodshed" / MANIFEST).read_text(encoding="utf-8"))["settings"]
    assert settings["offset"] == 1  # a later rebuild keeps it


def test_the_command_takes_the_offset_and_checks_it(
    pop: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(pop), "--no-stems", "--no-open", "--offset", "4"])
    assert exc.value.code == 2 and "--offset" in capsys.readouterr().err
    assert cli.main([str(pop), "--no-stems", "--no-open", "--offset", "1", "-o", str(tmp_path)]) == 0
    settings = json.loads((tmp_path / "pop.woodshed" / MANIFEST).read_text(encoding="utf-8"))["settings"]
    assert settings["offset"] == 1
