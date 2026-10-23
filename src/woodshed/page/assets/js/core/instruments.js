// Instrument geometry: guitar fingerings, keyboard notes, bass frets, vocal ranges.
// Pure functions of pitch classes and MIDI numbers; names come from the song's view tables.
(function () {
  "use strict";
  const W = window.Woodshed;
  const mod12 = (x) => ((x % 12) + 12) % 12;
  const SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const STRINGS = [40, 45, 50, 55, 59, 64]; // E2 A2 D3 G3 B3 E4
  const COUNTS = ["1", "e", "&", "a"];

  // The analysis writes these four; any other quality (and any slash bass) was typed by the band
  // (core/chords.js) and draws from the typed chords' own shapes.
  const ANALYSED = { has: (q) => W.chords.analysed(q) };
  const CHORDS = W.CHORD_TABLE;
  const isNone = (bass) => bass === undefined || bass === null;

  // An open shape by its sharp name ("Am7", "D/F#"): the song's table (shapes.json), then the typed
  // chords' own. A slash chord without its own shape is played as its chord, the bass named apart.
  function tableShape(shapes, pc, quality, bass) {
    const name = SHARP[mod12(pc)] + quality;
    if (!isNone(bass)) {
      const slash = CHORDS.open[name + "/" + SHARP[mod12(bass)]];
      if (slash) return { frets: slash, barre: 0, open: true };
    }
    const frets = shapes.open[name] || (ANALYSED.has(quality) ? null : CHORDS.open[name]);
    return frets ? { frets, barre: 0, open: true } : null;
  }

  // A typed quality: the movable form (root on the E or the A string) lowest on the neck, a wide
  // stretch counted as three frets higher, up an octave when a finger would sit below the nut.
  // tests/test_chords.py checks every one plays its chord, with the same choice.
  function movableShape(pc, quality) {
    let best = null;
    for (const [string, form] of Object.entries(CHORDS.movable[quality])) {
      const at = mod12(pc - (string === "E" ? 4 : 9));
      for (const r of [at, at + 12]) {
        if (!form.every((o) => o === null || r + o >= 0)) continue;
        const frets = form.map((o) => (o === null ? -1 : r + o));
        const fretted = frets.filter((f) => f > 0);
        const low = fretted.length ? Math.min(...fretted) : 0;
        const score = low + (fretted.length && Math.max(...fretted) - low >= 4 ? 3 : 0);
        // A barre only for a form whose strings all sound from the root's string on, none below its fret,
        // two of them or more at it.
        const from = string === "E" ? 0 : 1;
        const full = form.slice(from).every((o) => o !== null && o >= 0) && form.filter((o) => o === 0).length > 1;
        if (!best || score < best.score) best = { score, frets, barre: r > 0 && full ? r : 0, from };
        break;
      }
    }
    return { frets: best.frets, barre: best.barre, from: best.from };
  }

  // E-shape or A-shape barre, whichever sits lower on the neck. Sevenths keep the triad shape.
  function barreShape(pc, quality, bass) {
    if (!ANALYSED.has(quality)) return movableShape(pc, quality);
    const minor = quality.startsWith("m");
    const fe = mod12(pc - 4) || 12;
    const fa = mod12(pc - 9) || 12;
    if (fe <= fa) {
      return { frets: minor ? [fe, fe + 2, fe + 2, fe, fe, fe] : [fe, fe + 2, fe + 2, fe + 1, fe, fe], barre: fe, from: 0 };
    }
    return { frets: minor ? [-1, fa, fa + 2, fa + 2, fa + 1, fa] : [-1, fa, fa + 2, fa + 2, fa + 2, fa], barre: fa, from: 1 };
  }

  function openOrBarre(shapes, pc, quality, bass) {
    return tableShape(shapes, pc, quality, bass) || barreShape(pc, quality, bass);
  }

  // Three notes that say the chord: root, third (or the suspended note), and a diminished or augmented
  // fifth when there is one (dim, dim7, m7b5, aug), else the seventh or sixth, else the fifth. A ninth
  // (add9) is left out: three strings cannot say everything.
  function triadOf(pc, quality) {
    if (ANALYSED.has(quality)) return [0, quality.startsWith("m") ? 3 : 4, 7].map((i) => mod12(pc + i));
    const tones = CHORDS.qualities[quality].intervals.map((i) => mod12(i));
    const third = tones.find((i) => [2, 3, 4, 5].includes(i));
    const fifth = tones.find((i) => [6, 7, 8].includes(i));
    const colour = fifth === 6 || fifth === 8 ? fifth : tones.find((i) => [9, 10, 11].includes(i));
    return [0, third === undefined ? fifth : third, colour === undefined ? fifth : colour]
      .filter((i, k, a) => i !== undefined && a.indexOf(i) === k)
      .map((i) => mod12(pc + i));
  }

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
      map[ch.pc + ch.quality + (isNone(ch.bass) ? "" : "/" + mod12(ch.bass))] = { frets: [-1, -1, -1, best[0], best[1], best[2]], barre: 0 };
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

  // Root-position triad around middle C, optionally with the root an octave below. A typed quality
  // plays its own notes (the fifth left out of five-note chords); a slash bass takes the left hand.
  function keysMidi(pc, quality, withBass, bass) {
    const r = mod12(pc);
    const n0 = r < 7 ? 60 + r : 48 + r;
    let v;
    if (ANALYSED.has(quality)) v = [n0, n0 + (quality.startsWith("m") ? 3 : 4), n0 + 7];
    else {
      const all = CHORDS.qualities[quality].intervals;
      // Within the two octaves the keys panel draws (48-71): a ninth or a seventh above it folds down.
      v = [...new Set((all.length > 4 ? all.filter((i) => i !== 7) : all).map((i) => (n0 + i > 71 ? n0 + i - 12 : n0 + i)))].sort((a, b) => a - b);
    }
    // A slash bass below the hand, heard; drawn (withBass false: the keys panel's two octaves) at the
    // panel's bottom octave.
    if (!isNone(bass)) return withBass ? [n0 - 12 - mod12(r - bass), ...v] : [...new Set([48 + mod12(bass), ...v])];
    return withBass ? [n0 - 12, ...v] : v;
  }

  // What the keys heard on the record in a bar (`pcs`, before transposition) says against the chart (spec 015):
  // "none" (no upper note), "root" (the chord's root alone), { other } (the third the chart's chord does not
  // have, without its own), or null (a reading to show as heard). The third is only checked on a bar of one
  // chord that has exactly one third (no sus, 5 or no chord).
  function voicingVerdict(cur, chords, pcs) {
    if (!pcs.length) return "none";
    if (cur.pc < 0) return null;
    if (pcs.length === 1 && mod12(pcs[0]) === mod12(cur.pc)) return "root";
    const quality = CHORDS.qualities[cur.quality];
    if (chords.length !== 1 || !quality) return null;
    const tones = quality.intervals.map(mod12);
    if (tones.includes(3) === tones.includes(4)) return null;
    const third = tones.includes(3) ? 3 : 4;
    const heard = pcs.map(mod12);
    const other = mod12(cur.pc + 7 - third);
    return heard.includes(other) && !heard.includes(mod12(cur.pc + third)) ? { other } : null;
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

  // The slots a drum plays, said as a drummer says them: "every eighth" rather than eight counts.
  function playedText(played, per) {
    const n = played.filter(Boolean).length;
    if (!n) return "";
    if (n === played.length) return W.t("every sixteenth");
    if (played.every((p, i) => p === (i % 2 === 0))) return W.t("every eighth");
    if (n > played.length / 2) return W.t("most sixteenths");
    return hitsText(played.map(Number), per, (p, i) => played[i]);
  }

  W.instruments = {
    // A chord's slash bass moved by t semitones, or null.
    bassOf: (c, t) => (isNone(c.bass) ? null : c.bass + (t || 0)),
    STRINGS, VOICES, tableShape, barreShape, movableShape, openOrBarre, triadOf, triadCandidates, funkVoicings,
    fingeredMidi, keysMidi, voicingVerdict, bassFrets, counts, bestTranspose, hitsText, grooveHits, playedText,
  };
})();
