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
      // A correction stays a button: it can be changed, or taken back to the analysis's chord.
      const inner = c.doubt && !c.fixed
        ? h(
            "button",
            { type: "button", class: "doubt" + (timing ? " timing" : ""), "data-ref": ref, "data-testid": "doubt", "data-kind": c.doubt.kind, title: timing ? W.t("Placement to check by ear") : W.t("Check by ear") },
            main,
            timing ? null : h("sup", null, "?"),
          )
        : c.fixed && c.doubt
          ? h("button", { type: "button", class: "doubt fixed", "data-ref": ref, "data-testid": "fixed", title: W.t("Your correction: change it") }, main, h("span", { class: "fixed-dot", "aria-hidden": "true" }))
          : main;
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

    // A verse or a chorus played with different chords from the first one of its kind: said, not hidden
    // (the band may really play it so, or the chart may be wrong there: an ear decides).
    const COMPARED = ["verse", "prechorus", "chorus"];
    function playedOtherwise(sec, k) {
      if (!COMPARED.includes(sec.role)) return null;
      const list = app.sections();
      const firstOne = list.find((x, j) => j < k && x.role === sec.role);
      if (!firstOne) return null;
      const chords = (u) => (song.bars[u] ? song.bars[u].chords : []).map((c) => W.chords.key(c)).join(" ");
      // The shorter laid along the longer where they agree best: a chorus with two more bars in
      // front is not "different" for that.
      const [short, long] = sec.end - sec.start <= firstOne.end - firstOne.start ? [sec, firstOne] : [firstOne, sec];
      const n = short.end - short.start;
      let best = null; // the bars of this part that differ, where the two agree best
      for (let shift = 0; shift <= long.end - long.start - n; shift++) {
        const differ = [];
        for (let i = 0; i < n; i++) {
          if (chords(short.start + i) !== chords(long.start + shift + i)) differ.push((short === sec ? sec.start + i : sec.start + shift + i) + 1);
        }
        if (!best || differ.length < best.length) best = differ;
      }
      return n && best.length / n > 0.25 ? { part: firstOne, bars: best } : null;
    }
    // "bar 6", "bars 6-7, 9": the bars to listen to.
    function barsText(bars) {
      const spans = [];
      for (const b of bars) {
        const last = spans[spans.length - 1];
        if (last && b === last[1] + 1) last[1] = b;
        else spans.push([b, b]);
      }
      const list = spans.map(([a, z]) => (a === z ? String(a) : a + "-" + z)).join(", ");
      return bars.length === 1 ? W.t("bar {n}", { n: list }) : W.t("bars {list}", { list });
    }

    function sectionHead(sec, k) {
      const first = bar(sec.start);
      const n = sec.end - sec.start;
      const part = W.partName(sec.name);
      const other = playedOtherwise(sec, k);
      return h(
        "div",
        { class: "sec-head", "data-testid": "section", "data-section": k, "data-role": sec.role },
        h("button", { type: "button", class: "sec-name", "data-goto": sec.start, title: W.t("Go to {part}", { part }) }, part),
        h("span", { class: "sec-meta" }, fmt(first.start) + " · " + (n === 1 ? W.t("1 bar") : W.t("{n} bars", { n }))),
        other ? h("span", { class: "sec-other", "data-testid": "played-otherwise" }, W.t("{bars}: different chords from {part}, check by ear", { bars: barsText(other.bars), part: W.partName(other.part.name) })) : null,
        h("button", { type: "button", class: "linkbtn sec-loop", "data-loop": sec.start, "data-testid": "section-loop", title: W.t("Loop {part}", { part }) }, W.t("⟲ Loop")),
      );
    }

    function renderForm(s) {
      const list = app.sections();
      const cur = list.length ? song.sectionIndex(curBar(s), list) : -1;
      const focused = [...$("form").children].indexOf(document.activeElement);
      const stop = focused >= 0 ? focused : Math.max(0, cur); // one tab stop: the part playing, or the one in hand
      clear(
        $("form"),
        list.map((sec, k) =>
          h("button", { type: "button", class: "form-chip" + (k === cur ? " on" : "") + " r-" + sec.role, tabindex: k === stop ? "0" : "-1", "data-goto": sec.start, "data-testid": "form-chip" }, W.partName(sec.name)),
        ),
      );
      if (focused >= 0 && $("form").children[focused]) $("form").children[focused].focus({ preventScroll: true }); // the page follows the song
    }
    // The parts: one stop for Tab, the arrows (and Home, End) move between them.
    $("form").addEventListener("keydown", (e) => {
      const chips = [...$("form").children];
      const k = chips.indexOf(document.activeElement);
      if (k < 0) return;
      const to = { ArrowRight: k + 1, ArrowDown: k + 1, ArrowLeft: k - 1, ArrowUp: k - 1, Home: 0, End: chips.length - 1 }[e.key];
      if (to === undefined) return;
      e.preventDefault();
      e.stopPropagation(); // the arrows move bars elsewhere on the page
      const next = chips[Math.max(0, Math.min(chips.length - 1, to))];
      chips.forEach((c) => c.setAttribute("tabindex", c === next ? "0" : "-1"));
      next.focus();
    });

    // A sung line on its bars: each bar kept whole (a bar line, numbered, then its words), each
    // chord above the word it lands on, a chord with no word under it over a dash, a push marked.
    // Shared with stage mode (opts.stage: no bar lines, no seeking, no checks).
    function lyricLine(row, s, opts) {
      const shift = app.showShapes(s) ? s.capo : 0;
      const mark = (p) => {
        const name = chordNode(app.nameFor(p.chord, shift, s));
        const push = p.push ? h("span", { class: "push" }, W.t("push")) : null;
        if (!opts.stage && p.chord.doubt && !p.chord.fixed) {
          const timing = p.chord.doubt.kind === "timing";
          return h(
            "button",
            { type: "button", class: "doubt" + (timing ? " timing" : ""), "data-ref": p.bar + "_" + p.index, "data-testid": "doubt", "data-kind": p.chord.doubt.kind, title: timing ? W.t("Placement to check by ear") : W.t("Check by ear"), "aria-label": W.t("Check this chord by ear, bar {n}", { n: p.bar + 1 }) },
            name,
            timing ? null : h("sup", null, "?"),
            push,
          );
        }
        if (p.chord.fixed && p.chord.doubt && !opts.stage) {
          return h(
            "button",
            { type: "button", class: "doubt fixed", "data-ref": p.bar + "_" + p.index, "data-testid": "fixed", title: W.t("Your correction: change it"), "aria-label": W.t("Your correction, bar {n}: change it", { n: p.bar + 1 }) },
            name,
            h("span", { class: "fixed-dot", "aria-hidden": "true" }),
            push,
          );
        }
        return [name, push];
      };
      const word = (item) => {
        const checks = !opts.stage && item.chords.some((p) => p.chord.doubt); // to check, or a correction to change
        // The chord names are for the eye: a screen reader reads the words, and the checks.
        const lc = h("span", { class: "lc", "aria-hidden": checks ? null : "true" }, item.chords.map((p, i) => [i ? " " : "", mark(p)]));
        if (item.kind === "gap") return h("span", { class: "lw gap" }, lc, h("span", { class: "wt", "aria-hidden": "true" }, "–"));
        const seek = !opts.stage && item.timed ? item.t.toFixed(3) : null;
        return h("span", { class: "lw" + (item.chords.length ? " has" : ""), "data-seek": seek }, lc, h("span", { class: "wt", translate: "no" }, item.text));
      };
      const parts = [];
      row.bars.forEach((b, i) => {
        const inner = [];
        if (!opts.stage && !b.cont) inner.push(h("span", { class: "bl", "aria-hidden": "true" }, h("i", null, String(b.bar + 1))));
        b.items.forEach((item, j) => inner.push(j ? " " : "", word(item)));
        if (i) parts.push(" ");
        parts.push(h("span", { class: "nb", "data-bar": b.cont ? null : b.bar }, inner));
      });
      const backing = row.line.backing && row.line.backing.length ? h("span", { class: "bv", translate: "no" }, " (" + row.line.backing.join(") (") + ")") : null;
      return h("span", { class: "lwords" }, parts, backing);
    }
    app.lyricLine = lyricLine;

    const barLabel = (b, u, s) => W.t("Bar {n}: {chords}", { n: u + 1, chords: b.chords.map((c) => W.prettyText(app.nameFor(c, 0, s))).join(", ") });

    // Bars no sung line holds (an intro, a solo, an ending), as bars of the grid, four a row.
    function freeRow(list, s, note) {
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
            { class: "bar", "data-free": "", "data-bar": u, role: "button", tabindex: 0, "aria-label": barLabel(b, u, s), "data-testid": "bar" },
            barContent(b, u, s),
            h("span", { class: "num" }, String(u + 1)),
            h("span", { class: "rn", translate: "no" }, b.chords.map((c) => song.roman(c)).join(" ")),
          ),
        );
      }
      return h(
        "div",
        { class: "line", "data-testid": "line" },
        h("div", { class: "line-label" }, h("span", { class: "t" }, fmt(bar(list[0]).start)), note ? h("span", { class: "free-note", "data-testid": "free-note" }, note) : null),
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
      // Bars no line holds: inside a sung part they are said ("no words here"), after the last sung
      // line once ("the text may stop before the song"): never an unexplained grid among the words.
      const lastSung = rows.reduce((m, r) => Math.max(m, r.bars[r.bars.length - 1].bar), -1);
      const firstSung = rows.reduce((m, r) => Math.min(m, r.bars[0].bar), Infinity);
      const sung = new Set(rows.map((r) => (sections.length ? song.sectionIndex(r.firstBar, sections) : -1)));
      let endSaid = false;
      const freeNote = (x) => {
        if (x.at < firstSung) return null; // an intro, before anything is sung
        if (x.at > lastSung) {
          if (endSaid) return null;
          endSaid = true;
          return W.t("No words placed from here: the text pasted may stop before the song does.");
        }
        return sung.has(sections.length ? song.sectionIndex(x.at, sections) : -1) ? W.t("no words here") : null;
      };
      const out = [];
      let shown = -1;
      for (const x of blocks) {
        const k = sections.length ? song.sectionIndex(x.at, sections) : -1;
        while (k > shown) {
          shown++;
          out.push(sectionHead(sections[shown], shown));
        }
        if (x.free) {
          out.push(freeRow(x.free, s, freeNote(x)));
          continue;
        }
        const r = x.row;
        const last = r.bars[r.bars.length - 1].bar;
        out.push(
          h(
            "div",
            // The check is one of the texts woodshed lyrics writes, in core/i18n-fr.js.
            { class: "lline" + (r.line.check ? " check" : ""), "data-line": r.li, "data-from": r.bars[0].bar, "data-to": last, "data-testid": "lyric-line", title: r.line.check ? W.t(r.line.check) : null },
            h("button", { type: "button", class: "t", "data-seek": r.line.start.toFixed(3), "aria-label": W.t("Play from {time}: {words}", { time: fmt(r.line.start), words: r.line.text }) }, fmt(r.line.start)),
            lyricLine(r, s, { stage: false }),
          ),
        );
      }
      clear($("sheet"), inBlocks(out));
      paintLyrics(s);
    }

    // Each part with its lines in one block: on paper a part stays on one page when it fits.
    function inBlocks(items) {
      const blocks = [];
      for (const el of items) {
        if (!blocks.length || el.classList.contains("sec-head")) blocks.push(h("div", { class: "sec-block" }));
        blocks[blocks.length - 1].append(el);
      }
      return blocks;
    }

    // On paper, a guitarist gets the song's shapes once, in the voicing shown (hidden on screen).
    let printShown = "";
    function renderPrintShapes(s) {
      const box = $("printShapes");
      const shows = [s.inst, s.pos, s.capo, s.transpose, s.corrections, W.lang()].join("|");
      if (shows === printShown) return; // drawn again only when the shapes change, not at each pass
      printShown = shows;
      const shapes = s.inst === "guitar" && app.shapeFor
        ? song.distinctChords().filter((c) => c.pc >= 0).map((c) => {
            const shape = app.shapeFor(c, s);
            const shift = s.pos === "open" ? s.capo : 0;
            return shape ? h("figure", null, app.guitarDiagram(shape), h("figcaption", null, chordNode(app.nameFor(c, shift, s)))) : null;
          }).filter(Boolean)
        : [];
      const capo = s.pos === "open" && s.capo ? h("figure", { class: "pcapo" }, W.t("Capo {n}", { n: s.capo })) : null;
      clear(box, shapes.length ? capo : null, shapes);
      box.hidden = !shapes.length;
    }

    function paintLyrics(s) {
      if (app.sheetMode(s) !== "lyrics") return;
      const k = app.lineNow(s).now;
      document.querySelectorAll(".lline").forEach((el) => el.classList.toggle("cur", +el.getAttribute("data-line") === k));
    }

    function renderSheet(s) {
      const sections = app.sections();
      if (app.sheetMode(s) === "lyrics") {
        renderLyrics(s, sections);
        renderPrintShapes(s);
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
      clear($("sheet"), inBlocks(lines));
      renderPrintShapes(s);
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
            { class: "bar", "data-col": col, "data-group": g, "data-bar": u, role: "button", tabindex: 0, "aria-label": barLabel(b, u, s), "data-testid": "bar" },
            barContent(b, u, s),
            h("span", { class: "num" }, String(u + 1)),
            h("span", { class: "rn", translate: "no" }, b.chords.map((c) => song.roman(c)).join(" ")),
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
      // Drawn again only when what it shows changes: a redraw under a click (the band's corrections
      // arriving) would swallow it.
      const shows = [mode, !!app.words, s.inst, s.pos, s.capo, s.view, s.transpose, s.bandKey, s.wordsElsewhere, W.lang()].join("|");
      if (el.dataset.shows === shows) return;
      el.dataset.shows = shows;
      const sheetCtl = app.words
        ? h(
            "div",
            { class: "seg-ctl", role: "group", "aria-label": W.t("Chart with") },
            h("button", { type: "button", class: mode === "grid" ? "on" : "", "aria-pressed": String(mode === "grid"), "data-testid": "sheet-grid", onclick: () => store.set({ sheet: "grid" }) }, W.t("Grid")),
            h("button", { type: "button", class: mode === "lyrics" ? "on" : "", "aria-pressed": String(mode === "lyrics"), "data-testid": "sheet-lyrics", onclick: () => store.set({ sheet: "lyrics" }) }, W.t("Lyrics")),
          )
        : null;
      // The words are placed on the singer's track: offered once the page has it.
      const wordsBtn = song.tracks.some((t) => t.id === "solo-vocals") && !s.wordsElsewhere
        ? h("button", { type: "button", class: "btn", "data-testid": "words-open", onclick: () => app.openWords() }, app.words ? W.t("Edit the words") : W.t("Add the words"))
        : null;
      if (s.inst === "guitar" && s.pos === "open" && s.capo > 0) {
        clear(
          el,
          sheetCtl,
          wordsBtn,
          h(
            "div",
            { class: "seg-ctl", role: "group", "aria-label": W.t("Chart shows") },
            h("button", { type: "button", class: s.view === "concert" ? "on" : "", onclick: () => store.set({ view: "concert" }) }, W.t("Real chords")),
            h("button", { type: "button", class: s.view === "shapes" ? "on" : "", "data-testid": "show-shapes", onclick: () => store.set({ view: "shapes" }) }, W.t("Shapes, capo {n}", { n: s.capo })),
          ),
          keyNote(s).slice(s.transpose ? 0 : 1), // the capo says where the chords sound already
        );
      } else clear(el, sheetCtl, wordsBtn, keyNote(s));
    }

    // In another key than the recording, the page says so while it lasts; served by woodshed app,
    // the key can be kept for the band.
    function keyNote(s) {
      const key = (t) => W.prettyText(song.keyName(t));
      const out = [s.transpose
        ? h("span", { class: "hint key-note", "data-testid": "key-note" }, W.t("Chords in {key}: the recording plays in {original}.", { key: key(s.transpose), original: key(0) }))
        : h("span", { class: "hint" }, W.t("Real chords, concert pitch"))];
      if (s.bandKey === null || !app.shareBand) return out;
      if (s.transpose !== s.bandKey) {
        out.push(h("button", { type: "button", class: "btn", "data-testid": "band-key-keep", onclick: () => app.keepBandKey() }, W.t("Keep {key} for the band", { key: key(s.transpose) })));
        if (s.bandKey) out.push(h("button", { type: "button", class: "btn", "data-testid": "band-key-back", onclick: () => app.transposeTo(s.bandKey) }, W.t("The band's key: {key}", { key: key(s.bandKey) })));
      } else if (s.bandKey) out.push(h("span", { class: "okfact", "data-testid": "band-key" }, W.t("The band's key")));
      return out;
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
      clear($("nextChord"), up[0] ? chordNode(app.nameFor(up[0], shift, s)) : W.t("end"));
      clear($("thenChord"), up[1] ? chordNode(app.nameFor(up[1], shift, s)) : "");
      for (const box of [$("beats"), $("stBeats")]) {
        if (box.children.length !== song.per) clear(box, Array.from({ length: song.per }, (_, i) => h("div", { class: "beat" + (i === 0 ? " one" : "") })));
        for (let i = 0; i < box.children.length; i++) box.children[i].classList.toggle("on", i === b % song.per);
      }
      const sec = app.sectionOf(u);
      $("barInfo").textContent = sec ? W.partName(sec.name) : W.t("Bar {n}", { n: u + 1 });
      $("passInfo").textContent = sec ? W.t("bar {n} of {len}", { n: u - sec.start + 1, len: sec.end - sec.start }) : W.t("of {len}", { len: song.bars.length });
      renderTime(s);
    }

    function renderTime(s) {
      $("timeInfo").textContent = fmt(s.time, true);
    }

    function renderHarmony(s) {
      const key = song.keyName(s.transpose);
      const minor = key.endsWith("m");
      clear($("keyTitle"), chordNode(minor ? key.slice(0, -1) : key, "kn"), " " + (minor ? W.t("minor") : W.t("major")));
      if (!song.song.key.known) $("keyTitle").append(h("small", { class: "hint" }, " " + W.t("(uncertain)")));
      const sections = song.song.harmony;
      // Harmony is summarised per family of lines (A, B); the page names them after the part
      // where each family is first heard (Verse, Chorus), the names the chart shows.
      const partOf = (family) => {
        const g = song.song.groups.find((gr) => gr.family === family);
        const sec = g && app.sectionOf(g.occurrences[0][0]);
        return sec ? W.partName(sec.name.replace(/ \d+$/, "")) : family;
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
        sec.chords.forEach(([pc, q], i) => prog.append(h("span", null, chordNode(app.nameFor({ pc, quality: q }, 0, s)), h("small", { translate: "no" }, sec.romans[i]))));
        if (!sec.name) return;
        const named = W.t(sec.name); // a well-known progression's name (theory.PROGRESSIONS), in core/i18n-fr.js
        const said = named.charAt(0).toUpperCase() + named.slice(1) + ".";
        text.push(sections.length > 1 ? W.t("{part}: {progression}", { part: labels[n], progression: said }) : said);
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
            h("button", { type: "button", "data-goto": d.bar }, W.t("Bar {n}", { n: d.bar + 1 })),
            h("span", null, chordNode(app.nameFor(d.chord, 0, s)), "? " + W.t(d.chord.doubt.why)),
          ),
        );
      }
      clear($("checks"), items.length ? items : h("li", { class: "ok" }, h("span", null, W.t("Nothing left to check by ear."))));
    }

    let lastPass = null;
    let shownTenth = -1;
    store.on((s, changed) => {
      const u = curBar(s);
      const pass = bar(u).group + ":" + bar(u).occurrence;
      const full = ["transpose", "capo", "inst", "pos", "view", "corrections", "sheet", "bandKey", "wordsElsewhere"].some((k) => changed.has(k));
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
      if (s.playing && (full || changed.has("beat"))) keepInView(s);
      if (changed.has("playing")) {
        if (s.playing) paused = false; // a new play: the page follows again
        else back.hidden = true;
      }
    });

    // While the song plays the page scrolls with it: the bar or the sung line playing stays in the
    // upper part of the screen, above the dock. Only while the chart is on screen (a phone reading the
    // instrument panel under it stays there). A scroll by hand wins: following waits while the
    // musician reads elsewhere, with a button back to the song, and comes back by itself when the bar
    // playing is where the page would put it (the music reached what they read, or they scrolled
    // back to it), on play, and on a jump they ask for.
    let paused = false;
    const byHand = () => (paused = true);
    app.followAgain = () => (paused = false);
    const back = h("button", { type: "button", class: "btn back-to-song", hidden: "", "data-testid": "back-to-song" }, W.t("Back to the song"));
    back.addEventListener("click", () => {
      paused = false;
      followed = null;
      keepInView(store.get(), true);
    });
    document.body.appendChild(back);
    W.onLang.push(() => (back.textContent = W.t("Back to the song")));
    const inside = (e, sel) => e.target instanceof Element && !!e.target.closest(sel);
    // Dragging the tempo slider or the waveform of the dock is not a scroll.
    const scrolled = (e) => inside(e, "#dock, input") || byHand();
    window.addEventListener("wheel", scrolled, { passive: true });
    window.addEventListener("touchmove", scrolled, { passive: true });
    window.addEventListener("keydown", (e) => {
      // The page's own keys (a pedal's PageDown seeks a bar) are not a scroll.
      if (e.defaultPrevented || !["PageUp", "PageDown", "ArrowUp", "ArrowDown", "Home", "End"].includes(e.key)) return;
      if (!inside(e, "input, select, textarea")) byHand();
    });
    document.addEventListener("mousedown", (e) => {
      if (e.target === document.documentElement) byHand(); // the scrollbar
    });
    let followed = null;
    // `asked`: the musician pressed Back to the song, wherever the page is.
    function keepInView(s, asked) {
      // In the Lyrics view an intro or a solo is a free bar, between the sung lines.
      const el = app.sheetMode(s) === "lyrics" ? document.querySelector(".bar[data-free].cur") || document.querySelector(".lline.cur") : document.querySelector(".bar.cur");
      if (!el || s.stage) return;
      const seen = window.innerHeight - $("dock").offsetHeight;
      if (paused) {
        const box = el.getBoundingClientRect();
        if (!(box.top >= seen * 0.12 && box.bottom <= seen * 0.75)) {
          back.hidden = !s.playing;
          return;
        }
        paused = false; // the bar playing is where the eyes are
      }
      back.hidden = true;
      if (el === followed) return;
      const sheet = $("sheet").getBoundingClientRect();
      if (!asked && (sheet.bottom <= 0 || sheet.top >= seen)) return; // the musician reads something else
      followed = el;
      const r = el.getBoundingClientRect();
      if (r.top >= seen * 0.12 && r.bottom <= seen * 0.75) return;
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollBy({ top: r.top - seen * 0.3, behavior: smooth ? "smooth" : "auto" });
    }

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
