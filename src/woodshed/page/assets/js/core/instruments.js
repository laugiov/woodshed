// Instrument geometry: guitar fingerings, keyboard notes, bass frets, vocal ranges.
// Pure functions of pitch classes and MIDI numbers; names come from the song's view tables.
(function () {
  "use strict";
  const W = window.Woodshed;
  const mod12 = (x) => ((x % 12) + 12) % 12;
  const SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const STRINGS = [40, 45, 50, 55, 59, 64]; // E2 A2 D3 G3 B3 E4
  const COUNTS = ["1", "e", "&", "a"];

  // A shape from the shared table (shapes.json) by its sharp name, e.g. "Am7".
  function tableShape(shapes, pc, quality) {
    const name = SHARP[mod12(pc)] + quality;
    if (shapes.open[name]) return { frets: shapes.open[name], barre: 0, open: true };
    return null;
  }

  // E-shape or A-shape barre, whichever sits lower on the neck. Sevenths keep the triad shape.
  function barreShape(pc, quality) {
    const minor = quality.startsWith("m");
    const fe = mod12(pc - 4) || 12;
    const fa = mod12(pc - 9) || 12;
    if (fe <= fa) {
      return { frets: minor ? [fe, fe + 2, fe + 2, fe, fe, fe] : [fe, fe + 2, fe + 2, fe + 1, fe, fe], barre: fe, from: 0 };
    }
    return { frets: minor ? [-1, fa, fa + 2, fa + 2, fa + 1, fa] : [-1, fa, fa + 2, fa + 2, fa + 2, fa], barre: fa, from: 1 };
  }

  function openOrBarre(shapes, pc, quality) {
    return tableShape(shapes, pc, quality) || barreShape(pc, quality);
  }

  const triadOf = (pc, quality) => [0, quality.startsWith("m") ? 3 : 4, 7].map((i) => mod12(pc + i));

  // Three-note shapes on strings G-B-E within a 3-fret span.
  function triadCandidates(pc, quality) {
    const pcs = triadOf(pc, quality);
    const open = [55, 59, 64];
    const out = [];
    for (let a = 1; a <= 13; a++)
      for (let b = 1; b <= 13; b++)
        for (let c = 1; c <= 13; c++) {
          const n = [mod12(open[0] + a), mod12(open[1] + b), mod12(open[2] + c)];
          if (pcs.every((x) => n.includes(x)) && Math.max(a, b, c) - Math.min(a, b, c) <= 3) out.push([a, b, c]);
        }
    return out;
  }

  // One small triad per chord, chosen so the hand barely moves: start near fret 6, then stay
  // close to the previous shape. chords: [{pc, quality}] in song order, already transposed.
  function funkVoicings(chords) {
    let prev = 6;
    const map = {};
    for (const ch of chords) {
      let best = null;
      let bestCost = Infinity;
      for (const t of triadCandidates(ch.pc, ch.quality)) {
        const avg = (t[0] + t[1] + t[2]) / 3;
        const cost = Math.abs(avg - prev) + 0.3 * Math.abs(avg - 6);
        if (cost < bestCost) {
          bestCost = cost;
          best = t;
        }
      }
      map[ch.pc + ch.quality] = { frets: [-1, -1, -1, best[0], best[1], best[2]], barre: 0 };
      prev = (best[0] + best[1] + best[2]) / 3;
    }
    return map;
  }

  // MIDI notes a fingering sounds, with a capo.
  function fingeredMidi(shape, capo) {
    const out = [];
    shape.frets.forEach((f, i) => {
      if (f >= 0) out.push(STRINGS[i] + (capo || 0) + f);
    });
    return out;
  }

  // Root-position triad around middle C, optionally with the root an octave below.
  function keysMidi(pc, quality, withBass) {
    const r = mod12(pc);
    const n0 = r < 7 ? 60 + r : 48 + r;
    const v = [n0, n0 + (quality.startsWith("m") ? 3 : 4), n0 + 7];
    return withBass ? [n0 - 12, ...v] : v;
  }

  // Four-string bass frets for a bar of sixteenths: the lowest comfortable string near the previous fret.
  function bassFrets(notes) {
    const strings = [["G", 43], ["D", 38], ["A", 33], ["E", 28]];
    let prev = 1;
    return notes.map((n) => {
      if (!n) return null;
      let best = -1;
      let bestCost = Infinity;
      strings.forEach(([, open], k) => {
        const f = n.midi - open;
        if (f >= 0 && f <= 12) {
          const cost = Math.abs(f - prev) + (f > 7 ? 3 : 0);
          if (cost < bestCost) {
            bestCost = cost;
            best = k;
          }
        }
      });
      if (best < 0) return null;
      prev = n.midi - strings[best][1];
      return { string: best, fret: prev, faint: n.confidence < 0.67 };
    });
  }

  // Sixteenth labels: "1 e & a 2 e & a ..." for any number of beats per bar.
  const counts = (per) => Array.from({ length: per * 4 }, (_, i) => (i % 4 === 0 ? String(i / 4 + 1) : COUNTS[i % 4]));

  const VOICES = [["Bass", 40, 64], ["Baritone", 45, 69], ["Tenor", 48, 72], ["Alto", 53, 77], ["Mezzo", 57, 81], ["Soprano", 60, 84]];

  // Semitones (-6 to 6) that best fit the song's sung range into a voice's range.
  function bestTranspose(vocal, lo, hi) {
    let best = 0;
    let bestCost = Infinity;
    for (let t = -6; t <= 6; t++) {
      const a = vocal.low + t;
      const b = vocal.high + t;
      const cost = Math.max(0, lo - a) * 3 + Math.max(0, b - hi) * 3 + Math.abs((a + b) / 2 - (lo + hi) / 2) * 0.2 + Math.abs(t) * 0.05;
      if (cost < bestCost) {
        bestCost = cost;
        best = t;
      }
    }
    return best;
  }

  // "1, 2 and 3" for the slots hit in most bars.
  // The hits worth naming: by default the strong ones of a rhythm (chords); `kept` can give the rule
  // (the drums name what the notation draws: hits in more than half the bars).
  function hitsText(shares, per, kept) {
    const c = counts(per);
    const top = Math.max(...shares);
    const keep = kept || ((p) => p > 0.6 * top && p > 0.2);
    const on = [];
    shares.forEach((p, i) => {
      if (keep(p, i)) on.push(i % 4 === 0 ? c[i] : W.t("the {count} of {beat}", { count: c[i], beat: Math.floor(i / 4) + 1 }));
    });
    return on.length > 1 ? W.t("{list} and {last}", { list: on.slice(0, -1).join(", "), last: on[on.length - 1] }) : on.join("");
  }

  // The drums' one rule, for the text, the notation, the grid and the groove heard: a slot is played
  // when it is hit in more than half the bars. A drum hit a little everywhere and never steadily
  // (the top slot under 0.6, half the slots or more at 0.2 and over) is no groove to write: none of
  // its slots is played, and with no kick nor snare played the read says so.
  function grooveHits(g) {
    const diffuse = (row) => Math.max(...row) < 0.6 && row.filter((p) => p >= 0.2).length >= row.length / 2;
    const out = {};
    for (const k of ["kick", "snare", "hat"]) out[k] = diffuse(g[k]) ? g[k].map(() => false) : g[k].map((p) => p > 0.5);
    out.clear = out.kick.some(Boolean) || out.snare.some(Boolean);
    return out;
  }

  W.instruments = {
    STRINGS, VOICES, tableShape, barreShape, openOrBarre, triadOf, triadCandidates, funkVoicings,
    fingeredMidi, keysMidi, bassFrets, counts, bestTranspose, hitsText, grooveHits,
  };
})();
