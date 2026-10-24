// The words typed by hand (spec 029): a sung line typed as a singer writes it under the bars,
//   When you walk, | I stum- ble _ on
// `|` a bar line (the word after it on the next bar's beat one), the words of a bar sharing its beats by syllables,
// `_` one more syllable holding the word before it, `-` joining two syllables, "(ooh)" a backing vocal. The twin of
// woodshed/typed.py (the library reads the line it is sent and computes every time; the page reads it the same way
// to say it back before saving), checked on tests/words_typed_cases.json. Pure functions.
(function () {
  "use strict";
  const W = window.Woodshed;
  const MAX_BARS = 16;
  const MAX_WORDS = 40;
  const MAX_CHARS = 200;
  const KEY = /^t[0-9a-f]{8}$/;
  const VOWELS = /[aeiouyàâäéèêëîïôöùûüáíóúýãõåæœøаеёиоуыэюяіїєαεηιουωάέήίόύώϊϋΐΰ]+/gu;
  const CJK = /[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]/gu;
  const BACKING = /\(([^)]*)\)/g;
  const HOLD = "_";

  const ms = (t) => Math.floor(t * 1000 + 0.5) / 1000; // as typed.py _ms
  const num = (x) => typeof x === "number" && Number.isFinite(x);

  // A final e, es or ed after a consonant, not sung ("love", "comes", "walked"); "wanted", "roses", "table" sing it.
  function silentE(w) {
    const m = /([b-df-hj-np-tv-z])(e|es|ed)$/.exec(w);
    if (!m) return false;
    const [, c, end] = m;
    if (end === "ed") return !"td".includes(c);
    if (end === "es") return !"sxz".includes(c) && !/(ches|shes|ges|ces)$/.test(w);
    return !(c === "l" && w.length >= 3 && !"aeiouy".includes(w[w.length - 3]));
  }

  // Its vowel groups (a final silent e dropped when another is there, "qu" a consonant), one per CJK character.
  function syllables(word) {
    const w = word.toLowerCase();
    const cjk = (w.match(CJK) || []).length;
    const letters = w.replace(CJK, " ").replace(/[^\p{L}]/gu, "").replace(/qu/g, "q");
    let n = (letters.match(VOWELS) || []).length;
    if (n > 1 && silentE(letters)) n--;
    return Math.max(1, cjk + n);
  }

  // The nearest bar's beat length, at either end of the tracked beats.
  function beatLength(beats, per, last) {
    const n = beats.length;
    const span = Math.min(n - 1, per);
    return last ? (beats[n - 1] - beats[n - 1 - span]) / span : (beats[span] - beats[0]) / span;
  }

  // The time of beat `at` (an index in song.beats), to the ms (typed.beat_time).
  function beatTime(meta, at) {
    const beats = meta.beats;
    const n = beats.length;
    if (!n) return 0;
    if (n === 1) return ms(Math.max(0, beats[0] + (at * 60) / meta.bpm));
    const per = meta.beats_per_bar;
    let t;
    if (at > n - 1) t = beats[n - 1] + (at - (n - 1)) * beatLength(beats, per, true);
    else if (at < 0) t = beats[0] + at * beatLength(beats, per, false);
    else {
      const i = Math.min(Math.floor(at), n - 2);
      t = beats[i] + (at - i) * (beats[i + 1] - beats[i]);
    }
    return ms(Math.max(0, t));
  }

  // The beat index sounding at time t, with its fraction (typed.beat_at).
  function beatAt(meta, t) {
    const beats = meta.beats;
    const n = beats.length;
    if (n < 2) return 0;
    const per = meta.beats_per_bar;
    if (t >= beats[n - 1]) return n - 1 + (t - beats[n - 1]) / beatLength(beats, per, true);
    if (t < beats[0]) return (t - beats[0]) / beatLength(beats, per, false);
    let lo = 0;
    let hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (beats[mid] <= t) lo = mid;
      else hi = mid;
    }
    return lo + (t - beats[lo]) / (beats[lo + 1] - beats[lo]);
  }

  const barOf = (meta, at) => Math.floor((at - meta.first_beat) / meta.beats_per_bar + 1e-9);
  const clean = (text) => String(text).normalize("NFC").replace(/\ufeff/g, " ").split(/\s+/).filter(Boolean).join(" "); // as typed.py
  const tokens = (segment) => segment.replace(BACKING, " ").split(/\s+/).filter((t) => t && t !== "-");
  const wordsIn = (segment) => tokens(segment).filter((t) => t !== HOLD).length;

  class Refused extends Error {
    constructor(code, bar) {
      super(code);
      this.code = code;
      this.bar = bar;
    }
  }

  function bars(text) {
    const raw = text.split("|").map((s) => s.split(/\s+/).filter(Boolean).join(" "));
    if (raw.length > MAX_BARS) throw new Refused("bars");
    let lead = 0;
    while (lead < raw.length && !wordsIn(raw[lead])) lead++;
    if (lead === raw.length) throw new Refused("empty");
    return [raw.slice(lead), lead];
  }

  function joined(words) {
    let out = "";
    for (const w of words) out += w.length > 1 && w.endsWith("-") ? w.slice(0, -1) : w + " ";
    return out.trim();
  }

  // The words of the bars typed as before, by their index in the new line (typed._kept).
  function kept(list, at, meta, old) {
    if (!old || typeof old.notation !== "string" || !Array.isArray(old.words) || !old.words.length) return {};
    let oldBars;
    try {
      oldBars = bars(clean(old.notation))[0];
    } catch (err) {
      if (err instanceof Refused) return {};
      throw err;
    }
    const counts = oldBars.map(wordsIn);
    if (counts.reduce((a, b) => a + b, 0) !== old.words.length || !old.words.every((w) => num(w.at))) return {};
    const oldStart = barOf(meta, old.words[0].at);
    const byBar = new Map();
    let i = 0;
    oldBars.forEach((s, k) => {
      byBar.set(oldStart + k, [s, old.words.slice(i, i + counts[k])]);
      i += counts[k];
    });
    const out = {};
    const start = barOf(meta, at);
    i = 0;
    list.forEach((s, k) => {
      const n = wordsIn(s);
      const was = byBar.get(start + k);
      if (was && was[0] === s && was[1].length === n) for (let j = 0; j < n; j++) out[i + j] = was[1][j];
      i += n;
    });
    return out;
  }

  // A line typed in the notation from beat `at` (its first bar's beat one): {text, backing, notation, words}, or
  // {error, bar} (typed.typed_line).
  function line(input, at, meta, old, until) {
    try {
      const text = clean(input);
      if (!text) throw new Refused("empty");
      if ([...text].length > MAX_CHARS) throw new Refused("length");
      const [list, lead] = bars(text);
      const per = meta.beats_per_bar;
      const count = meta.bars.length;
      at += lead * per;
      const backing = [];
      for (const m of text.matchAll(BACKING)) if (m[1].trim()) backing.push(m[1].trim());
      const texts = [];
      const starts = [];
      const holdEnd = [];
      let last = -1;
      list.forEach((segment, k) => {
        const start = at + k * per;
        const b = barOf(meta, start);
        if (b < 0 || b >= count) throw new Refused("end");
        const units = [];
        for (const tok of tokens(segment)) {
          if (tok === HOLD) {
            units.push(-1);
            continue;
          }
          texts.push(tok);
          for (let s = syllables(tok); s > 0; s--) units.push(texts.length - 1);
        }
        const size = units.length;
        if (!size) return;
        const grid = [1, 0.5, 0.25].find((g) => size <= per / g);
        if (grid === undefined) throw new Refused("crowded", b + 1);
        const slots = Math.round(per / grid);
        const pos = units.map((_, j) => start + Math.floor((j * slots) / size) * grid).concat([start + per]);
        units.forEach((w, j) => {
          if (w > last) {
            starts.push(pos[j]);
            holdEnd.push(pos[j + 1]);
            last = w;
          } else if (last >= 0) holdEnd[last] = pos[j + 1];
        });
      });
      if (!texts.length) throw new Refused("empty");
      if (texts.length > MAX_WORDS) throw new Refused("words");
      const keep = kept(list, at, meta, old);
      const out = texts.map((w, k) => (k in keep ? { ...keep[k] } : { text: w, at: starts[k], start: beatTime(meta, starts[k]) }));
      out.forEach((w, k) => {
        const nxt = k + 1 < out.length ? out[k + 1].start : null;
        if (k in keep) w.end = nxt === null ? w.end : Math.min(w.end, nxt);
        else w.end = nxt !== null ? nxt : beatTime(meta, holdEnd[k]);
        if (nxt === null && num(until) && until > w.start) w.end = Math.min(w.end, until);
        w.end = Math.max(w.end, w.start);
      });
      return { text: joined(texts), backing, notation: list.join(" | ").split(/\s+/).filter(Boolean).join(" "), words: out };
    } catch (err) {
      if (err instanceof Refused) return err.bar === undefined ? { error: err.code } : { error: err.code, bar: err.bar };
      throw err;
    }
  }

  function span(ln) {
    const ws = ln && Array.isArray(ln.words) ? ln.words.filter((w) => w && num(w.start) && num(w.end)) : [];
    return ws.length ? [Math.min(...ws.map((w) => w.start)), Math.max(...ws.map((w) => w.end))] : null;
  }

  // The typed lines on the sheet, after the placement's lines, in time order; a placed line meeting one is covered
  // (typed.with_typed).
  function withTyped(data, entries) {
    const typed = [];
    for (const [k, e] of Object.entries(entries || {})) {
      if (!KEY.test(k) || !e || typeof e !== "object" || e.typed !== true || !Array.isArray(e.lines) || !e.lines.length) continue;
      const ln = e.lines[0];
      if (!ln || typeof ln !== "object") continue;
      const line = {
        text: ln.text === undefined ? "" : ln.text, tag: ln.tag || "", block: -1, backing: [...(ln.backing || [])],
        sung: true, check: null, typed: true, key: k, words: (ln.words || []).map((w) => ({ ...w })),
      };
      if (span(line)) typed.push(line);
    }
    if (!typed.length) return data;
    typed.sort((a, b) => span(a)[0] - span(b)[0]);
    const spans = typed.map(span);
    const lines = (data.lines || []).map((ln) => {
      if (!ln || typeof ln !== "object" || !ln.sung) return ln;
      const s = span(ln);
      return s && spans.some((t) => s[0] < t[1] && t[0] < s[1]) ? { ...ln, sung: false, covered: true } : ln;
    });
    return { ...data, lines: lines.concat(typed) };
  }

  // A typed entry as the library sends it (app.py _checked_typed_entry).
  function valid(k, v) {
    if (!KEY.test(k) || !v || typeof v !== "object" || v.typed !== true || typeof v.notation !== "string") return false;
    if (!(v.src === null || typeof v.src === "string") || !Array.isArray(v.lines) || v.lines.length !== 1) return false;
    const ln = v.lines[0];
    return !!ln && typeof ln.text === "string" && Array.isArray(ln.words) && ln.words.length > 0 &&
      ln.words.every((w) => w && typeof w.text === "string" && num(w.at) && num(w.start) && num(w.end));
  }

  W.typedWords = { KEY, syllables, beatTime, beatAt, barOf, line, span, withTyped, valid };
})();
