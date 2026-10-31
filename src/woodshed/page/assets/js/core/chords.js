// Chords a musician types on the chart: the parser and the qualities' table (core/chord-table.js,
// generated from chords.json). The same rules as woodshed/chords.py: a test runs both on one table
// of cases. Names and numerals still come from the view tables (core/song.js); this file only adds
// what a typed chord needs on top: its quality, its intervals and its slash bass.
(function () {
  "use strict";
  const W = window.Woodshed;
  const TABLE = W.CHORD_TABLE;
  const QUALITIES = TABLE.qualities;
  const ALIASES = TABLE.aliases;
  const REFUSALS = TABLE.refusals;
  const SPACES = /[ \t\r\n\u00a0]+/g; // the same class as chords.py
  const NATURALS = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  const ACCIDENTALS = { "#": 1, "♯": 1, b: -1, "♭": -1, "": 0 };
  const NO_CHORD_SPELLINGS = new Set(["N.C.", "NC", "N.C", "N/C"]);
  const CHORD = /^([A-Ga-g])([#♯b♭]?)([^/]*)(?:\/(.*))?$/;
  const NOTE = /^([A-Ga-g])([#♯b♭]?)$/;
  const ALTERED = /(?:^|7|9|11|13)[-+#b♯♭](?:5|9|11|13)/;
  const NO_CHORD = Object.freeze({ pc: -1, quality: "", bass: null });

  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

  // Only a capital M (major seventh, CM7) differs from its lower case.
  function qualityOf(suffix) {
    const lower = suffix.toLowerCase();
    const candidate = suffix.startsWith("M") && !lower.startsWith("maj") && !lower.startsWith("min") ? suffix : lower;
    for (const text of [suffix, candidate]) {
      if (has(QUALITIES, text)) return text;
      if (has(ALIASES, text)) return ALIASES[text];
    }
    return null;
  }

  // Why a chord is refused, in words (in English, as the library says it).
  const refuse = (code, root) => ({ refused: code, hint: TABLE.hints[code].replace(/\{root\}/g, root || "") });

  // A chord as written on a chord sheet: {pc, quality, bass} (pc -1 for no chord), or {refused, hint}.
  function parse(text) {
    let typed = String(text).replace(SPACES, "");
    if (!typed) return refuse("empty");
    if (typed.includes("|")) return refuse("bar-line");
    if (NO_CHORD_SPELLINGS.has(typed.toUpperCase())) return NO_CHORD;
    typed = typed.replace(/[()]/g, "");
    const m = CHORD.exec(typed);
    if (!m) return refuse("unknown");
    const [, root, accidental, suffix, bassText] = m;
    const pc = (NATURALS[root.toUpperCase()] + ACCIDENTALS[accidental] + 12) % 12;
    const named = root.toUpperCase() + accidental;
    const quality = qualityOf(suffix);
    if (quality === null) {
      const lower = suffix.toLowerCase();
      return refuse(has(REFUSALS, lower) ? REFUSALS[lower] : ALTERED.test(suffix) ? "altered" : "unknown", named);
    }
    let bass = null;
    if (bassText !== undefined) {
      const note = NOTE.exec(bassText);
      if (!note) return refuse(quality === "6" && bassText === "9" ? "six-nine" : "unknown", named);
      bass = (NATURALS[note[1].toUpperCase()] + ACCIDENTALS[note[2]] + 12) % 12;
      if (bass === pc) bass = null; // C/C is C
    }
    return { pc, quality, bass };
  }

  // The chord as the rehearsal sheet writes it (spec 031): "heard" as the chart has it; "usual" drops what the ear
  // rarely plays (9ths, add9) and keeps 7ths, sus, slash basses; "triads" keeps the third (or the sus, a power chord)
  // and no bass. Every quality of the chord table has its place; one typed otherwise is read by its third.
  const USUAL = { 9: "7", m9: "m7", maj9: "maj7", add9: "", madd9: "m" };
  const TRIADS = { "": "", m: "m", 5: "5", 6: "", m6: "m", 7: "", m7: "m", maj7: "", 9: "", m9: "m", maj9: "", add9: "",
    madd9: "m", sus2: "sus2", sus4: "sus4", "7sus4": "sus4", dim: "dim", dim7: "dim", m7b5: "dim", aug: "aug" };
  const triad = (q) => (q in TRIADS ? TRIADS[q] : /^dim/.test(q) ? "dim" : /^(aug|\+)/.test(q) ? "aug" : /^m(?!aj)/.test(q) ? "m" : /sus2/.test(q) ? "sus2" : /sus/.test(q) ? "sus4" : "");
  function simplify(c, level) {
    if (level !== "usual" && level !== "triads") return c;
    const out = Object.create(Object.getPrototypeOf(c));
    for (const k of Object.getOwnPropertyNames(c)) Object.defineProperty(out, k, Object.getOwnPropertyDescriptor(c, k)); // its key region too
    out.quality = level === "usual" ? (c.quality in USUAL ? USUAL[c.quality] : c.quality) : triad(c.quality);
    if (level === "triads") delete out.bass;
    return out;
  }

  W.chords = {
    parse,
    simplify,
    // The four qualities the analysis writes; every other one was typed by the band.
    analysed: (quality) => quality === "" || quality === "m" || quality === "7" || quality === "m7",
    // One identity for a chord everywhere: D and D/F# differ.
    key: (c) => c.pc + "|" + c.quality + "|" + (c.bass === undefined || c.bass === null ? "" : c.bass),
    NO_CHORD,
    qualities: () => Object.keys(QUALITIES),
    intervals: (quality) => QUALITIES[quality].intervals.slice(),
    roman: (quality) => QUALITIES[quality].roman,
    degree: (semitones) => TABLE.degrees[((semitones % 12) + 12) % 12],
  };
})();
