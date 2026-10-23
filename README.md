<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.png">
    <img src="docs/images/logo-light.png" alt="woodshed" width="440">
  </picture>
</p>

<p align="center"><strong>Turn any recording into a practice room for your whole band.</strong><br>
Chords, lyrics and a part for every instrument, on your own computer.</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-0c7a68"></a>
  <img alt="Python 3.10 to 3.14" src="https://img.shields.io/badge/python-3.10%20%E2%80%93%203.14-0c7a68">
  <a href="https://github.com/laugiov/woodshed/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/laugiov/woodshed/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Runs offline" src="https://img.shields.io/badge/runs-offline-3cc4a9">
  <img alt="No account" src="https://img.shields.io/badge/account-none-3cc4a9">
  <img alt="Status: alpha" src="https://img.shields.io/badge/status-alpha-f0a546">
</p>

<p align="center">
  <img src="docs/images/tour.gif" alt="A tour of woodshed: lyrics with chords, the chart, checking a chord by ear, bass, drums and keys parts, stage mode, phones, band mode, the library, exports" width="100%">
</p>

```bash
woodshed song.mp3
```

That's it. Within seconds your browser opens a practice page for the song, and a few minutes later
everything is there: the chord chart, the words with the chords above them, a part for guitar,
bass, keys, drums and voice, loops, a tempo trainer and play-along tracks with your instrument
taken out.

Nothing is uploaded. There is no account, no subscription, no ad. The models run on your computer,
and the page is a folder you can open offline, put on a USB stick or send to your drummer.

> *Woodshedding*: musicians' slang for practising alone, hard, until you've got it.

---

## Why woodshed

You have a recording and a rehearsal on Thursday. Chord sites give you a guess with the wrong
voicings, no bar lines and nothing for the bassist or the drummer. Transcribing by ear takes an
evening per song.

woodshed listens to the recording itself. It splits it into instrument tracks, finds the beats,
the bars, the chords and the sections, writes out the bass line and the drum groove, and places the
lyrics on the singer's voice. Then it gives every musician in the band their own way into the song.

---

## What you get

### Chords where they're sung

<img src="docs/images/lyrics.png" alt="The Lyrics view: chords above the words, bar lines numbered, the line being sung lit" width="100%">

Press **+ Add the words** on the song page, paste them, and woodshed places them on the singer's
voice, line by line (a progress bar shows how far it is), then puts each chord above the word it
lands on. Bar lines are numbered, pushes are marked, and the line being sung
lights up as the song plays. Click a word to jump there. Instrumental bars stay a grid, so a solo
never hides inside a lyric line.

### A part for every instrument

| Guitar | Bass | Drums |
|:---:|:---:|:---:|
| <img src="docs/images/desk-guitar.png" alt="Guitar: chord shapes, open, barre or funk triads, and the strumming rhythm" width="100%"> | <img src="docs/images/desk-bass.png" alt="Bass: the line as played, in tab" width="100%"> | <img src="docs/images/desk-drums.png" alt="Drums: the main groove in notation, with a hit grid" width="100%"> |
| Shapes in open, barre or funk-triad positions, barre chords tagged, the best capo for the song, and when the chords hit in the bar. | The line as played, in tab, bar by bar. Hear any bar on its own. | The main groove in notation, from the isolated drum track, and how often each hit happens. |

| Keys | Voice |
|:---:|:---:|
| <img src="docs/images/desk-keys.png" alt="Keys: the chord on a keyboard and the notes heard on the record, checked against the chart" width="100%"> | <img src="docs/images/desk-voice.png" alt="Voice: the song's range against your voice type" width="100%"> |
| The chord on a keyboard, the next one outlined, and the notes heard on the record in this bar, checked against the chart: a third that disagrees with it is said, and when the keys are often read as one note, it says to play the chart's chord there. | The range of the melody against your voice type, and the key that suits you. |

Change the key and everything follows: the chart, the shapes, the tab, the keyboard.

