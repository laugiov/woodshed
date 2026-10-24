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
    if (!INDEX.test(k) || !v || typeof v !== "object" || typeof v.was !== "string") return false;
    if (v.gone !== undefined) return v.gone === "not-sung" && Object.keys(v).length === 2;
    if (v.voice !== undefined && v.voice !== "other") return false;
    if (v.lines === undefined) return v.voice === "other";
    if (!Array.isArray(v.lines) || v.lines.length !== 1) return false;
    const ln = v.lines[0];
    return !!ln && typeof ln.text === "string" && Array.isArray(ln.words) && ln.words.length > 0 &&
      ln.words.every((w) => w && typeof w.text === "string" && (timed(w) || (w.start === null && w.end === null))) &&
      (ln.check === null || ln.check === undefined || typeof ln.check === "string") &&
      (ln.backing === undefined || (Array.isArray(ln.backing) && ln.backing.every((b) => typeof b === "string")));
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
      if (Array.isArray(e.lines) && e.lines.length) {
        const fixed = e.lines[0];
        const words = fixed.words.map((w) => ({ ...w }));
        Object.assign(ln, { text: fixed.text, backing: [...(fixed.backing || [])], words, check: fixed.check === undefined ? null : fixed.check, sung: words.some(timed) });
      }
      if (e.voice === "other") ln.voice = "other";
      ln.edited = true;
    }
    return { ...data, lines };
  }

  W.wordEdits = { key, apply, valid, fnv1a };
})();
