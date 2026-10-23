# Changelog

What changed in woodshed, for the musicians who use it: what you can do now, and what got fixed.
Newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
version numbers [Semantic Versioning](https://semver.org/).

To update: close woodshed, download the installer again from the
[latest release](https://github.com/laugiov/woodshed/releases/latest) and run it. Your songs,
corrections and set list stay where they are.

## [Unreleased]

### Added

- A key change is said where the band meets it. On stage, two bars before it: "Key change next bar:
  D♭ major", and the top line always says the key of the bar you are in.
- The guitar's shapes come grouped by key ("From bar 17: D♭ major"), with a word for the hands when
  the song lifts.
- The voice panel says "Up a semitone at bar 17" before you pick a key, and the words view shows the
  change on stage too.
- Where the chords around a change are unsure, its mark says "check by ear".
- The library page shows its version, with links to this list and to how to update.
- Singers on stage: the line you are singing is always on screen, at the top, and stopped, the line
  you sing next comes first, marked "Next:" (also after "Part ⏭").
- The recording in the singer's key works on a Mac installed with the download, with no extra step:
  the installers add the Rubber Band program woodshed uses to change the key (on Windows too).
- Keyboard: Space presses a button you reached with Tab (and still plays or pauses otherwise, so
  pedals work as before); in the chart the arrows move from bar to bar; in the bar editor Enter
  saves and Ctrl+Enter (⌘+Enter on a Mac) saves and opens the next bar.

### Changed

- ChordPro reads as a sheet for OnSong and the music stand: a sung line is never cut by a row of
  chords, N.C. (no chord) is never a chord to transpose, repeated rows are folded ("x2"), and a key
  change is said where it happens ("Key change: D♭ major").
- The keys panel's rhythm says it is the guitar's strumming when it is, and step 2 no longer
  promises chord shapes for the keys when no keys are heard.

### Fixed

- The keys panel tells what the record really holds in each bar: a bar with no chord says so, a
  third that disagrees with the chart is named ("The record has D♯ here, the chart says Bm: check
  this bar by ear"), and where the keys are often read as a single note it says to play the chart's
  chord there.
- While the recording is being prepared in another key, the page no longer says it "plays in A" next to
  a switch that says On: it says the recording catches up in a few seconds.
- The screen-lock hint on a phone no longer flashes while the screen is kept on, and stays (with the
  settings to change) when it may really lock.
- A band note belongs to the set: it goes when its song leaves the set, and it is no longer in warning
  orange.
- Step 4 is called "Play with the band", not to be confused with the Play button.
- A chord to check is no longer a button inside the bar's button: screen readers say "chord to check"
  on the bar.
- A long chart with a key change printed a blank last page.
- Switching key quickly could leave an unused audio track loading in the background.

## [0.4.0] - 2026-10-23

### Added

- Guitar and keys on their own tracks: new songs are split into six tracks, guitar and keys now
  apart (keys takes the piano, plus the synths and organ that land on no other track). Your part
  alone is really yours, and the mix without it leaves only your instrument out.
- The strumming rhythm is read from the guitar, the keyboard voicing from the keys.
- An instrument the song does not have says so ("No keys heard in this song"), and the full mix
  plays.
- Key changes: a last chorus lifted a semitone, a bridge in another key. The chart marks the bar
  ("→ D♭ major"), and from there the numerals and the chord names read in the new key (I V vi IV
  again, G♭ not F♯).
- The header says "C major → D♭ major", the stage view says the next part's key, the words show the
  change above their line, and the library and the set list say the key a song ends in.
- ChordPro and MusicXML exports change key where the song does.
- iPad and tablets open the library from the computer running woodshed on the same Wi-Fi, like a
  phone (tried in Safari's engine, not yet on a real iPad).

### Changed

- To keep guitar and keys together for new songs, uncheck **Guitar and keys apart** under
  **Options for the next songs**. Songs made before keep their tracks.
- A song now takes about 20 % more disk, and the first song downloads one more model (about 50 MB).
- A bridge on the relative minor, a rock vamp or a few borrowed chords stay in the song's key: a
  change counts when the new key holds 8 bars or more.
- A song made before reads in one key: add it again to have its key changes found (a minute or two;
  the bars your band typed stay).

### Fixed

- On iPad and iPhone, a tap now lets every track play; a track switch the browser refuses keeps the
  music going and asks for another tap, instead of a silence.

## [0.3.0] - 2026-10-23

### Added

- Edit the chart: type any bar as on a chord sheet (`G . Am .`, `D/F#`, `Asus4`, `%` for the bar
  before), hear it, pick among the chords the analysis heard, and type it on every repeat of that
  line at once.
- 20 chord qualities, slash basses included: shapes, keys, the capo, the stage view and every export
  follow what you type.
- Rename the parts as your band calls them, join two, or start one on any bar.
- **Bar lines**: bar lines one beat off? Say where beat one is, and the song is analysed again with
  the bars there; your typed chords stay on their beats.
- Everything typed goes back to the analysis a bar at a time or all at once (with an undo), and
  reaches the band's phones live.
- Each instrument panel opens on **Listen to**: the full mix, your part alone, or the song without
  it, switched while the music plays. Take both files home, lossless.
- The singer's key in the recording too: **Play the recording 2 semitones up** renders the tracks in
  that key, in tune, and the page switches to them without stopping. The library page says when
  your computer cannot do it.
- A phone that follows, leads or shows the stage view keeps its screen on (plug it in on a long
  rehearsal). If it may still lock, it says where to turn its sleep off.
- Optional HTTPS for the band's phones, walked through for iPhone and Android in the README.

### Changed

- The library page lists your songs, with the set list beside them.

## [0.2.0] - 2026-10-22

### Added

- **Back to the analysis**: a chord you corrected can be taken back to the analysis's chord, on every
  device of the band, and the exports follow.
- The chart names the bars where a chorus is played with other chords than the first one.
- Print: each part stays on one page when it fits, with the song's guitar shapes on top.
- A set sheet for the music stand: big titles, key and tempo in bold, the total time, your notes.
- On a tablet held upright, the guitar shapes of the chord now and the next one ride above the
  player.
- A singer's tablet opens on the words, and stage mode says what comes next when you stop.
- Guitar: the panel names the capo woodshed chooses, with the barre chords it saves, and a button to
  put it on.
- Bass: a looped passage shows the tab of each of its bars, and bars with no bass are said in one
  line.

### Changed

- ChordPro for OnSong and other songbook apps: one chord per word, chords with no word on rows of
  their own, in the key the page shows (the band's key included), and the bars to check by ear.
- The band modes (Lead, Follow, Alone) are explained in words on touch screens.
- Adding words happens on the computer that runs woodshed; the band's phones no longer offer it.
- The keyboard works everywhere: the doubt popover keeps it, and the song's parts are one tab stop,
  moved with the arrow keys.

### Fixed

- Drums say the same groove in the text, the notation, the grid, what you hear and the MIDI. When
  nothing comes back steadily, the page says "no clear groove" instead of drawing one.

## [0.1.0] - 2026-10-16

### Added

- The first release: turn a recording into a practice room for your whole band, on your own
  computer, offline.
- The chart: chords above the words you paste, parts named Verse, Chorus, Solo, and the places where
  the analysis hesitates marked "check by ear", with a popover to pick the chord you hear.
- Your instrument: guitar shapes (open, barre, capo, funk), bass tab, keys voicings, the drum groove,
  and the vocal range with the key that suits your voice.
- Practice: listen, learn, loop it slow with a tempo trainer, then play along with your own part
  muted. The page follows the song while it plays.
- The band: one device leads, every phone follows to the bar. A set list with each song's key,
  tempo, length and a note; the band's key per song and every correction on every device.
- Stage mode: the chord now and next in huge type, the words, guitar shapes, big touch buttons.
- Exports: ChordPro with the words (OnSong, SongbookPro), MIDI, MusicXML (MuseScore), and a compact
  print for the music stand. A song's folder can be zipped and sent: it opens offline.
- English or French, dark or light.

[Unreleased]: https://github.com/laugiov/woodshed/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/laugiov/woodshed/releases/tag/v0.4.0
[0.3.0]: https://github.com/laugiov/woodshed/releases/tag/v0.3.0
[0.2.0]: https://github.com/laugiov/woodshed/releases/tag/v0.2.0
[0.1.0]: https://github.com/laugiov/woodshed/releases/tag/v0.1.0
