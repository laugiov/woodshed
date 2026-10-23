# When something goes wrong

The messages woodshed shows, word for word as far as possible, and what to do. Look for the first
words of yours.

- [Installing](#installing)
- [Adding a song](#adding-a-song)
- [The library page](#the-library-page)
- [The singer's key](#the-singers-key)
- [The words](#the-words)
- [The phones](#the-phones)
- [Still stuck](#still-stuck)

## Installing

**The Mac says it cannot check the installer, or Windows says it protected your PC.** Expected the
first time: this free project does not pay to sign its installers. The steps for your computer are
in [the first time: your computer's warnings](install.md#the-first-time-your-computers-warnings).

**"This Mac has an Intel processor".** The installer needs a Mac with Apple silicon: use
[Docker](install.md#intel-macs) instead.

**On a Mac, closing woodshed's window, Terminal asks whether to terminate the running processes.**
Click **Terminate**: that is how woodshed stops.

**"Uninstall woodshed" says woodshed is running.** Close woodshed's window first, then open
**Uninstall woodshed** again.

## Adding a song

In the library, a song that could not be made says **Failed:** and the reason, and words that could
not be placed say **Words not placed:** and the reason. The reasons:

**"cannot read its length without ffmpeg installed"**, or **"could not read the audio, and ffmpeg is
not installed"**. An M4A (AAC) or a video file: see [M4A and video files](install.md#m4a-and-video-files),
or convert the song to MP3.

**"this kind of file is not supported"**, or **"not an audio or video file"**. The file holds no
music woodshed can read: try another copy, or another format (MP3, WAV, FLAC, Ogg).

**"lasts 42 minutes: the limit is 30"**. A song is at most 30 minutes: cut the recording into songs.

**"too few beats were detected: is this music?"**. woodshed found no steady beat: a very free
recording (no pulse, a speech) cannot get bars and chords.

**"is not downloaded yet: run once without --offline"**. The first song downloads the models (about
210 MB, and 1.2 GB more for the words): run once with the internet on.

**"instrument tracks and parts need the stems extra"**. Installed [by hand](install.md#by-hand)
without the `stems` extra: install it again with it.

**"failed last time (...); to retry, remove ... and add it again"**. The library does not retry a song
that failed at its last start: remove the folder it names, then drop the song again.

**"could not replace ...: close the page in your browser and try again"**, or **"could not
update ..."**. On Windows a page open in a browser holds its files: close that tab and try again.

**"Made by an older woodshed: analyse it again for the new page"**. In the library, on a song made by
an old version: add the song again (its separated tracks are reused when they are still in the cache).

## The library page

**"The library was restarted: reload this page."** woodshed was closed and opened again while the
page was open: reload the page (and drop the file again if you were adding one).

**"The app did not answer."**, or **"the library did not answer: is woodshed app still running?"**.
woodshed's window was closed: start woodshed again.

**"The set list was not saved"**, **"The note was not saved"**. The reason follows the message; most
often the library was restarted: reload the page and do it again.

## The singer's key

These lines show in the library or under **Play the recording ... up**. See
[what it needs](singers.md#what-it-needs).

**"This library cannot change the key: run the woodshed installer again, then restart woodshed."** On a
Mac or Windows, the Rubber Band program is missing: run the installer again (your songs stay).

**"Rubber Band is installed but this computer blocks it"**. Your security settings or antivirus stop
woodshed's Rubber Band program: allow it there, then restart woodshed.

**"its ffmpeg has no Rubber Band filter"**, **"install ffmpeg (sudo apt install ffmpeg)"**, **"install
the full ffmpeg (with Rubber Band)"**. On Linux: do what the line says (`sudo apt install ffmpeg`, or
`sudo apt install rubberband-cli`), then restart woodshed.

**"The recording keeps its key. Open the page from the woodshed library to hear it in another key."**
The page was opened from disk (a shared folder): the chart follows your key, the recording cannot.

**"Changing the recording's key is off in this library."** woodshed was started with `--no-pitch`.

**"Tap the page to hear the recording in the new key."**, **"Ready: tap the page to hear it."** On a
phone or tablet, a sound starts only from a tap: tap the page.

**"not enough free disk to render this track"**. Free some room on the disk, or clear the cache
(`woodshed cache --clear`).

**"The recording could not be changed to this key."** The rendering failed: try another key, and if
it keeps failing, [tell us](#still-stuck).

## The words

**"letters the model cannot hear: ..."**. The words hold letters outside the Latin alphabet, or
digits: write numbers out as words ("twenty", not "20"), and keep to Latin letters.

**"not enough time for the words"**. More words than the song has room for: check that the text is
this song's, without repeats that are not sung.

**"The words are placed on the singer's track, and this page has none yet"**. The song was made
without its instrument tracks: build it with them, then add the words.

**"This page is opened from the disk: save the words in a text file"**. Do as the page says, or open
the song from the library to paste them there.

**"Words are added from the computer that runs the library, like songs."** A phone cannot add the
words: add them on the computer.

## The phones

**"no network found: is this computer on the band's Wi-Fi?"**, or **"Let in, but this computer has
no network address"**. Join the Wi-Fi (or a phone's hotspot: see
[no Wi-Fi in the room](phones.md#no-wi-fi-in-the-room)), then let the phones join again.

**A phone cannot open the address.** Your computer may have asked whether woodshed (or Python) may
accept incoming connections: allow it on private networks (on Windows: tick **Private networks**,
click **Allow access**). Check that the phone is on the same Wi-Fi.

**"the phones cannot be let in on port 8000"**. Another program uses that port, or the system refused
it: close the other program, or start woodshed on another port from a terminal
(`woodshed app --port 8001`).

**A phone's screen locks.** The page shows where to turn its sleep off: see
[phones on the music stand](phones.md#phones-on-the-music-stand).

**In the terminal: "a device does not trust the certificate yet, or opened an http:// address"**.
With HTTPS on, a phone must trust the certificate's root first, and open the `https://` address:
see [HTTPS for the phones](phones.md#https-for-the-phones-optional).

**"the key is protected by a password"**, **"is inside the library"**, **"do not go together"**. The
HTTPS files: give woodshed a key without a password (mkcert makes those), keep both files outside
the library folder, and give the certificate with its own key.

## Still stuck

Open an [issue](https://github.com/laugiov/woodshed/issues) and say what you did, what you expected
and what woodshed showed, with `woodshed --version`, your system and your browser. Never attach a
recording you don't have the rights to share: [CONTRIBUTING](../../CONTRIBUTING.md#reporting-a-problem-with-a-song)
says how to describe it instead.
