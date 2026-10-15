// The words of the song, when they were placed on the voice (woodshed lyrics): each sung line as
// its bars, each bar its words and chords, in time. The chords come from the chart as it is now
// (with the user's corrections), placed on the words by the same rule as the Python side
// (lyrics.chord_changes and lyrics.place_chords): the word starting just after the change (a
// push), else the word still sung or held, else a gap of its own.
(function () {
  "use strict";
  const W = window.Woodshed;

  W.lyrics = function lyrics(song, data) {
    if (!data || data.version !== 1 || !Array.isArray(data.lines)) return null;
    const meta = song.song;
    const per = song.per;
    const bpm = meta.bpm;
    const barTime = (60 / bpm) * per;

    // A word the voice did not give a time (null) keeps its place in the line, with no chord.
    const timed = (w) => w && typeof w.start === "number" && typeof w.end === "number";
    const lines = data.lines
      .map((ln, index) => ({ ...ln, index }))
      .filter((ln) => ln.sung && Array.isArray(ln.words) && ln.words.some(timed));
    for (const ln of lines) {
      const ws = ln.words.filter(timed);
      ln.start = Math.min(...ws.map((w) => w.start));
      ln.end = Math.max(...ws.map((w) => w.end));
    }
    lines.sort((a, b) => a.start - b.start);
    if (!lines.length) return null;

    // The chord changes of the chart now, on the tracked beats only (as lyrics.chord_changes).
    function changes() {
      const out = [];
      let prev = null;
      song.bars.forEach((bar, u) => {
        let pos = 0;
        bar.chords.forEach((c, k) => {
          const name = c.pc + "/" + c.quality;
          const i = meta.first_beat + u * per + pos;
          if (name !== prev && i >= 0 && i < meta.beats.length) out.push({ t: meta.beats[i], bar: u, index: k, chord: c });
          prev = name;
          pos += c.beats;
        });
      });
      return out;
    }

    // lyrics.place_chords, step for step.
    function place(list) {
      const push = Math.min(60 / bpm / 2, 0.2);
      const hold = barTime / 2;
      const flat = [];
      lines.forEach((ln, li) => ln.words.forEach((w, wi) => timed(w) && flat.push({ start: w.start, end: w.end, li, wi })));
      flat.sort((a, b) => a.start - b.start || a.end - b.end || a.li - b.li || a.wi - b.wi);
      return list.map((ch) => {
        let k = 0;
        while (k < flat.length && flat[k].start < ch.t) k++;
        if (k < flat.length && flat[k].start - ch.t <= push) return { ...ch, li: flat[k].li, wi: flat[k].wi, push: flat[k].start > ch.t + 0.05 };
        if (k > 0 && ch.t - flat[k - 1].end < hold) return { ...ch, li: flat[k - 1].li, wi: flat[k - 1].wi, push: false };
        return { ...ch, li: null, wi: null, push: false };
      });
    }

    // Each line as bars: [{bar, cont, items}] where an item is a word (with the chords on it) or a
    // gap (a chord with no word under it). A line holds the bars from the one it starts in to its
    // end plus half a bar, never past the next line; a bar holds to one line. A line starting in
    // a bar the line before still holds goes on in it (cont: no bar line of its own). Bars no line
    // holds (owner -1) are left to the chart, which shows them as a grid.
    // Chords to check that are no change (the same chord again, or off the tracked beats): no
    // change for the placement, but the view shows them, as the header counts them.
    function checksLeft(list) {
      const seen = new Set(list.map((c) => c.bar + "_" + c.index));
      const out = [];
      song.bars.forEach((bar, u) => {
        let pos = 0;
        bar.chords.forEach((c, k) => {
          const i = meta.first_beat + u * per + pos;
          const t = i >= 0 && i < meta.beats.length ? meta.beats[i] : bar.start + pos * (60 / bpm);
          if (c.doubt && !c.fixed && !seen.has(u + "_" + k)) out.push({ t, bar: u, index: k, chord: c });
          pos += c.beats;
        });
      });
      return out;
    }

    function rows() {
      const list = changes();
      const placed = place(list.concat(checksLeft(list)));
      const starts = song.bars.map((b) => b.start);
      const owner = new Array(song.bars.length).fill(-1);
      const out = lines.map((ln, li) => {
        const next = lines[li + 1] ? lines[li + 1].start : Infinity;
        const from = song.barAt(ln.start + 0.15);
        const to = Math.max(from, song.barAt(Math.max(ln.start, Math.min(next - 0.15, ln.end + barTime / 2))));
        const bars = [];
        for (let u = from; u <= to; u++) {
          if (owner[u] < 0) {
            owner[u] = li;
            bars.push({ bar: u, cont: false, items: [] });
          } else if (u === from) bars.push({ bar: u, cont: true, items: [] });
        }
        return { line: ln, li, bars, firstBar: song.barAt(ln.start + barTime / 2) };
      });
      for (const r of out) {
        const barOf = (t) => {
          let b = r.bars[0];
          for (const x of r.bars) if (starts[x.bar] - 0.15 <= t) b = x;
          return b;
        };
        let t = r.line.start;
        r.line.words.forEach((w, wi) => {
          if (timed(w)) t = w.start;
          barOf(t).items.push({ kind: "word", t, timed: timed(w), text: w.text, chords: [], wi });
        });
        const last = r.bars[r.bars.length - 1].bar;
        r.end = last + 1 < starts.length ? starts[last + 1] : meta.duration;
      }
      for (const p of placed) {
        if (p.li !== null) {
          for (const b of out[p.li].bars) for (const it of b.items) if (it.kind === "word" && it.wi === p.wi) it.chords.push(p);
          continue;
        }
        // A chord no word takes: in the line holding its bar, if a line does.
        let into = null;
        for (const r of out) for (const b of r.bars) if (b.bar === p.bar && (!into || r.line.start - 0.15 <= p.t)) into = b;
        if (into) into.items.push({ kind: "gap", t: p.t, chords: [p] });
      }
      for (const r of out) for (const b of r.bars) b.items.sort((a, c) => a.t - c.t || (a.wi ?? -1) - (c.wi ?? -1));
      return { rows: out, owner };
    }

    // The line sung at time t: the last one started, until a bar after its end (then nothing is
    // sung: a solo); and the next line to come.
    function lineAt(t) {
      let k = -1;
      for (let i = 0; i < lines.length; i++) if (lines[i].start <= t + 0.05) k = i;
      if (k >= 0 && t > lines[k].end + barTime) k = -1;
      let next = lines.findIndex((ln) => ln.start > t + 0.05);
      if (next < 0) next = lines.length;
      return { now: k, next };
    }

    // The parts as the words name them (lyrics.sections_by_words), when they fit this chart: in
    // order, without overlap, within its bars. Otherwise the chart's own names.
    const named = data.sections;
    const fits =
      Array.isArray(named) && named.length > 0 &&
      named.every((p, k) => p && typeof p.name === "string" && typeof p.role === "string" && typeof p.letter === "string" &&
        Number.isInteger(p.start) && Number.isInteger(p.end) && p.start >= 0 && p.start < p.end && p.end <= song.bars.length &&
        (k === 0 || p.start >= named[k - 1].end));
    const sections = fits ? named.map((p) => ({ name: p.name, role: p.role, letter: p.letter, start: p.start, end: p.end })) : null;

    return { lines, rows, lineAt, place, changes, sections };
  };
})();
