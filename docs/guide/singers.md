# For singers

Paste the words, pick **Voice**, find your key, and the whole band plays in it: the chart, the
shapes, every phone, and the recording itself.

## The words, with the chords above them

<img src="../images/lyrics.png" alt="The Lyrics view: chords above the words, bar lines numbered, the line being sung lit" width="100%">

In the library, a song offers **add the words**; on its page, **+ Add the words** next to the
chart. Paste them (part names like `[Chorus]` help; one line per sung line), then pick one of two
paths:

- **Lay them by tapping along**: no model, any language, free for any use (paid gigs included). See
  [Tap along](#tap-along) below.
- **Place them on the voice**: woodshed listens to the singer's own track and places each line on it
  (a progress bar shows how far it is); a minute later the page shows each chord above the word it
  lands on. The first time takes longer: the model is downloaded once. It needs the song built with
  its instrument tracks, and its licence allows non-commercial use only (see below).

The library computer can start without the model: `woodshed app --no-words-model` (or
`WOODSHED_NO_WORDS_MODEL=1`, for Docker). Then only tapping along and typing are offered.

Bar lines are numbered, pushes are marked, and the line being sung lights up as the song plays.
Click a word to jump there. Instrumental bars stay a grid, so a solo never hides inside a lyric
line.

A chord is written where it changes. A line that opens on a chord still sounding from before shows
it anyway, small and grey over its first word ("Cm", or "N.C." when nothing is played): a grey chord
means "keep playing it", a bold one is a change. One line above the words says so, and a screen
reader hears each line's opening chord ("still Cm"). The singer's stage keeps to the words.

From the command line, or for a page opened from disk: `woodshed lyrics "Song.woodshed" words.txt`.

### Fix a line on the sheet

A typo, a number, a line the MC speaks: press **Edit chords and words**, then click (or tap) the
line. Fix the words and press **Enter**: only that line is placed again, in a blink, on the voice
heard the first time; the lines around it do not move, and every device of the band shows the fix.
**Undo** is in the note and in the strip (**Ctrl+Z**, **⌘+Z** on a Mac); **Back to the placement**
gives the line back as it was placed.

- **Other voice / spoken**: a line someone else sings or speaks stays on the sheet with its chords,
  in quieter letters, off your stage view and its "Next:".
- **Not in this recording**: the line leaves the sheet, the stage and the ChordPro; in Edit mode it
  stays as one quiet row with the way back.
- The chips under the field open the bar editor on each bar of the line, to type its chord.
- **Shift+Enter** (or **Split at the cursor**) breaks a line where the cursor is; **Join with the next
  line** makes two lines of one part one line. Each is placed in the line's own time.
- Placing all the words again, from the app or with `woodshed lyrics`, keeps each fix whose line still
  reads the same, and says which ones it left out.
- Undo never takes back a fix another device made since: it says so and leaves it.
- The library app and `woodshed lyrics` can work on the same library at the same time: a fix saved
  from a phone while the command line places the words again is kept.

A line is fixed through the library (woodshed app), on any device of the band; a page opened from
disk cannot place it. Without the voice heard before (the cache was cleared), the words are spread
over the line's time and marked to listen to.

What the words need:

- Latin letters only (most accented letters are fine).
- Numbers written out as words ("twenty", not "20").
- The song built with its instrument tracks, since the words are placed on the singer's own track.

The model that places the words is free for non-commercial use only: if your band is paid to play,
tap along or type the words instead (no model), and read [the licences](how-it-works.md#models-and-licences).

### Tap along

**Lay them by tapping along** reads the pasted words as the model would (parts, `x2`, rows of chords
dropped, words in brackets as backing vocals), closes the dialog and plays the song. A panel shows the
line to come: tap **Space**, your pedal (it sends Space, Right arrow or Page Down) or the big **Tap**
button on a phone or tablet the moment the line starts. **Escape** (or **Done**) stops: the lines
tapped so far are laid, the others are not.

- Each tap snaps to the nearest quarter beat.
- A line's words take one beat per syllable from the tap (half beats, or quarter beats, when the line
  is crowded before the next tap); `_` holds a word one more syllable, as when you type a line.
- One **Undo** takes the whole layout back. Laying the words again replaces only the lines the last
  layout laid: a line you typed by hand stays, and a new line that would be sung over it is left out.
- Then move the words that fall wrong, as below. In a swing feel, "half a beat" is the straight half:
  a swung "and" sits a little later, so a word on it may need a nudge by ear.

### Type a line yourself

No model needed, any language, free for any use: type the line as you would write it under the bars.
In **Edit chords and words** (or **Edit the chart** on a song with no words yet), press **+ Type a
line here** under bars with no words, or in the bar editor of the bar the line starts on, and type:

```text
When you walk, | I stum- ble _ on
```

- The words before the first `|` start on beat one of that bar. Each `|` is a bar line: the word
  after it falls on the next bar's beat one; `| |` is a bar with no new word.
- The words of a bar share its beats by syllables: three short words on four beats land on beats 1,
  2 and 3. Two syllables a beat and the words go on the "ands", up to four a beat.
- `-` joins two syllables of one word (`stum- ble` shows "stum-ble", a chord can sit on "ble"), `_`
  holds the syllable before it one syllable longer (at the start of a line, the words come in
  later), and words in round brackets, `(ooh)`, are backing vocals.
- The editor reads the line back before you save it ("Bar 5: “When” on 1, “you” on 2…"). **Enter**
  saves, **Ctrl+Enter** (**⌘+Enter**) saves and opens a new line on the next bar.
- Even notes in a swing feel land on the beat and its "and": the sheet is for reading, not a
  transcription.

A typed line is drawn, lit, followed on stage and exported to ChordPro like a placed one; in Edit
mode its time says **typed**. Typed over a line the model placed, it hides that line while it is
there (Edit mode shows it as one quiet row, "covered by a typed line"); **Take this line off** in
its editor brings the placed line back. Two typed lines never overlap: the editor says so before
saving. **Words back to the placement…** never takes back a typed line. Typed lines stay with the
recording they were typed on, also when the words are placed again with the model.

#### Move a word

Click (or tap) the word: in the line's editor, **◀** and **▶** move it half a beat, or tap where it
goes on the ruler of its bars. Words it overtakes move along; it never goes into the next line. With
the keyboard, press **M** on a line in Edit mode: the editor opens on the word to move (**Enter**
still opens it on the words). A moved word of a placed line makes it a line fixed by hand, its other
words staying where they were. Each move has **Undo**.

Typing and moving need the library (woodshed app), on any device of the band, as fixing a line does.

## Your voice type and your key

<img src="../images/desk-voice.png" alt="Voice: the song's range against your voice type" width="100%">

Pick **Voice**: the page opens on the words, with the next part named. The panel shows the range of
the melody against your voice type, and the key that suits you. Pick your voice type and
**Transpose to** the key it suggests. Change the key and everything follows: the chart, the guitar
shapes, the bass tab, the keyboard.

When the song changes key (a last chorus lifted a semitone), the voice panel says "Up a semitone at
bar 82: B♭ major." before you pick a key, then what the ending asks of your voice:

- its own range, drawn as a dashed bar under the song's ("From bar 82: F3–B♭3"), with the notes
  named in its key;
- one sentence: "From bar 82 you sing F3 to B♭3: no higher than the rest of the song.", or, in the
  warning colour, "From bar 82 it goes higher: up to D4." (or lower). Under 8 sung notes the ending
  is too short to measure, and the page says so.

The key it suggests fits the whole range, the ending included. Songs added before this version get
the ending's range a few seconds after the library starts (it is measured on the song's own vocal
track, in the background); a page open meanwhile loads it again once you stop playing.