**Your part.** Each panel opens on **Listen to**: **Full mix**, **Your part alone** (your instrument's
separated track) or **Without your part** (the song to play over), switched while the music plays, the loop and
the tempo kept. Two links take the files home, lossless as the page plays them (about 10 MB per minute of song):
served by `woodshed app` they download as `<song> - bass alone.flac` and `<song> - without bass.flac`; a page
opened from disk opens them, and says they are already in its `audio` folder. The guitar and the keys each
have their own track; an instrument the song does not have says so, and the full mix plays. The tracks carry
the page's common gain, not the original file's level.

**Guitar and keys apart.** New songs are split into six instruments: drums, bass, vocals, guitar and keys
(the piano, plus synths and organ, which land on no other track). A page holds 11 tracks instead of 9, about
20 % more disk. To keep guitars and keys on one track, as pages made before 0.4.0 do, uncheck **Guitar and
keys apart** under **Options for the next songs** (from the command line: `--separation four`). A page keeps
the separation it was made with. The separated stems of a song take about 50 % more room in the cache;
`woodshed cache --clear` frees it, the old four-instrument stems included.

**For singers.** Paste the words (**+ Add the words**) and pick **Voice**: the page opens on the
words, with the next part named. Pick your voice type and **Transpose to** the key it suggests,
then, in the library, **Keep E♭ for the band** (the button names your key): every device opens the
song in it. Tap a line's time to sing from there; stage mode shows the words big, your line lit at the
top, and the next part coming. Stopped, the line you sing next comes first, marked **Next:**. The
ChordPro export is in the key the page shows, the band's key included, and reads as a sheet: a line is
never cut by a chord row, N.C. is never a chord to transpose, repeated rows are folded, and a key change
is said where it happens.

