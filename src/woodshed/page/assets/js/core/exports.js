// Text exports made in the browser, with the listener's corrections: ChordPro, MIREX .lab, JSON.
// Same output as woodshed.exports in Python for an uncorrected song (a test compares them).
(function () {
  "use strict";
  const W = window.Woodshed;
  const LAB_QUALITY = { "": "maj", m: "min", 7: "7", m7: "min7" };
  const SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const CONTROL = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;
  // Text inside a ChordPro directive: one line, no braces (as woodshed.exports.directive_text).
  const directiveText = (text) => text.replace(/[\r\n]+/g, " ").replace(CONTROL, "").replace(/\{/g, "(").replace(/\}/g, ")");

  // The song as published (schema v1), with corrections in place of the doubts they settle.
  function data(song) {
    const out = JSON.parse(JSON.stringify(song.song));
    out.bars = song.bars.map((bar, u) => ({
      ...out.bars[u],
      chords: bar.chords.map((c) => ({ pc: c.pc, quality: c.quality, beats: c.beats, doubt: c.fixed ? null : c.doubt })),
    }));
    return out;
  }

  // ChordPro, as woodshed.exports.chordpro: each part under its name; a sung part as its words with
  // each chord on its word, a part without words as a grid. Chords to check are listed, not marked.
  const ENVIRONMENT = { chorus: "chorus", bridge: "bridge" };
  // Words as ChordPro reads them (as woodshed.exports.lyric_text and lyric_row): a brace would open a
  // directive, a row starting with # would be a comment.
  const lyricText = (text) => text.replace(CONTROL, "").replace(/\{/g, "(").replace(/\}/g, ")");
  const lyricRow = (row) => (row.startsWith("#") ? " " + row : row);

  // `transpose`: in the key the page shows (exports.chordpro(song, words, transpose) in Python).
  function chordpro(song, words, transpose = 0) {
    const d = data(song);
    const name = (c) => (c.pc < 0 ? "N.C." : song.chordName(c, transpose));
    const cells = (u) => {
      const out = [];
      for (const c of d.bars[u].chords) {
        out.push(name(c));
        for (let i = 1; i < c.beats; i++) out.push(".");
      }
      return out.join(" ");
    };
    const quote = (text) => directiveText(text).replace(/"/g, "'");
    const grid = (label, rows) => [
      '{start_of_grid: label="' + quote(label) + '"}',
      ...rows.map(([bars, times]) => {
        const text = bars.map(cells).join(" | ");
        return times > 1 ? "|: " + text + " :|" + (times > 2 ? " x" + times : "") : "| " + text + " |";
      }),
      "{end_of_grid}",
    ];
    const lines = [
      "{title: " + directiveText(d.title) + "}",
      "{key: " + song.keyName(transpose) + "}",
      "{tempo: " + Math.round(d.bpm) + "}",
      "{time: " + d.beats_per_bar + "/4}",
      "{comment: chords found by woodshed from " + directiveText(d.file) + "}",
    ];
    const sections = (words && words.sections) || d.sections || [];
    // The chords to check by ear, by part (exports.py _to_check): a file has no bar numbers.
    const doubtful = [];
    d.bars.forEach((bar, u) => bar.chords.forEach((c) => c.doubt && (c.doubt.kind || "chord") === "chord" && doubtful.push([u, c]))); // no kind: older data
    if (doubtful.length) {
      let check;
      if (!sections.length) {
        const bars = [...new Set(doubtful.map(([u]) => u + 1))];
        check = (bars.length === 1 ? "bar " : "bars ") + bars.join(", ");
      } else {
        const parts = new Map();
        for (const [u, c] of doubtful) {
          const sec = sections.find((s) => s.start <= u && u < s.end);
          const part = sec ? sec.name : "outside the parts";
          if (!parts.has(part)) parts.set(part, [[], []]);
          const [bars, names] = parts.get(part);
          bars.push(u + 1);
          if (!names.includes(name(c))) names.push(name(c));
        }
        check = [...parts].map(([part, [bars, names]]) => part + ", " + barList(bars) + " (" + names.join(", ") + ")").join(", ");
      }
      lines.push("{comment: check by ear: " + directiveText(check) + "}");
    }
    if (!sections.length) {
      for (const group of d.groups) lines.push("", ...grid(group.label, [[group.occurrences[0], group.occurrences.length]]));
      return lines.join("\n") + "\n";
    }
    const sung = sungRows(song, words, sections, name);
    sections.forEach((sec, k) => {
      lines.push("");
      if (sung.has(k)) {
        const env = ENVIRONMENT[sec.role] || "verse";
        lines.push("{start_of_" + env + ': label="' + quote(sec.name) + '"}', ...sung.get(k), "{end_of_" + env + "}");
      } else {
        const rows = [];
        for (let u = sec.start; u < sec.end; u += 4) {
          const row = [];
          for (let v = u; v < Math.min(u + 4, sec.end); v++) row.push(v);
          const last = rows[rows.length - 1];
          if (last && last[0].map(cells).join("|") === row.map(cells).join("|")) last[1] += 1;
          else rows.push([row, 1]);
        }
        lines.push(...grid(sec.name, rows));
      }
    });
    return lines.join("\n") + "\n";
  }

  // Bar numbers as a musician reads them: "bar 3", "bars 18-19, 23" (as exports.bar_list).
  function barList(bars) {
    const spans = [];
    for (const b of [...new Set(bars)].sort((x, y) => x - y)) {
      const last = spans[spans.length - 1];
      if (last && b === last[1] + 1) last[1] = b;
      else spans.push([b, b]);
    }
    return (spans.length === 1 && spans[0][0] === spans[0][1] ? "bar " : "bars ") + spans.map(([a, z]) => (a === z ? String(a) : a + "-" + z)).join(", ");
  }

  // The rows of each sung part: its lines with the chords on their words, the chords between lines
  // on rows of their own, the chords of the bar leading into a line on its first word.
  function sungRows(song, words, sections, name) {
    const out = new Map();
    if (!words || !words.lines.length) return out;
    const per = song.per;
    const barTime = (60 / song.song.bpm) * per;
    const sectionOfBar = (u) => {
      let k = 0;
      sections.forEach((sec, i) => {
        if (sec.start <= u) k = i;
      });
      return k;
    };
    const chord = (p) => "[" + name(p.chord) + "]";
    // Chords with no word of their own: bar by bar, four bars a row, never one long row.
    const chordRows = (ps) => {
      const bars = [];
      let last = null;
      for (const p of ps) {
        if (p.bar !== last) {
          bars.push([]);
          last = p.bar;
        }
        bars[bars.length - 1].push(chord(p));
      }
      const out = [];
      for (let i = 0; i < bars.length; i += 4) out.push("| " + bars.slice(i, i + 4).map((b) => b.join(" ")).join(" | ") + " |"); // framed, as exports.py
      return out;
    };
    const placed = words.place(words.changes());
    const bySection = new Map();
    words.lines.forEach((ln, li) => {
      const k = sectionOfBar(song.barAt(ln.start + barTime / 2));
      if (!bySection.has(k)) bySection.set(k, []);
      bySection.get(k).push(li);
    });
    const gaps = new Map();
    const onWord = new Map();
    for (const p of placed) {
      if (p.li === null) {
        const k = sectionOfBar(p.bar);
        if (!gaps.has(k)) gaps.set(k, []);
        gaps.get(k).push(p);
      } else {
        const key = p.li + ":" + p.wi;
        if (!onWord.has(key)) onWord.set(key, []);
        onWord.get(key).push(p);
      }
    }
    for (const [k, ids] of bySection) {
      const rows = [];
      let waiting = (gaps.get(k) || []).slice();
      for (const li of ids) {
        const ln = words.lines[li];
        const lead = waiting.filter((p) => ln.start - barTime <= p.t && p.t < ln.start);
        const before = waiting.filter((p) => p.t < ln.start - barTime);
        rows.push(...chordRows(before));
        let inside = waiting.filter((p) => ln.start <= p.t && p.t < ln.end);
        waiting = waiting.filter((p) => p.t >= ln.end);
        let tokens = [];
        ln.words.forEach((w, wi) => {
          const timed = typeof w.start === "number" && typeof w.end === "number"; // as lyrics.js reads a word
          const ahead = inside.filter((p) => timed && p.t <= w.start);
          inside = inside.filter((p) => !(timed && p.t <= w.start));
          const chords = [...(wi === 0 ? lead : []), ...ahead, ...(onWord.get(li + ":" + wi) || [])];
          // One chord a word. Those before it go on a chord row of their own: above the line for its
          // first word; for a later word the line breaks there (they change while the word before it
          // is held).
          const extra = chords.slice(0, -1);
          if (extra.length && tokens.length) {
            rows.push(lyricRow(tokens.join(" ")));
            tokens = [];
          }
          rows.push(...chordRows(extra));
          tokens.push((chords.length ? chord(chords[chords.length - 1]) : "") + lyricText(w.text));
        });
        tokens.push(...inside.map(chord));
        const backing = (ln.backing || []).map((b) => " (" + lyricText(b) + ")").join("");
        rows.push(lyricRow(tokens.join(" ") + backing));
      }
      rows.push(...chordRows(waiting));
      out.set(k, rows);
    }
    return out;
  }

  function lab(song) {
    const d = data(song);
    const per = d.beats_per_bar;
    const rows = [];
    let past = false;
    d.bars.forEach((bar, u) => {
      let b = u * per;
      for (const c of bar.chords) {
        const label = c.pc < 0 ? "N" : SHARP[c.pc] + ":" + LAB_QUALITY[c.quality];
        const start = Math.max(0, song.beatTime(b));
        const end = Math.min(d.duration, song.beatTime(b + c.beats)); // never past the end of the file
        if (past || start >= d.duration) {
          past = true;
          return;
        }
        if (rows.length && rows[rows.length - 1][2] === label) rows[rows.length - 1][1] = end;
        else rows.push([start, end, label]);
        b += c.beats;
      }
    });
    if (rows.length && rows[0][0] > 0) rows.unshift([0, rows[0][0], "N"]);
    if (rows.length && rows[rows.length - 1][1] < d.duration) rows.push([rows[rows.length - 1][1], d.duration, "N"]);
    return rows.map(([s, e, label]) => s.toFixed(3) + " " + e.toFixed(3) + " " + label + "\n").join("");
  }

  const json = (song) => JSON.stringify(data(song), null, 1) + "\n";

  // MIDI, as woodshed.exports.midi: chords, bass line and drums on the beat grid (type 1, 480 PPQ),
  // made here so a correction is in the file.
  const PPQ = 480;
  const SLOTS = 4; // sixteenths per beat in the parts
  // Python's round(): half to even (60,000,000 / BPM can fall on a half).
  const pyRound = (x) => (Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : Math.round(x));
  const utf8 = (text) => Array.from(new TextEncoder().encode(text));
  function vlq(n) {
    const out = [n & 0x7f];
    n = Math.floor(n / 128);
    while (n) {
      out.push((n & 0x7f) | 0x80);
      n = Math.floor(n / 128);
    }
    return out.reverse();
  }
  const u32 = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];
  const u16 = (n) => [(n >>> 8) & 255, n & 255];
  function track(events, name) {
    const title = utf8(name);
    const out = [0x00, 0xff, 0x03, ...vlq(title.length), ...title];
    let now = 0;
    const sorted = events.slice().sort((a, b) => a[0] - b[0] || ((a[1][0] & 0xf0) !== 0x80) - ((b[1][0] & 0xf0) !== 0x80));
    for (const [tick, msg] of sorted) {
      out.push(...vlq(tick - now), ...msg);
      now = tick;
    }
    out.push(0x00, 0xff, 0x2f, 0x00);
    return [0x4d, 0x54, 0x72, 0x6b, ...u32(out.length), ...out]; // MTrk
  }
  function note(events, channel, pitch, start, length, velocity) {
    events.push([start, [0x90 | channel, pitch, velocity]]);
    events.push([start + Math.max(1, length), [0x80 | channel, pitch, 0]]);
  }
  function spans(d) {
    const out = [];
    d.bars.forEach((bar, u) => {
      let b = u * d.beats_per_bar;
      for (const c of bar.chords) {
        out.push([b, c.beats, c]);
        b += c.beats;
      }
    });
    return out;
  }
  function midi(song) {
    const d = data(song);
    const per = d.beats_per_bar;
    const tempo = u32(pyRound(60000000 / d.bpm)).slice(1);
    const meta = [[0, [0xff, 0x51, 0x03, ...tempo]], [0, [0xff, 0x58, 0x04, per, 2, 24, 8]]];
    const chords = [];
    for (const [b, n, c] of spans(d)) {
      if (c.pc < 0) continue;
      const third = c.quality.startsWith("m") ? 3 : 4;
      const intervals = [0, third, 7, ...(c.quality.endsWith("7") ? [10] : [])];
      for (const i of intervals) note(chords, 0, 53 + ((((c.pc - 5) % 12) + 12) % 12) + i, b * PPQ, n * PPQ - 10, 80);
    }
    const bass = [];
    const drums = [];
    const sixteenth = PPQ / SLOTS;
    if (d.parts) {
      d.parts.bass.forEach((line, u) => {
        const onsets = [];
        line.forEach((e, i) => e && onsets.push([i, e]));
        onsets.forEach(([i, e], k) => {
          const end = k + 1 < onsets.length ? onsets[k + 1][0] : line.length;
          note(bass, 1, e[0], u * per * PPQ + i * sixteenth, (end - i) * sixteenth - 10, 90);
        });
      });
      const groove = d.parts.groove;
      if (groove) {
        const hits = W.instruments.grooveHits(groove); // as exports.groove_hits
        for (let u = 0; u < d.bars.length; u++) {
          for (let i = 0; i < per * SLOTS; i++) {
            const at = u * per * PPQ + i * sixteenth;
            for (const [row, pitch] of [["kick", 36], ["snare", 38], ["hat", 42]]) {
              if (hits[row][i]) note(drums, 9, pitch, at, sixteenth / 2, row !== "hat" ? 100 : 70);
            }
          }
        }
      }
    } else {
      for (const [b, n, c] of spans(d)) if (c.pc >= 0) note(bass, 1, 36 + c.pc, b * PPQ, n * PPQ - 10, 90);
    }
    const tracks = [
      track(meta, Array.from(d.title).slice(0, 120).join("")),
      track([[0, [0xc0, 0]], ...chords], "Chords"),
      track([[0, [0xc1, 33]], ...bass], "Bass"),
    ];
    if (drums.length) tracks.push(track(drums, "Drums"));
    return new Uint8Array([0x4d, 0x54, 0x68, 0x64, ...u32(6), ...u16(1), ...u16(tracks.length), ...u16(PPQ), ...tracks.flat()]);
  }

  // MusicXML, as woodshed.exports.musicxml: chord symbols over the bars, and the bass line.
  const KIND = { "": "major", m: "minor", 7: "dominant", m7: "minor-seventh" };
  const STEPS = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  const xmlText = (text) => text.replace(CONTROL, "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  function musicxml(song) {
    const d = data(song);
    const per = d.beats_per_bar;
    const slots = per * SLOTS;
    const spelled = (pc) => {
      const root = song.chordName({ pc, quality: "" }, 0);
      return [root[0], { "": 0, "#": 1, b: -1 }[root.slice(1)]];
    };
    const key = d.key;
    const major = key.mode === "maj" ? key.pc : (key.pc + 3) % 12;
    const SHARPS = { 0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6 };
    const FLATS = { 5: -1, 10: -2, 3: -3, 8: -4, 1: -5 };
    const fifths = major in FLATS ? FLATS[major] : SHARPS[major];
    const TABLE = [[16, "whole", false], [12, "half", true], [8, "half", false], [6, "quarter", true],
      [4, "quarter", false], [3, "eighth", true], [2, "eighth", false], [1, "16th", false]];
    const durations = (n) => {
      const out = [];
      while (n > 0) {
        const t = TABLE.find((x) => x[0] <= n);
        out.push(t);
        n -= t[0];
      }
      return out;
    };
    const pitchXml = (m) => {
      const [step, alter] = spelled(((m % 12) + 12) % 12);
      const octave = Math.floor((m - STEPS[step] - alter) / 12) - 1;
      return "<pitch><step>" + step + "</step>" + (alter ? "<alter>" + alter + "</alter>" : "") + "<octave>" + octave + "</octave></pitch>";
    };
    const notes = (events) =>
      events.map(([length, m]) => {
        const pieces = durations(length);
        return pieces.map(([size, kind, dot], i) => {
          const tie = m !== null && pieces.length > 1;
          const ties = tie ? (i > 0 ? '<tie type="stop"/>' : "") + (i < pieces.length - 1 ? '<tie type="start"/>' : "") : "";
          const kinds = tie ? [...(i > 0 ? ["stop"] : []), ...(i < pieces.length - 1 ? ["start"] : [])] : [];
          const tied = kinds.length ? "<notations>" + kinds.map((k) => '<tied type="' + k + '"/>').join("") + "</notations>" : "";
          const body = m === null ? "<rest/>" : pitchXml(m);
          const timing = "<duration>" + size + "</duration>" + ties + "<voice>1</voice><type>" + kind + "</type>" + (dot ? "<dot/>" : "");
          return "<note>" + body + timing + tied + "</note>";
        }).join("");
      }).join("");
    const attributes = "<attributes><divisions>" + SLOTS + "</divisions><key><fifths>" + fifths + "</fifths><mode>" +
      (key.mode === "maj" ? "major" : "minor") + "</mode></key><time><beats>" + per + "</beats><beat-type>4</beat-type></time>";
    const measures = d.bars.map((bar, u) => {
      const xml = ['<measure number="' + (u + 1) + '">'];
      if (u === 0) xml.push(attributes + "<clef><sign>F</sign><line>4</line></clef></attributes>");
      let offset = 0;
      for (const c of bar.chords) {
        if (c.pc >= 0) {
          const [step, alter] = spelled(c.pc);
          xml.push("<harmony><root><root-step>" + step + "</root-step>" + (alter ? "<root-alter>" + alter + "</root-alter>" : "") + "</root><kind>" + KIND[c.quality] + "</kind>");
          xml.push(offset ? "<offset>" + offset * SLOTS + "</offset></harmony>" : "</harmony>");
        }
        offset += c.beats;
      }
      const events = [];
      if (d.parts) {
        const line = d.parts.bass[u];
        const onsets = [];
        line.forEach((e, i) => e && onsets.push(i));
        if (!onsets.length || onsets[0] > 0) events.push([onsets.length ? onsets[0] : slots, null]);
        onsets.forEach((i, k) => events.push([(k + 1 < onsets.length ? onsets[k + 1] : slots) - i, line[i][0]]));
      } else events.push([slots, null]);
      xml.push(notes(events), "</measure>");
      return xml.join("");
    });
    return (
      '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n' +
      '<score-partwise version="4.0"><work><work-title>' + xmlText(d.title) + "</work-title></work>" +
      "<identification><encoding><software>woodshed</software></encoding></identification>" +
      '<part-list><score-part id="P1"><part-name>' + (d.parts ? "Bass" : "Chords") + "</part-name></score-part></part-list>" +
      '<part id="P1">' + measures.join("") + "</part></score-partwise>\n"
    );
  }

  // Save as a file: a Blob download works from a page opened on disk.
  function save(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = W.h("a", { href: url, download: name, style: { display: "none" } });
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 0);
  }

  W.exports = { data, chordpro, lab, json, midi, musicxml, save };
})();