## Keep the key for the band

Then, on the song's page opened from the library, **Keep E♭ for the band** (the button names your key): every device opens the
song in it. Served by the library, the recording follows too (see below); a page opened from disk
keeps its own key, and the page says so.

## The recording in your key

Served by the library, a transposed page offers **Play the recording 2 semitones up** (on by default
for the voice, and for everyone in the band's saved key). The library renders each track in that
key, one at a time, about 10 s per minute of song, the track you play first: the original plays
meanwhile and the page swaps to the new one at the same place, without stopping. While it renders,
the page says the recording catches up in a few seconds.

The tracks stay in tune, as long and at their level (a track already at the loudest is made a little
quieter rather than clipped); the drums alone play as recorded. A page opened from disk plays the
recording in its own key. Each page keeps the band's key, the two most recently asked others and any
key a device played in the last minute; the downloads stay the original files.

### What it needs

It works out of the box with the installers: on a Mac and on Windows they add the Rubber Band
program woodshed uses to change the key, with no extra step. On Linux and in Docker, ffmpeg has it
(`sudo apt install ffmpeg`). The library page says when it is missing and the one step that adds it
(see [the singer's key](troubleshooting.md#the-singers-key) in troubleshooting);
`woodshed app --no-pitch` turns it off.

## On stage

Tap a line's time to sing from there. Stage mode shows the words big, your line lit at the top, and
the next part coming. Stopped, the line you sing next comes first, marked **Next:** (also after
**Part ⏭**). A key change is announced before you reach it.

## ChordPro for OnSong

The ChordPro export (OnSong, SongbookPro) is in the key the page shows, the band's key included,
and reads as a sheet: a sung line is never cut by a row of chords, N.C. (no chord) is never a chord
to transpose, repeated rows are folded ("x2"), and a key change is said where it happens. More
formats in [exports](exports.md).
