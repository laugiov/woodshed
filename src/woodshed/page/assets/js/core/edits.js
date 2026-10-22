// Chords the band types on the chart (core/chords.js reads each one). Pure functions: reading a bar
// written as on a chord sheet, and laying typed bars on the song's beats.
//
// A typed bar is kept by the global index of its first beat (as song.beats counts them) with its chords
// as [beats, label]: on beats, not bar numbers, so moving the bar lines keeps it where it was played.
(function () {
  "use strict";
  const W = window.Woodshed;
  const SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const HOLDS = new Set([".", "/"]);

  // A chord's label as stored: sharp names, read back by chords.parse whatever the key on screen.
  function label(c) {
    if (c.pc < 0) return "N.C.";
    return SHARP[c.pc] + c.quality + (c.bass === null || c.bass === undefined ? "" : "/" + SHARP[c.bass]);
  }

  // Runs of one chord: [[beats, label]], equal neighbours held.
  function runs(beats) {
    const out = [];
    for (const l of beats) {
      const last = out[out.length - 1];
      if (last && last[1] === l) last[0] += 1;
      else out.push([1, l]);
    }
    return out;
  }

  // "G . Am ." (one token a beat, "." or "/" holding), "G Am" (fewer chords than beats: even shares, the
  // first chords holding the remainder), "%" (the bar before). {chords} or {error, at}.
  function parseBar(text, per, previous) {
    const tokens = String(text).trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return { error: "empty" };
    if (tokens.includes("|")) return { error: "bar-line" };
    if (tokens.length === 1 && tokens[0] === "%") {
      return previous ? { chords: previous.map(([b, l]) => [b, l]) } : { error: "nothing-before" };
    }
    const read = [];
    for (let i = 0; i < tokens.length; i++) {
      if (HOLDS.has(tokens[i])) {
        read.push(null);
        continue;
      }
      const c = W.chords.parse(tokens[i]);
      if (c.refused) return { error: c.refused, at: i };
      read.push(label(c));
    }
    let beats;
    if (read.includes(null)) {
      if (read.length !== per) return { error: "beats" };
      const before = previous && previous.length ? previous[previous.length - 1][1] : null;
      beats = [];
      for (const l of read) {
        const held = l === null ? (beats.length ? beats[beats.length - 1] : before) : l;
        if (held === null) return { error: "nothing-before" };
        beats.push(held);
      }
    } else {
      if (read.length > per) return { error: "too-many" };
      const share = Math.floor(per / read.length);
      const extra = per % read.length;
      beats = read.flatMap((l, k) => Array(share + (k < extra ? 1 : 0)).fill(l));
    }
    return { chords: runs(beats) };
  }

  // The bars with the typed spans laid on their beats (bars as the page holds them after the doubt
  // picks; firstBeat: the first bar's beat one in song.beats). A typed chord carries `typed`; a bar
  // touched by one carries `edited`; a doubt any of whose beats is typed over is settled.
  function apply(bars, edits, firstBeat, per) {
    const beat = []; // per beat of the song: {from: the bar's chord} or {typed: chord}
    bars.forEach((bar) => bar.chords.forEach((c) => {
      for (let k = 0; k < c.beats; k++) beat.push({ from: c });
    }));
    const settled = new Set();
    for (const [at, entry] of Object.entries((edits && edits.bars) || {})) {
      let b = Number(at) - firstBeat;
      for (const [n, l] of entry.chords || []) {
        const c = W.chords.parse(l);
        if (c.refused) {
          b += n;
          continue; // written by another version: left out, the analysis's chord stays
        }
        for (let k = 0; k < n; k++, b++) {
          if (b < 0 || b >= beat.length) continue;
          if (beat[b].from) settled.add(beat[b].from);
          beat[b] = { typed: { pc: c.pc, quality: c.quality, ...(c.bass === null ? {} : { bass: c.bass }) } };
        }
      }
    }
    return bars.map((bar, u) => {
      const chords = [];
      let edited = false;
      for (let k = 0; k < per; k++) {
        const here = beat[u * per + k];
        const last = chords[chords.length - 1];
        if (here.typed) {
          edited = true;
          if (last && last.typed && W.chords.key(last) === W.chords.key(here.typed)) last.beats += 1;
          else chords.push({ ...here.typed, beats: 1, doubt: null, typed: true });
        } else if (last && last.of === here.from) last.beats += 1;
        else {
          const { of, ...rest } = { ...here.from, of: here.from };
          chords.push({ ...rest, beats: 1, doubt: settled.has(here.from) ? null : here.from.doubt, of });
        }
      }
      chords.forEach((c) => delete c.of);
      return { ...bar, chords, edited };
    });
  }

  W.edits = { parseBar, apply, label };
})();
