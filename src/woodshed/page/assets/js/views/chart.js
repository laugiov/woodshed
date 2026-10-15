// The chart: the chord now and next, the bars in lines of four with repeats, the harmony panel.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, chordNode, fmt } = W;

  W.views = W.views || {};

  W.views.chart = function chart(app) {
    const { song, store } = app;
    const bar = (u) => song.bars[u];
    const curBar = (s) => Math.floor(s.beat / song.per);

    // The occurrence of line g shown on screen: the one playing, else the first.
    function shownOccurrence(g, s) {
      const b = bar(curBar(s));
      return b.group === g ? b.occurrence : 0;
    }
    const barShown = (g, col, s) => {
      const occ = song.song.groups[g].occurrences[shownOccurrence(g, s)];
      return occ[Math.min(col, occ.length - 1)];
    };

    function chordEl(c, small, ref, s) {
      const shapes = app.showShapes(s);
      const name = app.nameFor(c, shapes ? s.capo : 0, s);
      const main = chordNode(name);
      // A timing doubt (the chord is clear) stays readable as a plain chord, still open to a check.
      const timing = c.doubt && c.doubt.kind === "timing";
      const inner = c.doubt && !c.fixed
        ? h(
            "button",
            { type: "button", class: "doubt" + (timing ? " timing" : ""), "data-ref": ref, "data-testid": "doubt", "data-kind": c.doubt.kind, title: timing ? "Placement to check by ear" : "Check by ear" },
            main,
            timing ? null : h("sup", null, "?"),
          )
        : [main, c.fixed ? h("span", { class: "fixed-dot", title: "Your correction" }) : null];
      return h(
        "span",
        { class: "ch" + (small ? " small" : "") },
        inner,
        shapes ? chordNode(app.nameFor(c, 0, s), "shape") : null,
      );
    }

    function barContent(b, u, s) {
      const chords = b.chords;
      if (chords.length === 1) return [chordEl(chords[0], false, u + "_0", s)];
      const even = chords.length === 2 && chords[0].beats === song.per / 2;
      const out = [];
      chords.forEach((c, k) => {
        out.push(chordEl(c, !even, u + "_" + k, s));
        if (!even) for (let i = 1; i < c.beats; i++) out.push(h("span", { class: "slash" }, "/"));
      });
      return out;
    }

    function sectionHead(sec, k) {
      const first = bar(sec.start);
      const n = sec.end - sec.start;
      return h(
        "div",
        { class: "sec-head", "data-testid": "section", "data-section": k, "data-role": sec.role },
        h("button", { type: "button", class: "sec-name", "data-goto": sec.start, title: "Go to " + sec.name }, sec.name),
        h("span", { class: "sec-meta" }, fmt(first.start) + " · " + n + (n === 1 ? " bar" : " bars")),
        h("button", { type: "button", class: "linkbtn sec-loop", "data-loop": sec.start, "data-testid": "section-loop", title: "Loop " + sec.name }, "⟲ Loop"),
      );
    }

    function renderForm(s) {
      const list = app.sections();
      const cur = list.length ? song.sectionIndex(curBar(s), list) : -1;
      clear(
        $("form"),
        list.map((sec, k) =>
          h("button", { type: "button", class: "form-chip" + (k === cur ? " on" : "") + " r-" + sec.role, "data-goto": sec.start, "data-testid": "form-chip" }, sec.name),
        ),
      );
    }

    // A sung line on its bars: each bar kept whole (a bar line, numbered, then its words), each
    // chord above the word it lands on, a chord with no word under it over a dash, a push marked.
    // Shared with stage mode (opts.stage: no bar lines, no seeking, no checks).
    function lyricLine(row, s, opts) {
      const shift = app.showShapes(s) ? s.capo : 0;
      const mark = (p) => {
        const name = chordNode(app.nameFor(p.chord, shift, s));
        const push = p.push ? h("span", { class: "push" }, "push") : null;
        if (!opts.stage && p.chord.doubt && !p.chord.fixed) {
          const timing = p.chord.doubt.kind === "timing";
          return h(
            "button",
            { type: "button", class: "doubt" + (timing ? " timing" : ""), "data-ref": p.bar + "_" + p.index, "data-testid": "doubt", "data-kind": p.chord.doubt.kind, title: timing ? "Placement to check by ear" : "Check by ear", "aria-label": "Check this chord by ear, bar " + (p.bar + 1) },
            name,
            timing ? null : h("sup", null, "?"),
            push,
          );
        }
        return [name, p.chord.fixed && !opts.stage ? h("span", { class: "fixed-dot", title: "Your correction" }) : null, push];
      };
      const word = (item) => {
        const checks = !opts.stage && item.chords.some((p) => p.chord.doubt && !p.chord.fixed);
        // The chord names are for the eye: a screen reader reads the words, and the checks.
        const lc = h("span", { class: "lc", "aria-hidden": checks ? null : "true" }, item.chords.map((p, i) => [i ? " " : "", mark(p)]));
        if (item.kind === "gap") return h("span", { class: "lw gap" }, lc, h("span", { class: "wt", "aria-hidden": "true" }, "–"));
        const seek = !opts.stage && item.timed ? item.t.toFixed(3) : null;
        return h("span", { class: "lw" + (item.chords.length ? " has" : ""), "data-seek": seek }, lc, h("span", { class: "wt" }, item.text));
      };
      const parts = [];
      row.bars.forEach((b, i) => {
        const inner = [];
        if (!opts.stage && !b.cont) inner.push(h("span", { class: "bl", "aria-hidden": "true" }, h("i", null, String(b.bar + 1))));
        b.items.forEach((item, j) => inner.push(j ? " " : "", word(item)));
        if (i) parts.push(" ");
        parts.push(h("span", { class: "nb", "data-bar": b.cont ? null : b.bar }, inner));
      });
      const backing = row.line.backing && row.line.backing.length ? h("span", { class: "bv" }, " (" + row.line.backing.join(") (") + ")") : null;
      return h("span", { class: "lwords" }, parts, backing);
    }
    app.lyricLine = lyricLine;

    // Bars no sung line holds (an intro, a solo, an ending), as bars of the grid, four a row.
    function freeRow(list, s) {
      const cells = [];
      for (let col = 0; col < 4; col++) {
        const u = list[col];
        if (u === undefined) {
          cells.push(h("div", { class: "bar empty", "aria-hidden": "true" }));
          continue;
        }
        const b = bar(u);
        cells.push(
          h(
            "div",
            { class: "bar", "data-free": "", "data-bar": u, role: "button", tabindex: 0, "aria-label": "Bar " + (u + 1) + ": " + b.chords.map((c) => W.prettyText(app.nameFor(c, 0, s))).join(", "), "data-testid": "bar" },
            barContent(b, u, s),
            h("span", { class: "num" }, String(u + 1)),
            h("span", { class: "rn" }, b.chords.map((c) => song.roman(c)).join(" ")),
          ),
        );
      }
      return h(
        "div",
        { class: "line", "data-testid": "line" },
        h("div", { class: "line-label" }, h("span", { class: "t" }, fmt(bar(list[0]).start))),
        h("div", { class: "staff four" }, h("div", { class: "plain-bar" }), cells, h("div", { class: "plain-end" })),
      );
    }

    // The song in order: sung lines and runs of free bars, under the heads of their sections.
    function renderLyrics(s, sections) {
      const { rows, owner } = app.words.rows();
      const blocks = rows.map((r) => ({ at: r.firstBar, t: r.line.start, row: r }));
      let run = null;
      owner.forEach((li, u) => {
        const head = sections.some((sec) => sec.start === u);
        if (li >= 0) run = null;
        else if (run && run.free.length < 4 && !head) run.free.push(u);
        else blocks.push((run = { at: u, t: bar(u).start, free: [u] }));
      });
      blocks.sort((x, y) => x.t - y.t);
      const out = [];
      let shown = -1;
      for (const x of blocks) {
        const k = sections.length ? song.sectionIndex(x.at, sections) : -1;
        while (k > shown) {
          shown++;
          out.push(sectionHead(sections[shown], shown));
        }
        if (x.free) {
          out.push(freeRow(x.free, s));
          continue;
        }
        const r = x.row;
        const last = r.bars[r.bars.length - 1].bar;
        out.push(
          h(
            "div",
            { class: "lline" + (r.line.check ? " check" : ""), "data-line": r.li, "data-from": r.bars[0].bar, "data-to": last, "data-testid": "lyric-line", title: r.line.check || null },
            h("button", { type: "button", class: "t", "data-seek": r.line.start.toFixed(3), "aria-label": "Play from " + fmt(r.line.start) + ": " + r.line.text }, fmt(r.line.start)),
            lyricLine(r, s, { stage: false }),
          ),
        );
      }
      clear($("sheet"), out);
      paintLyrics(s);
    }

    function paintLyrics(s) {
      if (app.sheetMode(s) !== "lyrics") return;
      const k = app.words.lineAt(s.time).now;
      document.querySelectorAll(".lline").forEach((el) => el.classList.toggle("cur", +el.getAttribute("data-line") === k));
    }

    function renderSheet(s) {
      const sections = app.sections();
      if (app.sheetMode(s) === "lyrics") {
        renderLyrics(s, sections);
        renderForm(s);
        renderViewControl(s);
        paintBars(s);
        return;
      }
      const headAt = new Map(sections.map((sec, k) => [sec.start, [sec, k]]));
      const lines = [];
      song.song.groups.forEach((gr, g) => {
        const head = headAt.get(gr.occurrences[0][0]);
        if (head) lines.push(sectionHead(head[0], head[1]));
        lines.push(row(gr, g, s));
      });
      clear($("sheet"), lines);
      renderForm(s);
      renderViewControl(s);
      paintBars(s);
    }

    function row(gr, g, s) {
      const n = gr.occurrences.length;
      const len = gr.occurrences[0].length;
      const cells = [];
      for (let col = 0; col < 4; col++) {
        if (col >= len) {
          cells.push(h("div", { class: "bar empty", "aria-hidden": "true" }));
          continue;
        }
        const u = barShown(g, col, s);
        const b = bar(u);
        cells.push(
          h(
            "div",
            { class: "bar", "data-col": col, "data-group": g, "data-bar": u, role: "button", tabindex: 0, "aria-label": "Bar " + (u + 1) + ": " + b.chords.map((c) => W.prettyText(app.nameFor(c, 0, s))).join(", "), "data-testid": "bar" },
            barContent(b, u, s),
            h("span", { class: "num" }, String(u + 1)),
            h("span", { class: "rn" }, b.chords.map((c) => song.roman(c)).join(" ")),
          ),
        );
      }
      return h(
        "div",
        { class: "line", "data-testid": "line" },
        h("div", { class: "line-label" }, h("span", { class: "t" }, fmt(bar(gr.occurrences[0][0]).start))),
        h(
          "div",
          { class: "staff four" },
          n > 1 ? h("div", { class: "rep" }, "𝄆") : h("div", { class: "plain-bar" }),
          cells,
          n > 1 ? [h("div", { class: "rep r-end" }, "𝄇"), h("span", { class: "times", "data-testid": "repeat" }, "×" + n)] : h("div", { class: "plain-end" }),
        ),
      );
    }

    function renderViewControl(s) {
      const el = $("viewCtl");
      const mode = app.sheetMode(s);
      const sheetCtl = app.words
        ? h(
            "div",
            { class: "seg-ctl", role: "group", "aria-label": "Chart with" },
            h("button", { type: "button", class: mode === "grid" ? "on" : "", "aria-pressed": String(mode === "grid"), "data-testid": "sheet-grid", onclick: () => store.set({ sheet: "grid" }) }, "Grid"),
            h("button", { type: "button", class: mode === "lyrics" ? "on" : "", "aria-pressed": String(mode === "lyrics"), "data-testid": "sheet-lyrics", onclick: () => store.set({ sheet: "lyrics" }) }, "Lyrics"),
          )
        : null;
      if (s.inst === "guitar" && s.pos === "open" && s.capo > 0) {
        clear(
          el,
          sheetCtl,
          h(
            "div",
            { class: "seg-ctl", role: "group", "aria-label": "Chart shows" },
            h("button", { type: "button", class: s.view === "concert" ? "on" : "", onclick: () => store.set({ view: "concert" }) }, "Real chords"),
            h("button", { type: "button", class: s.view === "shapes" ? "on" : "", "data-testid": "show-shapes", onclick: () => store.set({ view: "shapes" }) }, "Shapes, capo " + s.capo),
          ),
        );
      } else clear(el, sheetCtl, h("span", { class: "hint" }, "Real chords, concert pitch"));
    }

    function barEl(u, s) {
      if (app.sheetMode(s) === "lyrics") {
        const free = document.querySelector('.bar[data-free][data-bar="' + u + '"]');
        if (free) return free;
        return [...document.querySelectorAll(".lline")].find((el) => +el.getAttribute("data-from") <= u && u <= +el.getAttribute("data-to")) || null;
      }
      const b = bar(u);
      if (barShown(b.group, b.column, s) !== u) return null;
      return document.querySelector('.bar[data-group="' + b.group + '"][data-col="' + b.column + '"]');
    }

    // The bar to paint: a bar of the grid, or in the Lyrics view a sung bar (.nb) or a free one.
    function paintEl(u, s) {
      if (app.sheetMode(s) === "lyrics") return document.querySelector('.bar[data-free][data-bar="' + u + '"], .lline .nb[data-bar="' + u + '"]');
      return barEl(u, s);
    }

    function paintBars(s) {
      document.querySelectorAll(".bar, .lline .nb").forEach((e) => {
        e.classList.remove("cur", "inloop");
        const c = e.querySelector(".cursor");
        if (c) c.remove();
      });
      const el = paintEl(curBar(s), s);
      if (el && el.classList.contains("bar")) {
        el.classList.add("cur");
        el.appendChild(h("span", { class: "cursor", style: { left: ((s.beat % song.per) * 100) / song.per + "%" } }));
      }
      if (s.loopOn && s.loop) for (let i = s.loop[0]; i <= s.loop[1]; i++) {
        const le = paintEl(i, s);
        if (le) le.classList.add("inloop");
      }
    }

    function renderNow(s) {
      const b = s.beat;
      const u = curBar(s);
      const c = song.chordAtBeat(b);
      const up = song.upcoming(b, 2);
      const shift = app.showShapes(s) ? s.capo : 0;
      clear($("bigChord"), chordNode(app.nameFor(c, shift, s)));
      $("bigRoman").textContent = song.roman(c) || "–";
      clear($("nowSub"), app.nowHint(c, s));
      clear($("nextChord"), up[0] ? chordNode(app.nameFor(up[0], shift, s)) : "end");
      clear($("thenChord"), up[1] ? chordNode(app.nameFor(up[1], shift, s)) : "");
      for (const box of [$("beats"), $("stBeats")]) {
        if (box.children.length !== song.per) clear(box, Array.from({ length: song.per }, (_, i) => h("div", { class: "beat" + (i === 0 ? " one" : "") })));
        for (let i = 0; i < box.children.length; i++) box.children[i].classList.toggle("on", i === b % song.per);
      }
      const sec = app.sectionOf(u);
      $("barInfo").textContent = sec ? sec.name : "Bar " + (u + 1);
      $("passInfo").textContent = sec ? "bar " + (u - sec.start + 1) + " of " + (sec.end - sec.start) : "of " + song.bars.length;
      renderTime(s);
    }

    function renderTime(s) {
      $("timeInfo").textContent = fmt(s.time, true);
    }

    function renderHarmony(s) {
      const key = song.keyName(s.transpose);
      const minor = key.endsWith("m");
      clear($("keyTitle"), chordNode(minor ? key.slice(0, -1) : key, "kn"), minor ? " minor" : " major");
      if (!song.song.key.known) $("keyTitle").append(h("small", { class: "hint" }, " (uncertain)"));
      const sections = song.song.harmony;
      // Harmony is summarised per family of lines (A, B); the page names them after the part
      // where each family is first heard (Verse, Chorus), the names the chart shows.
      const partOf = (family) => {
        const g = song.song.groups.find((gr) => gr.family === family);
        const sec = g && app.sectionOf(g.occurrences[0][0]);
        return sec ? sec.name.replace(/ \d+$/, "") : family;
      };
      const used = new Map();
      const labelOf = (label) => {
        const base = [...new Set(label.split("+").map(partOf))].join(" + ");
        used.set(base, (used.get(base) || 0) + 1);
        return used.get(base) > 1 ? base + " (" + used.get(base) + ")" : base;
      };
      const labels = sections.map((sec) => labelOf(sec.label));
      const prog = $("prog");
      clear(prog);
      const text = [];
      sections.forEach((sec, n) => {
        // One row per section; the chips are direct children of .prog, as the stylesheet expects.
        if (n > 0) prog.append(h("div", { style: { flexBasis: "100%", height: "0" } }));
        if (sections.length > 1) prog.append(h("b", { class: "prog-sec" }, labels[n]));
        sec.chords.forEach(([pc, q], i) => prog.append(h("span", null, chordNode(app.nameFor({ pc, quality: q }, 0, s)), h("small", null, sec.romans[i]))));
        if (sec.name) text.push((sections.length > 1 ? labels[n] + ": " : "") + sec.name.charAt(0).toUpperCase() + sec.name.slice(1) + ".");
      });
      $("progText").textContent = text.join(" ");
      const items = [];
      const seen = new Set();
      for (const d of song.doubts()) {
        if (d.chord.fixed || d.chord.doubt.kind !== "chord" || seen.has(d.chord.doubt.id)) continue;
        seen.add(d.chord.doubt.id);
        items.push(
          h(
            "li",
            null,
            h("button", { type: "button", "data-goto": d.bar }, "Bar " + (d.bar + 1)),
            h("span", null, chordNode(app.nameFor(d.chord, 0, s)), "? " + d.chord.doubt.why),
          ),
        );
      }
      clear($("checks"), items.length ? items : h("li", { class: "ok" }, h("span", null, "Nothing left to check by ear.")));
    }

    let lastPass = null;
    let shownTenth = -1;
    store.on((s, changed) => {
      const u = curBar(s);
      const pass = bar(u).group + ":" + bar(u).occurrence;
      const full = ["transpose", "capo", "inst", "pos", "view", "corrections", "sheet"].some((k) => changed.has(k));
      // The grid shows the pass playing; the lyrics show every pass, they need no new drawing.
      if (full || (pass !== lastPass && app.sheetMode(s) !== "lyrics")) renderSheet(s);
      else if (changed.has("beat") || changed.has("loop") || changed.has("loopOn")) paintBars(s);
      if (!full && changed.has("beat")) paintLyrics(s);
      // Every animation frame changes the time: the chord panel redraws on a new beat only.
      if (full || changed.has("beat")) renderNow(s);
      else if (changed.has("time") && Math.floor(s.time * 10) !== shownTenth) renderTime(s);
      shownTenth = Math.floor(s.time * 10);
      if (full) renderHarmony(s);
      lastPass = pass;
    });

    return {
      render(s) {
        renderSheet(s);
        renderNow(s);
        renderHarmony(s);
      },
      barEl: (u) => barEl(u, store.get()),
      // A bar of the grid shows the pass playing; a free bar or a sung bar (.nb) is one bar.
      barFromEl: (el) => (el.classList.contains("bar") && !el.hasAttribute("data-free") ? barShown(+el.getAttribute("data-group"), +el.getAttribute("data-col"), store.get()) : +el.getAttribute("data-bar")),
    };
  };
})();
