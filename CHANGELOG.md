# Changelog

What changed in woodshed, for the musicians who use it: what you can do now, and what got fixed.
Newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
version numbers [Semantic Versioning](https://semver.org/).

To update: close woodshed, download the installer again from the
[latest release](https://github.com/laugiov/woodshed/releases/latest) and run it. Your songs,
corrections and set list stay where they are.

## [Unreleased]

### Added

- **Rehearsal**, next to Stage mode: the whole song on one screen, as on a band's old chord sheets. The title,
  the key, the tempo and the capo, the song's notes, the parts with simple chords over the words, the bars with
  no words as bar lines (`| G D | Am |`), a part played twice in a row written once ("Chorus ×2"), and the chord
  boxes. It fits the screen in columns, turns pages with the arrows or a pedal on a phone, marks the line the
  band is at, and stays open from song to song of the set. Chords as Triads, Usual (the default) or As heard.
- Notes on a song ("Start: drums count 4, then guitar", "End: stop on the 1"), on several lines: written on
  the song's page, shown under its title, on stage and on the rehearsal sheet, and in the set list.
- Rename a song and its artist from its page (✎ beside the title): the library, the set list, the tab and the
  exports follow; the recording's title comes back in one click.

### Changed

- A guitarist with a capo now reads the shapes played by default, on the chart and on stage, with the switch
  to the real chords first above the chart and on stage; the choice is remembered on each device.
- A song's note now stays when the song leaves the set (it is the song's, no longer the set's): notes an older
  version kept on songs out of the set show again.

## [0.7.0] - 2026-10-30

### Added

- Six looks for the whole app, chosen from the new **Style** button next to the theme button, on each
  device: **woodshed**, **Spotlight** (the most contrast, black on white for an outdoor gig in the sun,
  white and yellow on black for a dark stage, nothing else on screen), **Disco 70** (a mirror ball
  that turns while the song plays), **Mixtape 80** (a cassette whose reels turn, with the set's name on
  its label), **Grunge 90** (a CD that spins, flannel and photocopies) and **Y2K** (an MP3 player and an
  equaliser that dances). Each has its light and dark theme; the chords and the words keep their
  fonts and their contrast in all of them, the stage view and the printed set stay plain.
- Name the set: **+ Name the set** on the library's set list ("Les Imprévus · season 2026-2027"). The
  name heads the set on every library open on the band's devices at once, the printed set and the
  browser's tab.

## [0.6.0] - 2026-10-25

### Added

- In the Lyrics view, a line that opens on a chord still sounding from before shows it, small and
  grey over its first word ("Cm", "N.C."), so a line with no change never reads as "no chord found".
  Also on the guitar and keys words stage (the lines coming), never on the singer's stage; a screen
  reader hears each line's opening chord.
- Fix a line of the words right on the sheet: **Edit chords and words**, click the line, type, Enter.
  Only that line is placed again, in a blink, and the lines around it do not move; every device of
  the band shows it, and Undo or **Back to the placement** brings it back. A line someone else sings
  or speaks can be marked **Other voice / spoken** (kept on the sheet, off the singer's stage), and
  a line the recording does not have, **Not in this recording**. The chord of each bar of the line
  opens from there. The stage, the phones and the ChordPro export read the fixed words, and placing
  all the words again keeps each fix whose line still reads the same.
- Split a line of the words or join two, right on the sheet: in the line editor, **Shift+Enter** (or
  **Split at the cursor**) breaks the line where the cursor is, and **Join with the next line** makes
  two lines of one part a single line. The library places them in the line's own time, the lines
  around do not move, and Undo or **Back to the placement** takes back the whole split or join. The
  songbook file of the page (`exports/*.cho`) is written again with the band's fixes after each one.
- Type the words yourself, no model needed, in any language and for any use (paid gigs included):
  **+ Type a line here** in Edit mode, then the line as you would write it under the bars, `|`
  before the word on beat one (`When you walk, | I stum- ble _ on`). The words share each bar by
  syllables, the editor reads the line back before saving, and the band sees it live. A typed line
  covers the placed line under it while it is there. Move any word half a beat with ◀ ▶, a tap on
  its place in the bar, or **M** from the keyboard.
- Paste all the words and tap along, no model needed: **Words** opens one dialog with two paths,
  **Lay them by tapping along** (no model, any language, any use) and **Place them on the voice**
  (the speech model, its non-commercial licence said under it). Tapping along plays the song: tap
  Space, a pedal or the big button on a phone as each line starts, Escape to stop. Each tap snaps to
  the nearest quarter beat, the words share the line by syllables, and one Undo takes the whole layout
  back. Laying them again replaces only the lines the last layout laid, never a line typed by hand.
- `woodshed app --no-words-model` (or `WOODSHED_NO_WORDS_MODEL=1`, for Docker) starts a library that
  never offers nor runs the speech model: for a band paid to play, only tapping along and typing.
- An older woodshed opened on the same library keeps the chords, but forgets the lines fixed on the
  sheet the next time it saves a chord: update every computer that runs the library.

### Fixed

- The switch that plays the recording in the chart's key takes every press: a press made just as
  the page updated its line (a key settling, the library saying where it is) was sometimes lost and
  the switch stayed off.

## [0.5.1] - 2026-10-24

### Changed

- On a song that changes key, the Key box shows every key, "A → B♭", with the key of the bar you are
  in lit; it no longer says "A" beside B♭ shapes. The toasts, the recording's switch and a screen
  reader name the keys the same way. On a phone, "Capo" stays with its box.

### Fixed

- The keyboard stays where you are: with the song stopped, the page scrolls to the bar you move to
  with the arrows, and the arrows go on from the bar you are on. After you press an instrument, a
  step of the practice path, Edit the chart, Done or Stage mode, the keyboard stays on that button
  (Tab goes on to the next one, not back to the top), and Escape out of the stage brings it back
  where it was. A screen reader says which instrument, voicing and chord sound are pressed. A pedal
  works as before.

- After a key change, the voice panel shows the range of the ending under the song's, and says in
  one sentence whether it goes higher ("From bar 82 it goes higher: up to D4.") or stays within the
  rest of the song. The best key for your voice now fits the ending too, and the line "Up a semitone
  at bar 82: B♭ major." is as easy to read as the best key under it. Songs added before this version
  get it in the background, a few seconds after the library starts.

- A song page's footer says which version runs the page and which one found its chords: "Page:
  woodshed 0.5.0 · chords and beats found by woodshed 0.4.0 (still current)". After an update it
  no longer says "Made with woodshed 0.4.0" on a page the library had already brought up to date.
- Tapping **Lead** on a phone that follows now takes over the band: the song goes on from where the
  band is, and the device that led follows. It used to stop the band and leave nobody leading. If
  two devices tap Lead at once, the first leads and the other is told.

## [0.5.0] - 2026-10-23

### Added

- **Uninstall woodshed** next to woodshed: in Applications on a Mac, the Start menu and Settings >
  Apps on Windows, the menu on Linux. It asks once, removes woodshed and what it downloaded (about
  1 GB), and keeps your songs.
- A guide for each musician next to a short README: install, singers, parts, phones, editing,
  exports, how it works, and what the app's messages mean. The first-install warnings of a Mac and
  of Windows are drawn step by step.
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

[Unreleased]: https://github.com/laugiov/woodshed/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/laugiov/woodshed/releases/tag/v0.7.0
[0.6.0]: https://github.com/laugiov/woodshed/releases/tag/v0.6.0
[0.5.1]: https://github.com/laugiov/woodshed/releases/tag/v0.5.1
[0.5.0]: https://github.com/laugiov/woodshed/releases/tag/v0.5.0
[0.4.0]: https://github.com/laugiov/woodshed/releases/tag/v0.4.0
[0.3.0]: https://github.com/laugiov/woodshed/releases/tag/v0.3.0
[0.2.0]: https://github.com/laugiov/woodshed/releases/tag/v0.2.0
[0.1.0]: https://github.com/laugiov/woodshed/releases/tag/v0.1.0
