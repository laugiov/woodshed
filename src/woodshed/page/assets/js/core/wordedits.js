// The band's fixes of the words on the sheet (spec 028), as the library keeps them (app.py set_words):
// by the index of the line in lyrics.json, under a key of the placement. Pure functions, mirrored in
// Python (lyrics.words_key, lyrics.apply_edits) and checked against them by the tests.
(function () {
  "use strict";
  const W = window.Woodshed;
  const INDEX = /^(0|[1-9][0-9]{0,3})$/; // as app.py LINE_INDEX

  // 32-bit FNV-1a over UTF-16 code units (app.js, woodshed/fnv.py).
  function fnv1a(text) {
    let hash = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(16);
  }

  const finite = (t) => typeof t === "number" && Number.isFinite(t);
  const timed = (w) => !!w && typeof w === "object" && finite(w.start) && finite(w.end);

  // Each line's text and its words' starts in whole milliseconds: the same words placed again on the
  // same voice, or a rebuild of the page, give the same key.
  function key(data) {
    const lines = (data && Array.isArray(data.lines) ? data.lines : []).map((ln) => {
      const line = ln && typeof ln === "object" ? ln : {};
      const words = Array.isArray(line.words) ? line.words : [];
      return [
        typeof line.text === "string" ? line.text : "",
        words.map((w) => (w && typeof w === "object" && finite(w.start) ? Math.floor(w.start * 1000 + 0.5) : null)),
      ];
    });
    return fnv1a(JSON.stringify(lines));
  }

  // A fix as the library sends it: a line's words in time, another voice, or not in this recording.
  function valid(k, v) {
    if (W.typedWords.KEY.test(k)) return W.typedWords.valid(k, v); // a line typed by hand (spec 029)
    if (!INDEX.test(k) || !v || typeof v !== "object" || typeof v.was !== "string") return false;
    if (v.gone !== undefined) return (v.gone === "not-sung" || v.gone === "joined") && Object.keys(v).length === 2;
    if (v.voice !== undefined && v.voice !== "other") return false;
    if (v.unjoined !== undefined && v.unjoined !== null && (v.lines === undefined || v.unjoined.unjoined !== undefined || !valid(k, v.unjoined))) return false;
    if (v.lines === undefined) return v.voice === "other";
    if (!Array.isArray(v.lines) || v.lines.length < 1 || v.lines.length > 4) return false; // more than one: a split
    return v.lines.every((ln) => !!ln && typeof ln.text === "string" && Array.isArray(ln.words) && ln.words.length > 0 &&
      ln.words.every((w) => w && typeof w.text === "string" && (timed(w) || (w.start === null && w.end === null))) &&
      (ln.check === null || ln.check === undefined || typeof ln.check === "string") &&
      (ln.backing === undefined || (Array.isArray(ln.backing) && ln.backing.every((b) => typeof b === "string"))));
  }

  // The placement with the fixes on it: a fixed line takes its words, times and check; another voice stays on
  // the sheet; a line not in this recording is no longer sung (its chords go where the placement rule puts them).
  function apply(data, entries) {
    if (!data || !Array.isArray(data.lines)) return data;
    const lines = data.lines.map((ln) => (ln && typeof ln === "object" && !Array.isArray(ln) ? { ...ln } : ln));
    for (const [k, e] of Object.entries(entries || {})) {
      const i = INDEX.test(k) ? Number(k) : -1;
      if (i < 0 || i >= lines.length || !lines[i] || typeof lines[i] !== "object" || !e || typeof e !== "object") continue;
      const ln = lines[i];
      if (e.gone === "not-sung") {
        ln.sung = false;
        ln.edited = "not-sung";
        continue;
      }
      if (e.gone === "joined") { // its words went to the line before it (spec 028 B)
        ln.sung = false;
        ln.edited = "joined";
        continue;
      }
      if (Array.isArray(e.lines) && e.lines.length) {
        const fixed = e.lines[0];
        const words = fixed.words.map((w) => ({ ...w }));
        Object.assign(ln, { text: fixed.text, backing: [...(fixed.backing || [])], words, check: fixed.check === undefined ? null : fixed.check, sung: words.some(timed) });
      }
      if (e.voice === "other") ln.voice = "other";
      ln.edited = true;
    }
    // The lines typed by hand (spec 029) after the rows, over those they cover.
    return W.typedWords.withTyped(splitRows({ ...data, lines }, entries), entries);
  }

  // A line split on the sheet (spec 028 B) as rows: its first line where it was, the others right after it, each
  // marked with `piece` (1, 2, 3); a fix, a window, an Undo still name the line by its index in the placement
  // (byIndex). Markers name the row they come before. lyrics._split_rows, step for step.
  function splitRows(data, entries) {
    const lines = data.lines;
    const more = {};
    for (const [k, e] of Object.entries(entries || {})) {
      const i = INDEX.test(k) ? Number(k) : -1;
      if (i < 0 || i >= lines.length || !lines[i] || typeof lines[i] !== "object" || !e || typeof e !== "object" || e.gone !== undefined) continue;
      if (Array.isArray(e.lines) && e.lines.length > 1) more[i] = e.lines.slice(1);
    }
    if (!Object.keys(more).length) return data;
    const rows = [];
    const where = [];
    lines.forEach((ln, i) => {
      where.push(rows.length);
      rows.push(ln);
      (more[i] || []).forEach((piece, j) => {
        const words = piece.words.map((w) => ({ ...w }));
        rows.push({ ...ln, text: piece.text, backing: [...(piece.backing || [])], words, check: piece.check === undefined ? null : piece.check, sung: words.some(timed), piece: j + 1 });
      });
    });
    const out = { ...data, lines: rows };
    if (Array.isArray(data.markers)) {
      out.markers = data.markers.map((m) => (m && typeof m === "object" && Number.isInteger(m.before) && m.before >= 0
        ? { ...m, before: m.before < where.length ? where[m.before] : rows.length } : m));
    }
    return out;
  }

  // The rows of the words with the fixes on, by the index of their line in the placement: a split line has two
  // to four rows, the others one.
  function byIndex(data) {
    const out = [];
    for (const row of data && Array.isArray(data.lines) ? data.lines : []) {
      if (row && typeof row === "object" && row.piece && out.length) out[out.length - 1].push(row);
      else out.push([row]);
    }
    return out;
  }

  W.wordEdits = { key, apply, valid, byIndex, fnv1a };
})();
