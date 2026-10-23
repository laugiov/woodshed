# Your library and your exports

## The library

<img src="../images/library.png" alt="The library: each song with its key, tempo, length and what its page has, and tonight's set list beside the songs" width="100%">

Opening woodshed opens your library in the browser (from a terminal: `woodshed app`). Drop audio or
video files anywhere on it and each one becomes a practice page: first with the full mix after a
few seconds, then with every instrument's track. Each song shows its key (the band's key when you
chose one), tempo, length and what its page has; tonight's [set list](phones.md#the-set-list) sits
beside your songs, and above them on a phone.

The footer says which version of woodshed you have, with links to what's new and to
[how to update](install.md#updating).

## Exports

Export any song to:

- **ChordPro**, with its words and parts, for OnSong and SongbookPro (it reads as a sheet: see
  [ChordPro for OnSong](singers.md#chordpro-for-onsong));
- **MIDI**;
- **MusicXML**, for MuseScore;
- a chord timeline (`.lab`);
- **JSON**.

Your corrections go into every export. ChordPro is in the key the page shows, the band's key
included, and ChordPro and MusicXML change key where the song does.

## Print for the music stand

Print a compact chart: about two A4 pages for a song with its words, each part kept on one page
when it fits, the song's guitar shapes on top when Guitar is picked. The set list prints too, as a
sheet for the music stand: big titles, key and tempo in bold, the total time, your notes.

## Share a song

Zip its `.woodshed` folder and send it. Unzipped, `index.html` opens in any browser, offline, with
every track, the words and the parts. A page opened from disk keeps its corrections in that
browser, and plays the recording in its own key.
