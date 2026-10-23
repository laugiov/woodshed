"""Key changes (spec 012, lot 14a): found where a song really changes key, never on a relative-minor bridge or a
mixolydian vamp; the chords after a change weighted toward the new key; the parts' numerals in their key."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import synth
from woodshed import analysis, theory


def regions(name: str, folder: Path) -> list[tuple[int, int, str]]:
    song = analysis.analyze(
        synth.write(name, folder).wav, use_stems=False, beats_per_bar=synth.SONGS[name].beats_per_bar
    )
    return [(r.bar, r.key.tonic, r.key.mode) for r in song.key_regions]


@pytest.mark.parametrize("name", sorted(synth.KEY_REGIONS))
def test_a_lift_is_found_on_the_bar_the_new_key_starts(name: str, tmp_path: Path) -> None:
    expected = [(bar, synth.parse(key)[0], "maj") for bar, key in synth.KEY_REGIONS[name]]
    assert regions(name, tmp_path) == expected


@pytest.mark.parametrize("name", sorted(set(synth.SONGS) - set(synth.KEY_REGIONS)))
def test_a_song_in_one_key_has_one_region(name: str, tmp_path: Path) -> None:
    found = regions(name, tmp_path)
    assert len(found) == 1 and found[0][0] == 0  # the bridge on the relative minor and the mixolydian vamp too


def test_the_song_s_key_is_its_longest_region(tmp_path: Path) -> None:
    song = analysis.analyze(synth.write("lift2", tmp_path).wav, use_stems=False)
    assert (song.key.tonic, song.key.mode) == (0, "maj")  # C for 16 bars, D for 12: C (one key for all said G)


def test_each_part_reads_its_numerals_in_its_own_key(tmp_path: Path) -> None:
    song = analysis.analyze(synth.write("lift", tmp_path).wav, use_stems=False)
    romans = [tuple(s.romans) for s in song.harmony.sections]
    assert romans and all(r[:4] == ("I", "V", "vi", "IV") for r in romans)  # in C, then in Db: no bII


def test_key_at_reads_the_region_of_a_bar() -> None:
    from woodshed.model import KeyRegion

    c, db = theory.Key(0, "maj"), theory.Key(1, "maj")
    found = [KeyRegion(0, c), KeyRegion(16, db)]
    assert [analysis.key_at(found, b) for b in (0, 15, 16, 30)] == [c, c, db, db]
