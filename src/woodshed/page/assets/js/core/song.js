// The song and its view tables, read once from the page, with the lookups every view needs.
// Names and numerals come from the view tables computed in Python; a chord the band typed (core/chords.js)
// adds its quality's mark and its slash bass to them.
(function () {
  "use strict";
  const W = window.Woodshed;
  const SONG_VERSION = 2;
  const VIEW_VERSION = 1;

  function read() {
    const el = document.getElementById("woodshed-data");
    if (!el) throw new Error(W.t("This page has no song data."));
    const data = JSON.parse(el.textContent);
    if (data.song.schema_version !== SONG_VERSION || data.view.view_version !== VIEW_VERSION) {
      throw new Error(W.t("This page was made by another version of woodshed. Rebuild it with this one."));
    }
    return data;
  }

  function make(data) {
    const song = data.song;
    const view = data.view;
    const per = song.beats_per_bar;
    const bars = song.bars;
    const beats = song.beats;
    const totalBeats = bars.length * per;

    // Time of beat b, counted from beat one of the first bar. Outside the tracked beats, the
    // nearest beat period carries on (pickup before the first beat, last bar after the last).
    function beatTime(b) {
      const i = song.first_beat + b;
      if (beats.length === 0) return 0;
      if (i >= 0 && i < beats.length) return beats[i];
      const n = beats.length;
      if (n < 2) return beats[0];
      if (i < 0) return Math.max(0, beats[0] + i * (beats[1] - beats[0]));
      return beats[n - 1] + (i - n + 1) * (beats[n - 1] - beats[n - 2]);
    }

    // Beat index (from the first bar's beat one) playing at time t.
    function beatAt(t) {
      let lo = 0;
      let hi = totalBeats - 1;
      if (t <= beatTime(0)) return 0;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (beatTime(mid) <= t) lo = mid;
        else hi = mid - 1;
      }
      return lo;
    }

    function chordAtBeat(b) {
      const bar = bars[Math.max(0, Math.min(bars.length - 1, Math.floor(b / per)))];
      const pos = ((b % per) + per) % per;
      let acc = 0;
      for (const c of bar.chords) {
        acc += c.beats;
        if (pos < acc) return c;
      }
      return bar.chords[bar.chords.length - 1];
    }

    // The same chord only with the same bass: D and D/F# are two chords.
    const bassOf = (c) => (c.bass === undefined || c.bass === null ? null : c.bass);
    const same = (a, b) => !!a && !!b && a.pc === b.pc && a.quality === b.quality && bassOf(a) === bassOf(b);

    // The next n different chords after beat b (no-chord beats skipped).
    function upcoming(b, n) {
      const out = [];
      let cur = chordAtBeat(b);
      for (let k = b + 1; k < totalBeats && out.length < n; k++) {
        const c = chordAtBeat(k);
        if (!same(c, cur) && c.pc >= 0) out.push(c);
        cur = c;
      }
      return out;
    }

    const t = (transpose) => view.transpositions[((transpose % 12) + 12) % 12];
    // A pitch class from the recording, named in the transposed key.
    const noteName = (pc, transpose) => t(transpose).roots[((pc % 12) + 12) % 12];
    const chordName = (c, transpose) =>
      c.pc < 0 ? "N.C." : noteName(c.pc, transpose) + c.quality + (bassOf(c) === null ? "" : "/" + noteName(c.bass, transpose));
    // The analysis's four qualities have their numerals in the view; a typed one takes the root's numeral
    // with its own case and mark. A slash bass is its degree above the root ("I/3"), as in chords.py.
    function roman(c) {
      if (c.pc < 0) return "";
      let out;
      if (view.romans[c.quality]) out = view.romans[c.quality][c.pc];
      else {
        const form = W.chords.roman(c.quality);
        const numeral = view.romans[""][c.pc];
        out = (form.lower ? numeral.toLowerCase() : numeral) + form.mark;
      }
      return bassOf(c) === null ? out : out + "/" + W.chords.degree(c.bass - c.pc);
    }
    const keyName = (transpose) => t(transpose).key;
    const capoFor = (transpose) => t(transpose).capo;

    // Bars of the line holding bar u, in the same pass.
    function occurrenceRange(u) {
      const b = bars[u];
      const occ = song.groups[b.group].occurrences[b.occurrence];
      return [occ[0], occ[occ.length - 1]];
    }

    // Index, in a list of sections (the analysis's, or the band's own), of the one holding bar u.
    function sectionIndex(u, list) {
      for (let k = list.length - 1; k >= 0; k--) if (list[k].start <= u) return k;
      return 0;
    }

    function barAt(time) {
      let u = 0;
      for (let i = 0; i < bars.length; i++) if (bars[i].start <= time) u = i;
      return u;
    }

    function doubts() {
      const out = [];
      bars.forEach((bar, i) =>
        bar.chords.forEach((c, k) => {
          if (c.doubt) out.push({ bar: i, index: k, chord: c });
        }),
      );
      return out;
    }

    // Distinct chords of the song, in order of appearance, without no-chord beats and without
    // one-beat doubts (they are passing guesses, not shapes to learn).
    function distinctChords() {
      const seen = new Set();
      const out = [];
      for (const bar of bars) {
        for (const c of bar.chords) {
          if (c.pc < 0 || (c.doubt && c.beats <= 1)) continue;
          const key = c.pc + c.quality + "/" + bassOf(c);
          if (!seen.has(key)) {
            seen.add(key);
            out.push(c);
          }
        }
      }
      return out;
    }

    return {
      data, song, view, per, bars, totalBeats, beatTime, beatAt, chordAtBeat, same, upcoming,
      noteName, chordName, roman, keyName, capoFor, occurrenceRange, sectionIndex, barAt, doubts, distinctChords,
      tracks: view.tracks,
      parts: song.parts,
    };
  }

  W.song = { read, make, load: () => make(read()) };
})();
