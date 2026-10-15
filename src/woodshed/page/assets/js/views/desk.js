// The desk: one panel per instrument (guitar shapes, bass line, keys, drum groove, voice range).
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, s: svg, $, clear, chordNode } = W;
  const I = W.instruments;

  const TITLES = { guitar: "Your guitar", bass: "Your bass", piano: "Your keys", drums: "Your drums", voice: "Your voice" };

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
    const out = svg("svg", { viewBox: "0 0 96 112", role: "img", "aria-label": "Chord diagram" });
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
    const out = svg("svg", { viewBox: "0 0 " + width + " 116", width, role: "img", "aria-label": "Keyboard", "data-testid": "keyboard" });
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

  function rhythmGrid(label, shares, per, id) {
    const counts = I.counts(per);
    return h(
      "div",
      { class: "groove", id, style: { gridTemplateColumns: "56px repeat(" + counts.length + ", minmax(0, 1fr))" } },
      h("span"),
      counts.map((c, i) => h("span", { class: "ct" + (i % 4 === 0 ? " downbeat" : "") }, c)),
      ...(Array.isArray(label) ? label : [[label, shares]]).map(([name, row]) => [
        h("span", { class: "rl" }, name),
        row.map((v, i) => {
          const size = v < 0.1 ? 0 : 6 + Math.round(v * 12);
          return h(
            "span",
            { class: "cell" + (i % 4 === 0 ? " q0" : ""), "data-six": i, title: name + ", " + counts[i] + ": hit in " + Math.round(v * 100) + "% of bars" },
            size ? h("span", { class: "dot", style: { width: size + "px", height: size + "px", opacity: (0.25 + v * 0.75).toFixed(2) } }) : null,
          );
        }),
      ]),
    );
  }

  W.views = W.views || {};

  W.views.desk = function desk(app) {
    const { song, store } = app;
    const parts = song.parts;
    const curBar = (s) => Math.floor(s.beat / song.per);
    const note = (text) => h("p", { class: "desk-note" }, text);
    const noPart = (what) => note("No " + what + " track was separated for this song: run woodshed with stems to get this part.");

    function guitar(s) {
      const cur = song.chordAtBeat(s.beat);
      const chords = song.distinctChords();
      const t = s.transpose;
      const funk = s.pos === "funk" ? I.funkVoicings(chords.map((c) => ({ pc: c.pc + t, quality: c.quality }))) : null;
      const suggested = song.capoFor(t);
      const cards = chords.map((c) => {
        let shape;
        let label;
        let sub;
        if (s.pos === "open") {
          shape = I.openOrBarre(song.view.shapes, c.pc + t - s.capo, c.quality);
          label = app.nameFor(c, s.capo, s);
          sub = s.capo ? ["sounds ", chordNode(app.nameFor(c, 0, s))] : "";
        } else if (s.pos === "barre") {
          shape = I.barreShape(c.pc + t, c.quality);
          label = app.nameFor(c, 0, s);
          sub = "no capo";
        } else {
          shape = funk[c.pc + t + c.quality]; // keyed as funkVoicings builds it
          label = app.nameFor(c, 0, s);
          sub = "strings 3-2-1";
        }
        return h(
          "button",
          {
            type: "button",
            class: "shape-card" + (song.same(c, cur) ? " cur" : ""),
            "data-testid": "shape",
            "aria-label": "Hear " + app.nameFor(c, 0, s),
            onclick: () => app.hearShape(shape, s.pos === "open" ? s.capo : 0),
          },
          h("span", { class: "nm", style: { display: "block" } }, chordNode(label)),
          h("span", { class: "sub", style: { display: "block" } }, sub),
          guitarDiagram(shape),
          h("span", { class: "play-hint", style: { display: "block" } }, "▶ hear"),
        );
      });
      const tip =
        s.pos === "open"
          ? s.capo === suggested
            ? suggested ? "Capo " + s.capo + " gives open shapes for most of the song." : "Open shapes, no capo needed."
            : "Tip: capo " + suggested + " gives the easiest shapes."
          : s.pos === "funk"
            ? "Three-note shapes chosen so your hand barely moves from one chord to the next."
            : "Full barre chords, no capo, concert pitch.";
      return [
        h(
          "div",
          { class: "seg-ctl", role: "group", "aria-label": "Voicing", style: { marginBottom: "12px" } },
          [["open", s.capo ? "Open, capo " + s.capo : "Open"], ["barre", "Barre chords"], ["funk", "Funk triads"]].map(([pos, text]) =>
            h("button", { type: "button", class: s.pos === pos ? "on" : "", "data-testid": "voicing-" + pos, onclick: () => store.set({ pos }) }, text),
          ),
        ),
        h("div", { class: "shapes" }, cards),
        note(tip + " Click a shape to hear it."),
        comping(),
      ];
    }

    function comping() {
      if (!parts) return null;
      return [
        h("div", { class: "label subhead" }, "Rhythm: when the chords hit"),
        rhythmGrid("Chords", parts.comp, song.per, "compGrid"),
        h("p", { class: "src-note" }, "From the isolated keys and guitar track: chords on " + I.hitsText(parts.comp, song.per) + ". Bigger dot: hit in more bars."),
      ];
    }

    function bass(s) {
      if (!parts) return noPart("bass");
      const u = curBar(s);
      const line = (parts.bass[u] || []).map((e) => (e ? { midi: e[0] + s.transpose, confidence: e[1] } : null));
      const frets = I.bassFrets(line);
      const counts = I.counts(song.per);
      const names = ["G", "D", "A", "E"];
      const cell = (f, k) => (f && f.string === k ? ("-" + f.fret + "--").slice(0, 3) : "---");
      // Two beats a line: the tab never scrolls sideways, on a phone or in the side panel.
      const lines = [];
      for (let i = 0; i < frets.length; i += 8) {
        const end = i + 8 >= frets.length ? "|" : "";
        const head = "  " + counts.slice(i, i + 8).map((c) => (c + "  ").slice(0, 3)).join("");
        const rows = names.map((n, k) => n + "|" + frets.slice(i, i + 8).map((f) => cell(f, k)).join("") + end);
        lines.push(h("span", { class: "cnt" }, (i ? "\n\n" : "") + head), "\n" + rows.join("\n"));
      }
      const heard = [...new Set(line.filter(Boolean).map((n) => song.noteName(n.midi - s.transpose, s.transpose)))];
      return [
        h("div", { class: "label", style: { marginBottom: "6px" } }, "Bar " + (u + 1) + ", the line as played ", h("span", { class: "exp" }, "experimental")),
        h("div", { class: "tab", "data-testid": "bass-tab" }, lines),
        h("div", { class: "chips-row" }, h("span", { class: "hint" }, "Notes in this bar:"), heard.map((n) => h("span", { class: "pc-chip" }, chordNode(n)))),
        h(
          "div",
          { class: "hear-row" },
          h("button", { type: "button", class: "btn", "data-testid": "hear-riff", onclick: () => app.hearRiff(u) }, "▶ Hear bar " + (u + 1)),
          u + 1 < song.bars.length ? h("button", { type: "button", class: "btn", onclick: () => app.hearRiff(u + 1) }, "▶ Hear bar " + (u + 2)) : null,
        ),
        note("Transcribed from the isolated bass track. Faint notes are less certain."),
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
          h("div", { class: "hint" }, "Now: ", h("b", null, chordNode(app.nameFor(cur, 0, s))), " in root position. Orange outline: the next chord, ", up ? chordNode(app.nameFor(up, 0, s)) : "none", "."),
          h(
            "div",
            { class: "hear-row" },
            cur.pc >= 0 ? h("button", { type: "button", class: "btn", "data-testid": "hear-keys", onclick: () => app.hearKeys(cur) }, "▶ Hear ", chordNode(app.nameFor(cur, 0, s))) : null,
            up ? h("button", { type: "button", class: "btn", onclick: () => app.hearKeys(up) }, "▶ Hear ", chordNode(app.nameFor(up, 0, s))) : null,
            cur.pc >= 0 ? h("button", { type: "button", class: "btn", onclick: () => app.hearArpeggio(cur) }, "Note by note") : null,
          ),
        ),
      ];
      if (parts) {
        const pcs = parts.voicings[curBar(s)] || [];
        out.push(
          h("div", { class: "label subhead" }, "On the record, this bar"),
          h(
            "div",
            { class: "chips-row" },
            pcs.map((pc) => h("span", { class: "pc-chip" }, chordNode(song.noteName(pc, s.transpose)))),
            cur.pc >= 0 ? [h("span", { class: "hint" }, "over"), h("span", { class: "pc-chip bassnote" }, chordNode(song.noteName(cur.pc, s.transpose)))] : null,
            pcs.length ? h("button", { type: "button", class: "btn", "data-testid": "hear-voicing", style: { marginLeft: "4px" }, onclick: () => app.hearVoicing(curBar(s)) }, "▶ Hear it") : null,
          ),
          h("p", { class: "src-note" }, "Upper notes heard on the isolated keys and guitar track. The keyboard often leaves the root to the bass."),
          comping(),
        );
      }
      return out;
    }

    function drums() {
      if (!parts) return noPart("drum");
      const g = parts.groove;
      if (!g) return note("No steady groove was found on the drum track (too few bars with drums).");
      const pct = (x) => Math.round(x * 100) + "%";
      return [
        h("div", { class: "label", style: { marginBottom: "6px" } }, "Main groove ", h("span", { class: "exp" }, "experimental")),
        song.per === 4 ? h("div", { class: "staffbox", id: "drumStaff", "data-testid": "drum-staff", "aria-label": "Drum notation of the main groove" }) : null,
        rhythmGrid([["Hi-hat", g.hat], ["Snare", g.snare], ["Kick", g.kick]], null, song.per, "grooveGrid"),
        h("div", { class: "legend-row" }, h("span", null, "Bigger dot: hit in more bars"), song.per === 4 ? h("span", null, "Notation: hits played in more than half the bars") : null),
        h(
          "div",
          { class: "hear-row" },
          h("button", { type: "button", class: "btn", "data-testid": "hear-groove", onclick: () => app.hearGroove() }, "▶ Hear the groove"),
          h("button", { type: "button", class: "btn", "data-testid": "groove-with-band", onclick: () => app.playBars(Math.floor(store.get().beat / song.per), 2) }, "▶ Groove with the band"),
        ),
        note(
          "Read from the drum track, isolated on this computer, over " + g.bars + " bars. Kick on " + I.hitsText(g.kick, song.per) + ", snare on " + I.hitsText(g.snare, song.per) +
            ". Bars matching the main groove: kick " + pct(g.agreement.kick) + ", snare " + pct(g.agreement.snare) + ", hi-hat " + pct(g.agreement.hat) + ". Fills are not detected yet.",
        ),
      ];
    }

    function voice(s) {
      if (!parts) return noPart("vocal");
      const vocal = parts.vocal;
      if (!vocal) return note("No singing was detected on the isolated vocal track, so there is no range to match.");
      const vt = I.VOICES.find((v) => v[0] === s.voiceType) || null;
      const name = (m) => song.noteName(m, s.transpose) + (Math.floor((m + s.transpose) / 12) - 1);
      const lo = 40;
      const hi = 86;
      const width = 520;
      const X = (m) => 10 + ((m - lo) / (hi - lo)) * (width - 20);
      const range = svg("svg", { viewBox: "0 0 " + width + " 70", role: "img", "aria-label": "Song vocal range against your voice" });
      for (let m = lo; m <= hi; m++) {
        if (m % 12 === 0) {
          range.append(svg("line", { x1: X(m), y1: 8, x2: X(m), y2: 58, stroke: "var(--line)" }));
          range.append(svg("text", { x: X(m), y: 68, "font-size": 11, "text-anchor": "middle", fill: "var(--muted)" }, "C" + (m / 12 - 1)));
        }
      }
      if (vt) {
        range.append(svg("rect", { x: X(vt[1]), y: 34, width: X(vt[2]) - X(vt[1]), height: 16, rx: 5, fill: "var(--accent-soft)", stroke: "var(--accent)" }));
        range.append(svg("text", { x: X(vt[1]) + 6, y: 46, "font-size": 11, fill: "var(--ink)" }, vt[0]));
      }
      const a = vocal.low + s.transpose;
      const b = vocal.high + s.transpose;
      range.append(svg("rect", { x: X(a), y: 12, width: X(b) - X(a), height: 16, rx: 5, fill: "var(--warn-soft)", stroke: "var(--warn)" }));
      range.append(svg("text", { x: X(a) + 6, y: 24, "font-size": 11, fill: "var(--ink)" }, "Song: " + name(vocal.low) + "–" + name(vocal.high)));
      let fit;
      if (vt) {
        const best = I.bestTranspose(vocal, vt[1], vt[2]);
        fit =
          best === s.transpose
            ? h("p", { class: "fit" }, h("b", null, "This key fits a " + vt[0].toLowerCase() + " voice."))
            : h(
                "p",
                { class: "fit" },
                "Best key for a " + vt[0].toLowerCase() + " voice: ",
                h("b", null, chordNode(song.keyName(best))),
                " (" + (best > 0 ? "+" : "") + best + " semitones). ",
                h("button", { type: "button", class: "btn", "data-testid": "fit-key", onclick: () => app.transposeTo(best) }, "Transpose the song"),
              );
      } else fit = h("p", { class: "fit" }, "Pick your voice type to see the best key.");
      return [
        h("div", { class: "label", style: { marginBottom: "6px" } }, "Your range against the song"),
        h("div", { class: "range" }, range),
        h(
          "div",
          { class: "voice-types", role: "group", "aria-label": "Your voice type" },
          I.VOICES.map((v) => h("button", { type: "button", class: "btn" + (s.voiceType === v[0] ? " on" : ""), "data-testid": "voice-" + v[0].toLowerCase(), onclick: () => store.set({ voiceType: v[0] }) }, v[0])),
        ),
        fit,
        h("p", { class: "src-note" }, "Range measured on the isolated vocal track: " + name(vocal.low) + " to " + name(vocal.high) + " for most of the sung notes. Transposing moves the chart and the shapes together."),
      ];
    }

    function render(s) {
      $("deskTitle").textContent = TITLES[s.inst];
      $("capoWrap").hidden = $("capoStepper").hidden = s.inst !== "guitar";
      const body = { guitar, bass, piano: keys, drums, voice }[s.inst](s);
      clear($("desk"), body);
      if (s.inst === "drums") app.drawDrumStaff();
      clear($("trVal"), chordNode(song.keyName(s.transpose)), s.transpose ? " (" + (s.transpose > 0 ? "+" : "") + s.transpose + ")" : "");
      $("capoVal").textContent = String(s.capo);
    }

    let lastBar = -1;
    let lastChord = "";
    store.on((s, changed) => {
      const u = curBar(s);
      const c = song.chordAtBeat(s.beat);
      const chordKey = c.pc + c.quality;
      const full = ["transpose", "capo", "inst", "pos", "voiceType", "corrections"].some((k) => changed.has(k));
      const perBar = s.inst === "bass" || s.inst === "piano";
      const perChord = s.inst === "guitar" || s.inst === "piano";
      if (full || (perBar && u !== lastBar) || (perChord && chordKey !== lastChord)) render(s);
      lastBar = u;
      lastChord = chordKey;
    });

    return { render };
  };
})();
