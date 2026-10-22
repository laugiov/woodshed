// The desk: one panel per instrument (guitar shapes, bass line, keys, drum groove, voice range).
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, s: svg, $, clear, chordNode } = W;
  const I = W.instruments;

  const TITLES = () => ({ guitar: W.t("Your guitar"), bass: W.t("Your bass"), piano: W.t("Your keys"), drums: W.t("Your drums"), voice: W.t("Your voice") });

  function guitarDiagram(shape) {
    const played = shape.frets.filter((f) => f > 0);
    const max = played.length ? Math.max(...played) : 1;
    const min = played.length ? Math.min(...played) : 1;
    const base = max <= 4 ? 1 : min;
    const x0 = 16;
    const y0 = 22;
    const sw = 13;
    const fh = 17;
    const rows = 5;
    const out = svg("svg", { viewBox: "0 0 96 112", role: "img", "aria-label": W.t("Chord diagram") });
    for (let i = 0; i < 6; i++) out.append(svg("line", { x1: x0 + i * sw, y1: y0, x2: x0 + i * sw, y2: y0 + rows * fh, stroke: "var(--muted)", "stroke-width": 1 }));
    for (let j = 0; j <= rows; j++) {
      out.append(svg("line", { x1: x0, y1: y0 + j * fh, x2: x0 + 5 * sw, y2: y0 + j * fh, stroke: "var(--muted)", "stroke-width": j === 0 && base === 1 ? 4 : 1 }));
    }
    if (base > 1) out.append(svg("text", { x: x0 + 5 * sw + 5, y: y0 + fh * 0.7, "font-size": 10, fill: "var(--muted)" }, base + "fr"));
    if (shape.barre) {
      const by = y0 + (shape.barre - base + 0.5) * fh;
      const bx1 = x0 + (shape.from || 0) * sw;
      const bx2 = x0 + 5 * sw;
      out.append(svg("rect", { x: bx1 - 5, y: by - 5, width: bx2 - bx1 + 10, height: 10, rx: 5, fill: "var(--ink)" }));
    }
    shape.frets.forEach((f, i) => {
      const x = x0 + i * sw;
      if (f < 0) out.append(svg("text", { x, y: y0 - 7, "text-anchor": "middle", "font-size": 10, fill: "var(--muted)" }, "×"));
      else if (f === 0) out.append(svg("circle", { cx: x, cy: y0 - 10, r: 3.5, fill: "none", stroke: "var(--muted)", "stroke-width": 1.2 }));
      else if (!(shape.barre && f === shape.barre)) out.append(svg("circle", { cx: x, cy: y0 + (f - base + 0.5) * fh, r: 5.5, fill: "var(--accent)" }));
    });
    return out;
  }

  function pianoDiagram(on, ghost) {
    const whites = [0, 2, 4, 5, 7, 9, 11];
    const width = 14 * 22 + 2;
    const out = svg("svg", { viewBox: "0 0 " + width + " 116", width, role: "img", "aria-label": W.t("Keyboard"), "data-testid": "keyboard" });
    let wi = 0;
    const blacks = [];
    for (let m = 48; m < 72; m++) {
      if (whites.includes(m % 12)) {
        const g = ghost.has(m) && !on.has(m);
        out.append(svg("rect", { x: 1 + wi * 22, y: 1, width: 21, height: 112, rx: 3, fill: on.has(m) ? "var(--accent)" : "var(--sheet)", stroke: g ? "var(--warn)" : "var(--muted)", "stroke-width": g ? 2.5 : 1, "data-midi": m }));
        wi++;
      } else blacks.push([m, wi]);
    }
    for (const [m, at] of blacks) {
      const g = ghost.has(m) && !on.has(m);
      out.append(svg("rect", { x: 1 + at * 22 - 7, y: 1, width: 14, height: 70, rx: 2, fill: on.has(m) ? "var(--accent)" : "var(--ink)", stroke: g ? "var(--warn)" : "none", "stroke-width": 2.5, "data-midi": m }));
    }
    return out;
  }

  // `played`: the slots the drums' rule keeps, drawn solid; the others faint and small, or not at
  // all when `onlyPlayed` (a read with no clear groove: nothing to make a drummer see one).
  function rhythmGrid(label, shares, per, id, onlyPlayed) {
    const counts = I.counts(per);
    return h(
      "div",
      { class: "groove", id, style: { gridTemplateColumns: "56px repeat(" + counts.length + ", minmax(0, 1fr))" } },
      h("span"),
      counts.map((c, i) => h("span", { class: "ct" + (i % 4 === 0 ? " downbeat" : "") }, c)),
      ...(Array.isArray(label) ? label : [[label, shares, null]]).map(([name, row, on]) => [
        h("span", { class: "rl" }, name),
        row.map((v, i) => {
          const hit = on ? on[i] : null;
          const size = v < 0.1 || (onlyPlayed && hit === false) ? 0 : hit === false ? 4 + Math.round(v * 6) : 6 + Math.round(v * 12);
          const opacity = hit === false ? 0.3 : 0.25 + v * 0.75;
          return h(
            "span",
            { class: "cell" + (i % 4 === 0 ? " q0" : ""), "data-six": i, title: W.t("{name}, {count}: hit in {pct}% of bars", { name, count: counts[i], pct: Math.round(v * 100) }) },
            size ? h("span", { class: "dot" + (hit ? " on" : ""), style: { width: size + "px", height: size + "px", opacity: opacity.toFixed(2) } }) : null,
          );
        }),
      ]),
    );
  }

  W.views = W.views || {};

  W.views.desk = function desk(app) {
    const { song, store } = app;
    const parts = song.parts;
    // The shape the guitar panel draws for a chord, in the voicing and capo chosen: stage mode shows it too.
    app.shapeFor = (c, s) => {
      if (c.pc < 0) return null;
      const t = s.transpose;
      if (s.pos === "barre") return I.barreShape(c.pc + t, c.quality);
      if (s.pos === "funk") return I.funkVoicings(song.distinctChords().map((d) => ({ pc: d.pc + t, quality: d.quality })))[c.pc + t + c.quality] || null;
      return I.openOrBarre(song.view.shapes, c.pc + t - s.capo, c.quality);
    };
    app.guitarDiagram = guitarDiagram;
    const curBar = (s) => Math.floor(s.beat / song.per);
    const note = (text) => h("p", { class: "desk-note" }, text);

    function guitar(s) {
      const cur = song.chordAtBeat(s.beat);
      const chords = song.distinctChords();
      const t = s.transpose;
      const funk = s.pos === "funk" ? I.funkVoicings(chords.map((c) => ({ pc: c.pc + t, quality: c.quality }))) : null;
      const cards = chords.map((c) => {
        let shape;
        let label;
        let sub;
        if (s.pos === "open") {
          shape = I.openOrBarre(song.view.shapes, c.pc + t - s.capo, c.quality);
          label = app.nameFor(c, s.capo, s);
          sub = s.capo ? W.nodes(W.t("sounds {chord}"), { chord: chordNode(app.nameFor(c, 0, s)) }) : "";
          // No open shape for this chord here: a barre, said so.
          if (!I.tableShape(song.view.shapes, c.pc + t - s.capo, c.quality)) sub = [sub, sub ? " · " : "", h("span", { class: "barre-tag" }, W.t("barre"))];
        } else if (s.pos === "barre") {
          shape = I.barreShape(c.pc + t, c.quality);
          label = app.nameFor(c, 0, s);
          sub = W.t("no capo");
        } else {
          shape = funk[c.pc + t + c.quality]; // keyed as funkVoicings builds it
          label = app.nameFor(c, 0, s);
          sub = W.t("strings 3-2-1");
        }
        return h(
          "button",
          {
            type: "button",
            class: "shape-card" + (song.same(c, cur) ? " cur" : ""),
            "data-testid": "shape",
            "aria-label": W.t("Hear {chord}", { chord: app.nameFor(c, 0, s) }),
            onclick: () => app.hearShape(shape, s.pos === "open" ? s.capo : 0),
          },
          h("span", { class: "nm", style: { display: "block" } }, chordNode(label)),
          h("span", { class: "sub", style: { display: "block" } }, sub),
          guitarDiagram(shape),
          h("span", { class: "play-hint", style: { display: "block" } }, W.t("▶ hear")),
        );
      });
      // One line: the capo the page chooses when it transposes (theory.suggest_capo: chords weighted
      // by how long they last, a high capo only when clearly easier), with the barre chords it saves,
      // and a button to put it on.
      const barresAt = (k) => chords.filter((c) => !I.tableShape(song.view.shapes, c.pc + t - k, c.quality)).length;
      const best = song.capoFor(t);
      const counts = { [best]: barresAt(best), 0: barresAt(0) };
      let useBest = null;
      if (s.pos === "open" && s.capo !== best) {
        useBest = h("button", { type: "button", class: "btn", "data-testid": "use-best-capo", onclick: () => store.set({ capo: best }) }, best ? W.t("Use capo {n}", { n: best }) : W.t("Take the capo off"));
      }
      const tip =
        s.pos === "open"
          ? best
            ? !counts[best]
              ? W.t("Best capo: {c}, every shape open (without a capo, barre chords: {n}).", { c: best, n: counts[0] })
              : counts[best] === 1
                ? W.t("Best capo: {c}, 1 barre chord instead of {n}.", { c: best, n: counts[0] })
                : W.t("Best capo: {c}, {b} barre chords instead of {n}.", { c: best, b: counts[best], n: counts[0] })
            : !counts[0]
              ? W.t("Open shapes, no capo needed.")
              : counts[0] === 1
                ? W.t("One barre chord, and no capo makes the song clearly easier.")
                : W.t("Barre chords: {n}, and no capo makes the song clearly easier.", { n: counts[0] })
          : s.pos === "funk"
            ? W.t("Three-note shapes chosen so your hand barely moves from one chord to the next.")
            : W.t("Full barre chords, no capo, concert pitch.");
      return [
        h(
          "div",
          { class: "seg-ctl", role: "group", "aria-label": W.t("Voicing"), style: { marginBottom: "12px" } },
          [["open", s.capo ? W.t("Open, capo {n}", { n: s.capo }) : W.t("Open")], ["barre", W.t("Barre chords")], ["funk", W.t("Funk triads")]].map(([pos, text]) =>
            h("button", { type: "button", class: s.pos === pos ? "on" : "", "data-testid": "voicing-" + pos, onclick: () => store.set({ pos }) }, text),
          ),
        ),
        h("div", { class: "shapes" }, cards),
        note(W.t("{tip} Click a shape to hear it.", { tip })),
        useBest ? h("div", { class: "hear-row" }, useBest) : null,
        comping(),
      ];
    }

    function comping() {
      if (!parts) return null;
      return [
        h("div", { class: "label subhead" }, W.t("Rhythm: when the chords hit")),
        rhythmGrid(W.t("Chords"), parts.comp, song.per, "compGrid"),
        h("p", { class: "src-note" }, W.t("From the isolated keys and guitar track: chords on {hits}. Bigger dot: hit in more bars.", { hits: I.hitsText(parts.comp, song.per) })),
      ];
    }

    // The tab of one bar, two beats a line: it never scrolls sideways, on a phone or in the side panel.
    function bassTab(u, s, label) {
      const line = (parts.bass[u] || []).map((e) => (e ? { midi: e[0] + s.transpose, confidence: e[1] } : null));
      const frets = I.bassFrets(line);
      const counts = I.counts(song.per);
      const names = ["G", "D", "A", "E"];
      // A note the pitch tracker was less sure of is drawn faint, as the note under the tab says.
      const cell = (f, k) => {
        if (!f || f.string !== k) return "---";
        const text = ("-" + f.fret + "--").slice(0, 3);
        return f.faint ? h("span", { class: "lo", title: W.t("Less certain") }, text) : text;
      };
      const lines = [];
      for (let i = 0; i < frets.length; i += 8) {
        const end = i + 8 >= frets.length ? "|" : "";
        const head = "  " + counts.slice(i, i + 8).map((c) => (c + "  ").slice(0, 3)).join("");
        lines.push(h("span", { class: "cnt" }, (i ? "\n\n" : "") + head));
        names.forEach((n, k) => lines.push("\n" + n + "|", frets.slice(i, i + 8).map((f) => cell(f, k)), end));
      }
      const silent = !line.some(Boolean);
      return [
        label ? h("div", { class: "tab-bar" + (u === curBar(s) ? " cur" : "") }, label) : null,
        silent ? h("p", { class: "hint", "data-testid": "bass-silent" }, W.t("No bass heard in this bar.")) : null,
        h("div", { class: "tab", "data-testid": "bass-tab", translate: "no" }, lines),
      ];
    }

    function bass(s) {
      if (!parts) return note(W.t("No bass track was separated for this song: run woodshed with stems to get this part."));
      const u = curBar(s);
      const legend = note(W.t("Transcribed from the isolated bass track, at the pitch heard: onsets only, a note lasts until the next one. Faint notes are less certain."));
      // A loop: the tab of every looped bar (up to sixteen: a whole chorus), the passage on one screen.
      if (s.loopOn && s.loop) {
        const [a, b] = s.loop;
        const last = Math.min(b, a + 15);
        // Bars with no bass are one line, not blocks of empty tab: "Bars 1–4: no bass heard."
        const bars = [];
        let silent = [];
        const flush = () => {
          if (!silent.length) return;
          const [from, to] = [silent[0] + 1, silent[silent.length - 1] + 1];
          bars.push(h("p", { class: "hint", "data-testid": "bass-silent" }, from === to ? W.t("Bar {n}: no bass heard.", { n: from }) : W.t("Bars {from}–{to}: no bass heard.", { from, to })));
          silent = [];
        };
        for (let v = a; v <= last; v++) {
          if (!(parts.bass[v] || []).some(Boolean)) {
            silent.push(v);
            continue;
          }
          flush();
          bars.push(...bassTab(v, s, W.t("Bar {n}", { n: v + 1 })));
        }
        flush();
        return [
          h("div", { class: "label", style: { marginBottom: "6px" } }, W.nodes(last < b ? W.t("Bars {from}–{to}, the first sixteen of the loop {tag}", { from: a + 1, to: last + 1 }) : W.t("Bars {from}–{to}, looped {tag}", { from: a + 1, to: last + 1 }), { tag: h("span", { class: "exp" }, W.t("experimental")) })),
          bars,
          h("div", { class: "hear-row" }, h("button", { type: "button", class: "btn", "data-testid": "hear-riff", onclick: () => app.hearRiff(u) }, W.t("▶ Hear bar {n}", { n: u + 1 }))),
          legend,
        ];
      }
      const line = (parts.bass[u] || []).filter(Boolean);
      const heard = [...new Set(line.map((e) => song.noteName(e[0], s.transpose)))];
      return [
        h("div", { class: "label", style: { marginBottom: "6px" } }, W.nodes(W.t("Bar {n}, the line as played {tag}", { n: u + 1 }), { tag: h("span", { class: "exp" }, W.t("experimental")) })),
        bassTab(u, s, null),
        h("div", { class: "chips-row" }, h("span", { class: "hint" }, W.t("Notes in this bar:")), heard.map((n) => h("span", { class: "pc-chip" }, chordNode(n)))),
        h(
          "div",
          { class: "hear-row" },
          h("button", { type: "button", class: "btn", "data-testid": "hear-riff", onclick: () => app.hearRiff(u) }, W.t("▶ Hear bar {n}", { n: u + 1 })),
          u + 1 < song.bars.length ? h("button", { type: "button", class: "btn", onclick: () => app.hearRiff(u + 1) }, W.t("▶ Hear bar {n}", { n: u + 2 })) : null,
        ),
        legend,
      ];
    }

    function keys(s) {
      const cur = song.chordAtBeat(s.beat);
      const up = song.upcoming(s.beat, 1)[0];
      const on = new Set(cur.pc >= 0 ? I.keysMidi(cur.pc + s.transpose, cur.quality) : []);
      const ghost = new Set(up ? I.keysMidi(up.pc + s.transpose, up.quality) : []);
      const out = [
        h(
          "div",
          { class: "piano-wrap" },
          pianoDiagram(on, ghost),
          h(
            "div",
            { class: "hint" },
            W.nodes(W.t("Now: {chord} in root position. Orange outline: the next chord, {next}."), {
              chord: h("b", null, chordNode(app.nameFor(cur, 0, s))),
              next: up ? chordNode(app.nameFor(up, 0, s)) : W.t("none"),
            }),
          ),
          h(
            "div",
            { class: "hear-row" },
            cur.pc >= 0 ? h("button", { type: "button", class: "btn", "data-testid": "hear-keys", onclick: () => app.hearKeys(cur) }, W.nodes(W.t("▶ Hear {chord}"), { chord: chordNode(app.nameFor(cur, 0, s)) })) : null,
            up ? h("button", { type: "button", class: "btn", onclick: () => app.hearKeys(up) }, W.nodes(W.t("▶ Hear {chord}"), { chord: chordNode(app.nameFor(up, 0, s)) })) : null,
            cur.pc >= 0 ? h("button", { type: "button", class: "btn", onclick: () => app.hearArpeggio(cur) }, W.t("Note by note")) : null,
          ),
        ),
      ];
      if (parts) {
        const pcs = parts.voicings[curBar(s)] || [];
        out.push(
          h("div", { class: "label subhead" }, W.t("On the record, this bar")),
          h(
            "div",
            { class: "chips-row" },
            pcs.map((pc) => h("span", { class: "pc-chip" }, chordNode(song.noteName(pc, s.transpose)))),
            cur.pc >= 0 ? [h("span", { class: "hint" }, W.t("over")), h("span", { class: "pc-chip bassnote" }, chordNode(song.noteName(cur.pc, s.transpose)))] : null,
            pcs.length ? h("button", { type: "button", class: "btn", "data-testid": "hear-voicing", style: { marginLeft: "4px" }, onclick: () => app.hearVoicing(curBar(s)) }, W.t("▶ Hear it")) : null,
          ),
          h("p", { class: "src-note" }, W.t("Upper notes heard on the isolated keys and guitar track. The keyboard often leaves the root to the bass.")),
          comping(),
        );
      }
      return out;
    }

    function drums() {
      if (!parts) return note(W.t("No drum track was separated for this song: run woodshed with stems to get this part."));
      const g = parts.groove;
      if (!g) return note(W.t("No steady groove was found on the drum track (too few bars with drums)."));
      const pct = (x) => W.t("{n}%", { n: Math.round(x * 100) });
      const hits = I.grooveHits(g);
      return [
        h("div", { class: "label", style: { marginBottom: "6px" } }, W.nodes(W.t("Main groove {tag}"), { tag: h("span", { class: "exp" }, W.t("experimental")) })),
        song.per === 4 && hits.clear ? h("div", { class: "staffbox", id: "drumStaff", "data-testid": "drum-staff", "aria-label": W.t("Drum notation of the main groove") }) : null,
        rhythmGrid([[W.t("Hi-hat"), g.hat, hits.hat], [W.t("Snare"), g.snare, hits.snare], [W.t("Kick"), g.kick, hits.kick]], null, song.per, "grooveGrid", !hits.clear),
        h("div", { class: "legend-row" }, h("span", null, hits.clear ? W.t("Solid dot: played in more than half the bars; faint: now and then") : W.t("Solid dot: played in more than half the bars")), song.per === 4 && hits.clear ? h("span", null, W.t("Notation: hits played in more than half the bars")) : null),
        h(
          "div",
          { class: "hear-row" },
          h("button", { type: "button", class: "btn", "data-testid": "hear-groove", onclick: () => app.hearGroove() }, W.t("▶ Hear the groove")),
          h("button", { type: "button", class: "btn", "data-testid": "groove-with-band", onclick: () => app.playBars(Math.floor(store.get().beat / song.per), 2) }, W.t("▶ Groove with the band")),
        ),
        note(grooveText(g, pct)),
      ];
    }

    // One rule for the text, the notation and the groove heard: a hit played in more than half the
    // bars. What no bar mostly plays is said, not invented; an agreement only for what is played.
    function grooveText(g, pct) {
      const hits = I.grooveHits(g);
      const said = [W.t("Read from the drum track, isolated on this computer, over the {bars} bars of {total} where the drums play.", { bars: g.bars, total: song.bars.length })];
      const [kick, snare, hat] = ["kick", "snare", "hat"].map((k) => I.playedText(hits[k], song.per));
      if (!hits.clear) {
        // A steady hi-hat over no steady kick nor snare: said as it is, not as "no groove at all".
        said.push(hat
          ? W.t("No kick or snare groove: neither comes back in most bars. Hi-hat on {hits}. Trust your ears for the rest.", { hits: hat })
          : W.t("No clear groove: no kick nor snare comes back in most bars, so none is written down. Trust your ears here."));
        return said.join(" ");
      }
      said.push(kick ? W.t("Kick on {hits}.", { hits: kick }) : W.t("No kick in more than half the bars."));
      said.push(snare ? W.t("Snare on {hits}.", { hits: snare }) : W.t("No snare in more than half the bars."));
      if (hat) said.push(W.t("Hi-hat on {hits}.", { hits: hat }));
      const agree = [kick ? W.t("kick {share}", { share: pct(g.agreement.kick) }) : null, snare ? W.t("snare {share}", { share: pct(g.agreement.snare) }) : null, hat ? W.t("hi-hat {share}", { share: pct(g.agreement.hat) }) : null].filter(Boolean);
      if (agree.length) said.push(W.t("Bars matching the main groove: {list}.", { list: agree.join(", ") }));
      said.push(W.t("Fills are not detected yet."));
      return said.join(" ");
    }

    function voice(s) {
      if (!parts) return note(W.t("No vocal track was separated for this song: run woodshed with stems to get this part."));
      const vocal = parts.vocal;
      if (!vocal) return note(W.t("No singing was detected on the isolated vocal track, so there is no range to match."));
      const vt = I.VOICES.find((v) => v[0] === s.voiceType) || null;
      const name = (m) => song.noteName(m, s.transpose) + (Math.floor((m + s.transpose) / 12) - 1);
      const lo = 40;
      const hi = 86;
      const width = 520;
      const X = (m) => 10 + ((m - lo) / (hi - lo)) * (width - 20);
      const range = svg("svg", { viewBox: "0 0 " + width + " 70", role: "img", "aria-label": W.t("Song vocal range against your voice") });
      for (let m = lo; m <= hi; m++) {
        if (m % 12 === 0) {
          range.append(svg("line", { x1: X(m), y1: 8, x2: X(m), y2: 58, stroke: "var(--line)" }));
          range.append(svg("text", { x: X(m), y: 68, "font-size": 11, "text-anchor": "middle", fill: "var(--muted)" }, "C" + (m / 12 - 1)));
        }
      }
      if (vt) {
        range.append(svg("rect", { x: X(vt[1]), y: 34, width: X(vt[2]) - X(vt[1]), height: 16, rx: 5, fill: "var(--accent-soft)", stroke: "var(--accent)" }));
        range.append(svg("text", { x: X(vt[1]) + 6, y: 46, "font-size": 11, fill: "var(--ink)" }, W.t(vt[0])));
      }
      const a = vocal.low + s.transpose;
      const b = vocal.high + s.transpose;
      range.append(svg("rect", { x: X(a), y: 12, width: X(b) - X(a), height: 16, rx: 5, fill: "var(--warn-soft)", stroke: "var(--warn)" }));
      range.append(svg("text", { x: X(a) + 6, y: 24, "font-size": 11, fill: "var(--ink)" }, W.t("Song: {low}–{high}", { low: name(vocal.low), high: name(vocal.high) })));
      let fit;
      if (vt) {
        const best = I.bestTranspose(vocal, vt[1], vt[2]);
        const voiceName = W.t(vt[0]).toLowerCase(); // I.VOICES: Bass, Baritone, Tenor, Alto, Mezzo, Soprano
        fit =
          best === s.transpose
            ? h("p", { class: "fit" }, h("b", null, W.t("This key fits a {voice} voice.", { voice: voiceName })))
            : h(
                "p",
                { class: "fit" },
                W.nodes(W.t("Best key for a {voice} voice: {key} ({n} semitones).", { voice: voiceName, n: (best > 0 ? "+" : "") + best }), {
                  key: h("b", null, chordNode(song.keyName(best))),
                }),
                " ",
                h("button", { type: "button", class: "btn", "data-testid": "fit-key", onclick: () => app.transposeTo(best) }, W.t("Transpose to {key} ({n})", { key: W.prettyText(song.keyName(best)), n: (best > 0 ? "+" : "") + best })),
              );
      } else fit = h("p", { class: "fit" }, W.t("Pick your voice type to see the best key."));
      return [
        h("div", { class: "label", style: { marginBottom: "6px" } }, W.t("Your range against the song")),
        h("div", { class: "range" }, range),
        h(
          "div",
          { class: "voice-types", role: "group", "aria-label": W.t("Your voice type") },
          I.VOICES.map((v) => h("button", { type: "button", class: "btn" + (s.voiceType === v[0] ? " on" : ""), "data-testid": "voice-" + v[0].toLowerCase(), onclick: () => store.set({ voiceType: v[0] }) }, W.t(v[0]))),
        ),
        fit,
        h("p", { class: "src-note" }, W.t("Range measured on the isolated vocal track: {low} to {high} for most of the sung notes. Transposing moves the chart and the shapes together.", { low: name(vocal.low), high: name(vocal.high) })),
      ];
    }

    function render(s) {
      $("deskTitle").textContent = TITLES()[s.inst];
      $("capoWrap").hidden = $("capoStepper").hidden = s.inst !== "guitar";
      const body = { guitar, bass, piano: keys, drums, voice }[s.inst](s);
      clear($("desk"), body);
      renderDockShapes(s);
      if (s.inst === "drums") app.drawDrumStaff();
      clear($("trVal"), chordNode(song.keyName(s.transpose)), s.transpose ? " (" + (s.transpose > 0 ? "+" : "") + s.transpose + ")" : "");
      $("capoVal").textContent = String(s.capo);
    }

    let lastBar = -1;
    let lastChord = "";
    // A tablet or a phone puts the guitar panel under the chart: the shapes of the chord now and the
    // next one ride above the player instead, in sight while the page follows the song (CSS shows
    // them on single-column layouts only; stage mode has its own).
    let dockShown = "";
    function renderDockShapes(s) {
      const box = $("dockShapes");
      const c = song.chordAtBeat(s.beat);
      const next = song.upcoming(s.beat, 1)[0];
      const shift = s.pos === "open" ? s.capo : 0;
      const shows = s.inst === "guitar" && !s.stage ? [c, next].map((x) => (x && x.pc >= 0 ? x.pc + x.quality : "")).join("|") + "|" + [s.pos, s.capo, s.transpose, s.corrections].join("|") : "";
      if (shows === dockShown) return;
      dockShown = shows;
      const cards = shows
        ? [[c, ""], [next, "next"]].filter(([x]) => x && x.pc >= 0).map(([x, cls]) => {
            const shape = app.shapeFor(x, s);
            return shape ? h("span", { class: "dshape " + cls }, app.guitarDiagram(shape), h("b", null, chordNode(app.nameFor(x, shift, s)))) : null;
          }).filter(Boolean)
        : [];
      // The shapes are named as fingered: with a capo, the strip says it, as the guitar panel does.
      clear(box, shift && cards.length ? h("span", { class: "dcapo" }, W.t("Capo {n}", { n: shift })) : null, cards);
      box.hidden = !shows;
      box.classList.toggle("empty", !cards.length); // no chord now nor next: the strip keeps its height
    }

    const DOCK_KEYS = ["beat", "inst", "stage", "pos", "capo", "transpose", "corrections"];
    store.on((s, changed) => {
      if (DOCK_KEYS.some((k) => changed.has(k))) renderDockShapes(s);
      const u = curBar(s);
      const c = song.chordAtBeat(s.beat);
      const chordKey = c.pc + c.quality;
      const full = ["transpose", "capo", "inst", "pos", "voiceType", "corrections"].some((k) => changed.has(k)) || (s.inst === "bass" && (changed.has("loop") || changed.has("loopOn")));
      const perBar = s.inst === "bass" || s.inst === "piano";
      const perChord = s.inst === "guitar" || s.inst === "piano";
      if (full || (perBar && u !== lastBar) || (perChord && chordKey !== lastChord)) render(s);
      lastBar = u;
      lastChord = chordKey;
    });

    return { render };
  };
})();
