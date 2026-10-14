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

  function chordpro(song) {
    const d = data(song);
    const name = (c) => (c.pc < 0 ? "N.C." : song.chordName(c, 0));
    const lines = [
      "{title: " + directiveText(d.title) + "}",
      "{key: " + song.keyName(0) + "}",
      "{tempo: " + Math.round(d.bpm) + "}",
      "{time: " + d.beats_per_bar + "/4}",
      "{comment: chords found by woodshed from " + directiveText(d.file) + "; check the ones marked ?}",
      "",
    ];
    for (const group of d.groups) {
      lines.push('{start_of_grid label="' + directiveText(group.label).replace(/"/g, "'") + '"}');
      const bars = group.occurrences[0].map((u) => {
        const cells = [];
        for (const c of d.bars[u].chords) {
          cells.push(name(c) + (c.doubt ? "?" : ""));
          for (let i = 1; i < c.beats; i++) cells.push(".");
        }
        return cells.join(" ");
      });
      const times = group.occurrences.length;
      lines.push(times > 1 ? "|: " + bars.join(" | ") + " :|" + (times > 2 ? " x" + times : "") : "| " + bars.join(" | ") + " |");
      lines.push("{end_of_grid}");
    }
    return lines.join("\n") + "\n";
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

  W.exports = { data, chordpro, lab, json, save };
})();
