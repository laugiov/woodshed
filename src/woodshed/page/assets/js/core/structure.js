// Lines of the chart from the song's parts, as woodshed.structure._group: four bars inside each part,
// a part always starting a line, identical consecutive lines of one part shown once with a repeat.
// The analysis writes its lines into the page; the page draws them again when the band edits the
// parts or the chords (tests/page/test_regroup_page.py checks both agree).
(function () {
  "use strict";
  const W = window.Woodshed;
  const LINE_BARS = 4;
  const PRIMES = ["′", "″", "‴"];
  const MIN_VARIANT_BARS = 3;

  // 0 -> A, 25 -> Z, 26 -> AA, as structure.section_letter.
  function sectionLetter(n) {
    let out = "";
    n += 1;
    while (n) {
      const r = (n - 1) % 26;
      n = Math.floor((n - 1) / 26);
      out = String.fromCharCode(65 + r) + out;
    }
    return out;
  }

  // structure.line_starts.
  function lineStarts(nBars, partStarts) {
    const edges = [...new Set([0, ...partStarts.filter((s) => s > 0 && s < nBars)])].sort((a, b) => a - b);
    const out = [];
    edges.forEach((a, k) => {
      const b = k + 1 < edges.length ? edges[k + 1] : nBars;
      for (let s = a; s < b; s += LINE_BARS) out.push(s);
    });
    return out;
  }

  // A bar's chords as structure.Bar.signature, the slash bass too.
  const barSig = (bar) => bar.chords.map((c) => W.chords.key(c) + "x" + c.beats).join(",");

  // structure._Lettering: a line one bar away from a known one keeps its letter with a prime.
  function lettering() {
    const families = [];
    const known = new Map();
    const differences = (fam, sig) => sig.reduce((n, s, i) => n + (i < fam.sig.length && fam.sig[i] !== s ? 1 : 0), 0);
    function ofFamily(sig) {
      const candidates = families.filter((f) => sig.length <= f.sig.length);
      for (const fam of candidates) if (differences(fam, sig) === 0) return [fam.letter, fam.letter];
      if (sig.length < MIN_VARIANT_BARS) return null;
      for (const fam of candidates) {
        if (differences(fam, sig) === 1) {
          fam.variants += 1;
          const mark = fam.variants <= PRIMES.length ? PRIMES[fam.variants - 1] : "(" + fam.variants + ")";
          return [fam.letter + mark, fam.letter];
        }
      }
      return null;
    }
    return (sig) => {
      const id = sig.join("|");
      if (!known.has(id)) {
        let found = ofFamily(sig);
        if (!found) {
          const letter = sectionLetter(families.length);
          families.push({ sig, letter, variants: 0 });
          found = [letter, letter];
        }
        known.set(id, found);
      }
      return known.get(id);
    };
  }

  // {groups: [{label, family, occurrences}], fields: [{group, occurrence, column}] per bar}.
  function regroup(bars, parts) {
    const letterFor = lettering();
    const starts = new Set(parts.map((p) => p.start));
    const firsts = lineStarts(bars.length, [...starts]);
    const groups = [];
    let previous = null;
    firsts.forEach((start, k) => {
      const end = Math.min(start + LINE_BARS, k + 1 < firsts.length ? firsts[k + 1] : bars.length);
      const line = [];
      for (let i = start; i < end; i++) line.push(i);
      const sig = line.map((i) => barSig(bars[i]));
      if (groups.length && previous !== null && sig.join("|") === previous && !starts.has(start)) {
        groups[groups.length - 1].occurrences.push(line);
      } else {
        const [label, family] = letterFor(sig);
        groups.push({ label, family, occurrences: [line] });
      }
      previous = sig.join("|");
    });
    const fields = bars.map(() => null);
    groups.forEach((g, gi) => g.occurrences.forEach((line, o) => line.forEach((i, c) => (fields[i] = { group: gi, occurrence: o, column: c }))));
    return { groups, fields };
  }

  W.structure = { regroup, lineStarts, sectionLetter };
})();