**The recording in your key.** Served by `woodshed app`, a transposed page offers **Play the
recording 2 semitones up** (on by default for the voice, and for everyone in the band's saved key).
The library renders each track in that key, one at a time, about 10 s per minute of song, the track
you play first: the original plays meanwhile and the page swaps to the new one at the same place,
without stopping. The tracks stay in tune, as long and at their level (a track already at the
loudest is made a little quieter rather than clipped); the drums alone play as recorded. It works
out of the box with the installers: on a Mac and on Windows they add the Rubber Band program for it;
on Linux and in Docker, ffmpeg has it (`sudo apt install ffmpeg`). The library page says when it is
missing and the one step that adds it; `woodshed app --no-pitch` turns it off. A page
opened from disk plays the recording in its own key. Each page keeps the band's key, the two
most recently asked others and any key a device played in the last minute; the downloads stay the original files.

### A method, not just a chart

Every page walks you through the same four steps: **listen** with the full band, **learn** your
part alone, **loop it slow** (from 70 % tempo, 5 BPM faster on each pass) and **play with the band**,
your own part muted. A count-in, a click and per-instrument tracks are one button away. Drag across
bars to loop them, use a pedal or the arrow keys to move bar by bar. While the song plays, the page
scrolls with it: your hands stay on the instrument. Scroll ahead by hand to read on, and **Back to
the song** brings the page back to where the band is.

The keyboard does what it says. Space plays or pauses (a page-turner pedal sends it), except on a
button you reached with Tab, which it presses as anywhere on the web; a click anywhere gives Space
back to the music. The chart's bars are one Tab stop: the arrows move bar by bar and line by line,
Home and End go to the part's first and last bar, Enter goes to a bar (or opens its check by ear).
In the bar editor, Enter saves and Ctrl+Enter (⌘+Enter on a Mac) saves and opens the next bar.

### English or French, dark or light

<img src="docs/images/french-light.png" alt="The song page in French, in the light theme" width="100%">

The page speaks English or French (your browser's language at first), dark by default or light for
a sunny room: two buttons at the top, remembered, and switched without stopping the music. Chord
names, titles and words are never translated.

### Trust the chart, or fix it

<img src="docs/images/check-by-ear.png" alt="A chord to check by ear: three candidates with their share, each playable over the recording" width="100%">

Where the analysis hesitates, woodshed says so instead of guessing quietly. The spots to check are
marked on the chart: press one, hear each candidate chord played over that bar of the recording,
and keep the one your ear agrees with. Your corrections go into the exports, and through the
library every device of the band sees them.

<img src="docs/images/edit-chart.png" alt="Editing the chart: a bar typed as on a chord sheet, read back in words, with the chords heard by the analysis one tap away" width="100%">

**Edit the chart** when the chart is wrong, or right in a vocabulary the analysis does not have.
Click a bar and type its chords as on a chord sheet: `G . Am .` (a dot holds the chord), `D/F#`,
`Asus4`, `Cmaj7`, `Bdim`, `%` for the bar before. woodshed reads it back in words ("D/F♯ for 2
beats, F♯ in the bass, then G for 2"), lets you hear each chord and the bar of the record, and
offers to type it on every repeat of that line. Rename the parts as your band calls them, join two,
or start one on any bar. Bar lines one beat off? **Bar lines…** asks where beat one is and the
library analyses the song again from its tracks with the bars there, your typed chords staying on
their beats (from disk: `woodshed "song.mp3" --bar-phase 1`). Shapes, keys, the stage view and
every export follow, and each typed bar or part can go back to the analysis, or the whole chart at
once (with an undo). Through the library the band's phones get it live.

<img src="docs/images/key-change.png" alt="A key change on the chart: the last chorus lifted to D-flat, marked before its first bar, its numerals I V vi IV again" width="100%">

**Key changes.** A last chorus lifted a semitone, a bridge in another key: woodshed finds where the key
changes and marks the bar ("→ D♭ major", with a double bar line). From there the numerals read in the new
key (I V vi IV again, not bII), the chords are spelled in it (G♭, not F♯), and a chord it hesitates on is
weighted toward it. The header says "C major → D♭ major". On stage, a change inside a part is announced two bars
ahead ("Key change in 2 bars: D♭ major", then "next bar"), and one where a part starts rides on the part line
("Part B next bar · in D♭ major"); the top line always says the bar's key. While a bar in another key plays, each
panel's title says "now in D♭ major"; the guitar's shapes come by key ("From bar 17: D♭ major"), with a word for
the hands on a lift; the voice panel says "Up a semitone at bar 17" before you pick a key; the chart's key note
lists where the key moves; where the chords around the change are unsure, the mark says "check by ear". The words
show the change above their line, the library and the set list say the key a song ends in, and the ChordPro
and MusicXML exports change key where the song does. A change counts when the new key holds at least
8 bars and its own tonic takes over: a bridge on the relative minor, a rock vamp on bVII or a few borrowed
chords stay in the song's key.

### Built for the rehearsal room

<img src="docs/images/band.png" alt="Band mode: one computer leads, a phone follows the same bar" width="100%">

- **Stage mode**: the chord now and next in huge type, the words, where you are in the section.
  Readable from the drum stool, with big buttons for a tablet: previous part, play, next part.
- **Lead and follow**: one device leads, every phone on the network follows to the bar. Start,
  stop, loop and seek once, for the whole band. In the library, **Let the band's phones join**
  shows the address to open and a code to scan with the phone's camera.
- **Set list**: line up the evening's songs, with each one's key, tempo and length, the set's total
  time and a note per song ("capo 2, starts on the chorus"; it belongs to the set and goes when the
  song leaves it), and print it. At the end of a song, the pedal (or `N`) takes the whole band to the
  next one.
- **The singer's key**: pick the key that suits the voice, then **Keep it for the band** (the button names the key): every
  device opens the song in that key. Served by `woodshed app`, the recording follows too (rendered by the
  library, see "For singers"); opened from disk it keeps its own key, and the page says so.

<p align="center">
  <img src="docs/images/phones.png" alt="The page on a phone, and stage mode on a phone" width="100%">
</p>

### Your library, your exports

<img src="docs/images/library.png" alt="The library: each song with its key, tempo, length and what its page has, and tonight's set list beside the songs" width="100%">

`woodshed app` opens your library in the browser. Drop audio or video files anywhere on it and each
one becomes a practice page: first with the full mix after a few seconds, then with every
instrument's track. Each song shows its key (the band's key when you chose one), tempo, length and
what its page has; tonight's set list sits beside your songs, and above them on a phone. Export any song to **ChordPro** with its words and parts (OnSong, SongbookPro), **MIDI**,
**MusicXML** (MuseScore), a
chord timeline (`.lab`) or **JSON**, or print a compact chart for the music stand: about two A4 pages
for a song with its words, each part kept on one page when it fits, the song's guitar shapes on top when Guitar
is picked.

**Share a song**: zip its `.woodshed` folder and send it. Unzipped, `index.html` opens in any
browser, offline, with every track, the words and the parts. **After an update** of woodshed, the
library gives every page the new interface when it starts, without analysing anything again. A page made
before 0.4.0 reads in one key; to have its key changes found, add the song again (a minute or two, from its
separated tracks; the band's typed bars stay).

---

## Install

> **Alpha.** woodshed works on real songs today, but expect rough edges.

No GPU needed, and no Python to install first. On a Mac or a Windows PC, the easiest way is to
download one file and double-click it.

### Download and double-click: Mac and Windows

For a Mac with Apple silicon (M1 or newer) or a Windows PC. Intel Macs: use
[Docker](#with-docker-windows-macos-or-linux) instead (one part of woodshed has no ready-made
build for them).

1. Download the installer for your computer:
   - **Mac**: [woodshed-installer-macos.zip](https://github.com/laugiov/woodshed/releases/latest/download/woodshed-installer-macos.zip).
     Double-click it to get **Install woodshed** (`Install woodshed.command`); Safari may unzip it
     for you, in your Downloads folder.
   - **Windows**: [woodshed-installer-windows.cmd](https://github.com/laugiov/woodshed/releases/latest/download/woodshed-installer-windows.cmd).

   Both come from the [latest release](https://github.com/laugiov/woodshed/releases/latest); what
   changed in each version is in the [changelog](CHANGELOG.md).
2. Double-click it. A window says what it does, then installs woodshed for you only: about 1.5 GB
   to download, a few minutes, no administrator rights for the install itself.
3. When it says **Done**, woodshed starts and opens your library in the browser. Drop a song on
   the page and play.

**The first time only**, your computer warns you about the installer, because this free project
does not pay Apple or Microsoft to sign it:

- **Mac**: macOS says it cannot check the file. Click **Done** (or **OK**), open **System
  Settings**, then **Privacy & Security**, scroll down and click **Open Anyway** next to
  "Install woodshed", then **Open Anyway** again and enter your Mac password (or use Touch ID).
  On macOS 14 or older, you can instead right-click the file, choose **Open**, then **Open**
  again.
- **Windows**: your browser may hold the download back. In Edge, click **...** next to it, then
  **Keep**, **Show more** and **Keep anyway**; in Chrome, **Keep**. When you double-click it, an
  "Open File - Security Warning" box asks: click **Run**. If a blue "Windows protected your PC"
  box appears, click **More info**, then **Run anyway**. If nothing works, right-click the file,
  choose **Properties**, tick **Unblock**, click **OK** and double-click it again.

**Next time**, start woodshed like any other app: **woodshed** in Applications, Launchpad or
Spotlight on a Mac, in the Start menu on Windows. A small window opens next to your browser: keep
it open while you play, close it to stop woodshed (on a Mac, Terminal asks whether to terminate
the running processes: click **Terminate**). Started again while it runs, it just shows the
library. Your songs are in the `woodshed` folder of your home folder.

MP3, WAV, FLAC and Ogg files work as they are. AAC (M4A) and video files need
[ffmpeg](https://ffmpeg.org/download.html): the Windows installer adds it when it can, and on a Mac
`brew install ffmpeg` does it (with [Homebrew](https://brew.sh)). Without Homebrew, turn an M4A into
an MP3 in the Music app: **Music** > **Settings** > **Files** > **Import Settings**, choose **MP3
Encoder**, then select the song and **File** > **Convert** > **Create MP3 Version**.

**To update**, close woodshed first (its window), download the installer again from the
[latest release](https://github.com/laugiov/woodshed/releases/latest) and run it. **To uninstall**,
close woodshed, then open **Uninstall woodshed** (in Applications on a Mac, in the Start menu or
**Settings** > **Apps** on Windows, in the applications menu on Linux). A window lists what goes
and asks once: the downloaded models and separated tracks, Rubber Band (for the recording in your
key) and its licence, the shortcuts, then woodshed itself and its big downloads in uv's cache.
Your songs and their practice pages stay where they are, and so do uv and ffmpeg, which other
programs may use.

### With Docker: Windows, macOS or Linux

Nothing to install but [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker
on Linux). On Linux or macOS, one command downloads `compose.yaml` into `~/woodshed-docker`, starts
woodshed, waits until it answers and opens your browser:

```bash
curl -LsSf https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install-docker.sh | sh
```

Or by hand (also on Windows): in a new folder, save [`compose.yaml`](compose.yaml), then:

```bash
mkdir woodshed            # your songs and their practice pages go here
docker compose up -d --wait
```

Open **http://localhost:8000**, drop a song on the page, and play. The first start pulls the image
(about 2 GB). The first analysis downloads the models (about 210 MB, and 1.2 GB more for the lyrics)
into a Docker volume, once; a song then takes about twice its length to analyse, on a CPU. The
container needs no sound card: your browser plays the music.

Stop it with `docker compose down` (your songs and the models stay). `docker compose down --volumes`
also removes the models.

On Linux, if your user id is not 1000 (`id -u`), start with
`WOODSHED_UID=$(id -u) WOODSHED_GID=$(id -g) docker compose up -d` (the install script does this for
you).

Without Compose: `docker run -d -p 127.0.0.1:8000:8000 --user "$(id -u):$(id -g)" -v "$PWD/woodshed:/library" -v woodshed-cache:/cache ghcr.io/laugiov/woodshed`
(in PowerShell, `${PWD}` instead of `$PWD`, and no `--user`).

### In a terminal: Linux, macOS or Windows

On Linux or macOS:

```bash
curl -LsSf https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.sh | sh
```

The script installs [uv](https://docs.astral.sh/uv/) if needed, then woodshed with its own Python
and the CPU build of PyTorch, in your home folder: no sudo, nothing system-wide (uv adds its
folder to your PATH). It adds woodshed to the applications menu on Linux, and the woodshed app to
`~/Applications` on macOS (Apple silicon only: Intel Macs use Docker). It tells you how to add [ffmpeg](https://ffmpeg.org/download.html) if it
is missing (only for AAC (M4A) and video files: MP3, WAV, FLAC and Ogg work without it; on Linux it also
brings the recording in your key). On macOS it adds the Rubber Band program for the recording in your key.

On Windows, in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.ps1 | iex"
```

The same for your user, no administrator rights; ffmpeg comes with winget when it is available,
the Rubber Band program for the recording in your key, and woodshed gets a Start menu shortcut. The double-click installers run these same scripts.

To uninstall: open **Uninstall woodshed** (Applications on a Mac, the Start menu or Settings >
Apps on Windows, the menu on Linux). In a terminal, `woodshed uninstall` removes the same things
(asking first), then prints the last command to type, `uv tool uninstall woodshed`. Read the
scripts before running them if you like:
[install.sh](scripts/install.sh), [install.ps1](scripts/install.ps1), and the double-click
installers from the [latest release](https://github.com/laugiov/woodshed/releases/latest)
(their source is in `scripts/installers/`).

### By hand

With Python 3.10 or newer and [pipx](https://pipx.pypa.io/) (and ffmpeg for AAC (M4A) and video files):

```bash
pipx install "woodshed[stems] @ git+https://github.com/laugiov/woodshed" \
  --pip-args="--extra-index-url https://download.pytorch.org/whl/cpu"
```

The `stems` extra brings PyTorch and the models that split the instruments and find the beats (the
extra index gets the CPU build of PyTorch, about 1.4 GB, instead of the 5 GB GPU build). Without
it, woodshed still reads the chords from the full mix, but there are no instrument tracks or parts.

On a recent laptop a song takes about twice its length to analyse. The page opens with the full mix
after a few seconds, and the instrument tracks follow.

## Use it

**Try it on the demo song** that comes with the repository, "As I Am" by Josh Woodward (CC BY 4.0):

```bash
git clone https://github.com/laugiov/woodshed && cd woodshed
woodshed "demo/As I Am.mp3"                                # the page opens in your browser
woodshed lyrics "demo/As I Am.woodshed" "demo/As I Am.txt"  # and the words on the chart
```

With Docker, drop `demo/As I Am.mp3` on the library page (http://localhost:8000).

Then on your own songs:

```bash
woodshed song.mp3                           # one song: builds the page and opens it
woodshed ~/Music/setlist/                   # a whole folder: a songbook
woodshed app                                # your library in the browser (songs in ~/woodshed)
woodshed lyrics "Song.woodshed" words.txt   # put the words on a page
woodshed chart song.mp3                     # the chord chart, as text, in the terminal
```

**The whole band, on the local network.** In the library, press **Let the band's phones join**.
It shows this computer's address and a code to scan: on each phone, on the same Wi-Fi, scan it with
the camera (or type the address), open the song and press **Follow**. The first time, your computer
may ask whether woodshed (or Python) may accept incoming connections: allow it on private networks
(on Windows, the "Windows Security" box: tick **Private networks** and click **Allow access**). The phones
can play, lead and follow, not add songs, and the button lets them out again. From a terminal,
`woodshed app --host 0.0.0.0 --allow-network` starts the library already open to the network.

With Docker, publish the port to the network instead: in `compose.yaml`, `"8000:8000"` in place of
`"127.0.0.1:8000:8000"`.

**Phones on the music stand.** While a phone follows, leads or shows the stage view, woodshed keeps
its screen on: with the browser's Screen Wake Lock on a secure page, otherwise with a tiny silent
video playing in the page (it starts at the first touch after a song change). It is best effort:
the phone's system decides, Low Power Mode or Battery Saver can refuse it, and the video costs
battery, so plug the phones in for a long rehearsal. A follower whose screen may still lock sees one
line saying where to turn its sleep off (Settings → Display & Brightness → Auto-Lock → Never on an
iPhone, where Low Power Mode greys "Never" out; Screen timeout on Android), until a touch keeps the
screen on or you close it.

**HTTPS for the phones (optional).** Over the Wi-Fi's plain `http://` address, phones have no Screen
Wake Lock. Served over HTTPS they do. With [mkcert](https://github.com/FiloSottile/mkcert) on the
computer: `mkcert -install`, then `mkcert 192.168.1.20 localhost 127.0.0.1` with this computer's
address on the band's network (a name such as `mylaptop.local` works too, though Android often cannot
resolve `.local` names: the address is the safe choice), and start
`woodshed app --cert 192.168.1.20+2.pem --key 192.168.1.20+2-key.pem` (or set `WOODSHED_CERT` and
`WOODSHED_KEY`). Keep both files outside the library folder: woodshed refuses a key it would serve.
The library page then shows `https://` addresses and code. Each phone must trust mkcert's root,
`rootCA.pem` from `mkcert -CAROOT` (share that file only, never `rootCA-key.pem`):

- iPhone: send it by AirDrop or mail, install the profile in Settings (General → VPN & Device
  Management on recent iOS), then General → About → Certificate Trust Settings: turn on full trust.
- Android: Settings → Security → Encryption & credentials → Install a certificate → CA certificate
  (the menu names vary; a screen lock is required, and the file may need a `.crt` name). Chrome
  trusts it; Firefox for Android does not by default. A "network may be monitored" notice appears.

Remove the root from the phones after the gig: anything that trusts it trusts every certificate
your mkcert makes. The address in the certificate must be the one the phones type: give the
computer a fixed address on the router, or make a new certificate after joining another network.
mkcert's certificates last a little over two years. An old `http://` bookmark no longer answers. The
computer itself still opens `http://127.0.0.1:8000`, except when the whole library listens on the
network (`--host 0.0.0.0`, or Docker): then it is `https://localhost:8000` too, and the certificate must
include `localhost` and `127.0.0.1`. With Docker: put the two files in a `certs` folder next to
`compose.yaml` (not inside `woodshed`), and follow the comment in `compose.yaml`.

**No Wi-Fi in the room.** Turn on a phone's hotspot, join it from the computer and the other phones,
and let the band's phones join again: the library page shows the address on that network (not last
time's).

**iPad and tablets.** A tablet opens the library like a phone: on the same Wi-Fi as the computer running
`woodshed app`, scan the code or type the address the library page shows (**Let the band's phones join**),
in Safari. Your part, the stage view and following the leader are meant to work there as on a phone; over
the Wi-Fi's plain `http://` the screen may lock, as on a phone (turn Auto-Lock off, or use HTTPS above).
There is no practice on the iPad alone: the computer has to be on, on the same network. iOS starts a sound
only from a tap: a tap on the page lets every track play later, and if a switch is still refused, the music
goes on and the page asks for another tap. This is checked in WebKit, Safari's engine, not yet on a real
iPad. iPad users report that Safari opens an HTML file from the Files app without the files next to it, so
a page folder copied to an iPad is not expected to play.

**The words.** In the library, a song with its parts offers **add the words**; on its page, **Add the
words** next to the chart. Paste them (part names like `[Chorus]` help), press **Place the words**:
a minute later the page shows the chords above the words. From the command line, or for a page
opened from disk: `woodshed lyrics "Song.woodshed" words.txt`.

Useful options: `--bpm 65` settles a half-time or double-time doubt, `--beats-per-bar 3` for a
waltz, `--sevenths` adds 7th chords, `--bar-phase 1` puts the first bar line one beat later (a pickup),
`--separation four` keeps guitars and keys on one track, `--offline` never downloads models. `woodshed --help` lists
them all.

---

## How it works

```mermaid
flowchart LR
    A[Recording] --> B[Demucs<br/>instrument tracks]
    A --> C[beat_this<br/>beats and bars]
    A --> D[Chord engine<br/>full mix]
    C --> D
    D --> E[Sections<br/>verse, chorus, bridge]
    B --> F[Parts<br/>bass tab, drum groove,<br/>keys voicings, vocal range]
    W[Pasted words] --> G[MMS<br/>words on the voice]
    B --> G
    E --> P[Practice page<br/>one offline folder]
    F --> P
    G --> P
```

- **Separation**: [Demucs](https://github.com/facebookresearch/demucs) (htdemucs_6s) splits the mix
  into vocals, drums, bass, guitar, piano and the rest, losslessly cached.
- **Beats and bars**: [beat_this](https://github.com/CPJKU/beat_this) finds beats and downbeats.
- **Chords**: woodshed's own engine (signal processing, no trained model) reads the harmony from the
  full mix, bar by bar, and says where it is unsure rather than guessing.
- **Structure**: lines that come back are grouped into sections and named by their role.
- **Lyrics**: Meta's [MMS](https://pytorch.org/audio/stable/pipelines.html#torchaudio.pipelines.MMS_FA)
  aligns the words you paste on the vocal track.
- **The page** is plain HTML, CSS and JavaScript in one folder. It loads nothing from the internet:
  the repository's CI rejects any page code that points outside. Opened from disk, it makes no
  request at all; the band features talk only to your own library server.

No language model and no cloud service: everything above runs on your computer. The full tour, module
by module: **[Under the hood](docs/architecture.md)**.

## Privacy

Everything runs on your computer: the analysis, the models, the library server (which listens on
this computer only until you let the band's phones in). Your recordings, your corrections and your
lyrics never leave it. The band's corrections, keys and notes are kept by your own library, in its
folder; a page opened from disk keeps its corrections in that browser.

## Models and licences

woodshed is MIT. The models it downloads come with their own licences:

| Model | Used for | Licence |
|---|---|---|
| Demucs (htdemucs_6s, htdemucs) | Instrument tracks | MIT |
| beat_this | Beats and downbeats | MIT |
| MMS forced aligner (weights, 1.2 GB) | Placing lyrics (optional) | **CC BY-NC 4.0**: non-commercial use |

**If your band is paid to play, leave the words feature aside** unless you are sure your use is
non-commercial: it is the only part that needs the MMS weights, and
[their licence](https://creativecommons.org/licenses/by-nc/4.0/) allows non-commercial use only
(this is not legal advice). Everything else in woodshed is under permissive licences (MIT, and SIL
OFL for the fonts) and free for any use, paid gigs included.

The page ships VexFlow (MIT) for notation, the FluidR3 GM SoundFont (MIT) for instrument sounds,
and Atkinson Hyperlegible, Barlow Condensed, JetBrains Mono, Noto Music and Bravura fonts (SIL OFL).
The recording in another key is rendered by [Rubber Band](https://breakfastquay.com/rubberband/)
(GPL-2.0-or-later, Particular Programs Ltd), always as a separate program, never linked: your ffmpeg's
Rubber Band filter, or the Rubber Band program. On a Mac and on Windows the installers download that
program, the official build from [breakfastquay.com](https://breakfastquay.com/files/releases/), checked
against a pinned checksum, into woodshed's tools folder with its licence (on Windows with libsndfile,
LGPL-2.1, which it uses to read and write sound files). woodshed's package, repository and Docker image do
not contain it.

**Your songs and lyrics are yours to handle.** woodshed works on the files you give it, on your
computer. Respect the rights on the recordings and lyrics you use, and don't publish pages of songs
you don't have the rights to.

## Status and limits

- Alpha: the core (chart, sections, lyrics, parts, band mode) works, and the page is tested in
  Chromium and Firefox on every push and pull request, and what tablets need in WebKit. Installation will get simpler.
- How accurate it is, as measured on the prototype woodshed grew from (October 2026; no larger
  benchmark yet): on "Let It Be" (the album version, its first 2:55) against the Isophonics
  reference, chords 84.5 % right (major/minor), beats and downbeats found at 0.97 (F-measure); on a
  funk cover, the drum groove's kick and snare matched 9 bars out of 10. The bass notes' octave was
  checked on the separated tracks of real recordings. These recordings and references are
  copyrighted, so they are not in the repository. The bass tab note by note is not measured yet: it is marked experimental in the
  page, as the drum groove, and both say when the read is unsure ("no clear groove", "no bass heard
  in this bar"). Check them by ear.
- Chords are triads by default; `--sevenths` adds 7 and m7 chords, less reliably.
- Key changes: found when the new key holds 8 bars or more; shorter ones (a tonicisation) are not, and the
  band cannot type one yet. One meter for the whole song.
- Lyrics: Latin letters only (most accented letters are fine); write numbers out as words ("twenty", not "20").

## Development

```bash
git clone https://github.com/laugiov/woodshed && cd woodshed
uv sync --extra stems
uv run pytest -n auto                     # Python and page tests (Playwright)
scripts/ci.sh                             # the quick local CI
```

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Security problems go
through [private reporting](SECURITY.md).

## Credits

The screenshots show woodshed's analysis of four songs by
[Josh Woodward](https://www.joshwoodward.com/), from the album *The Shade from Our Trees*:
[As I Am](https://www.joshwoodward.com/song/AsIAm),
[Same Boat](https://www.joshwoodward.com/song/SameBoat),
[Beyond the Sky](https://www.joshwoodward.com/song/BeyondTheSky) and
[The Rival Within](https://www.joshwoodward.com/song/TheRivalWithin), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The images show woodshed's chords, parts
and excerpts of the lyrics placed on the recordings. The [`demo/`](demo/) folder ships "As I Am",
recording and lyrics, unchanged ([details](demo/LICENSE.md)). Thank you, Josh, for making your music
free to use.

## License

[MIT](LICENSE) © Laurent Giovannoni
