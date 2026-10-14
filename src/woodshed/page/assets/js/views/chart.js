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
      const inner = c.doubt && !c.fixed
        ? h("button", { type: "button", class: "doubt", "data-ref": ref, "data-testid": "doubt", title: "Check by ear" }, main, h("sup", null, "?"))
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

    function renderSheet(s) {
      const lines = song.song.groups.map((gr, g) => {
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
          h("div", { class: "line-label" }, h("span", { class: "sec", "data-testid": "section" }, gr.label), h("span", { class: "t" }, fmt(bar(gr.occurrences[0][0]).start))),
          h(
            "div",
            { class: "staff four" },
            n > 1 ? h("div", { class: "rep" }, "𝄆") : h("div", { class: "plain-bar" }),
            cells,
            n > 1 ? [h("div", { class: "rep r-end" }, "𝄇"), h("span", { class: "times", "data-testid": "repeat" }, "×" + n)] : h("div", { class: "plain-end" }),
          ),
        );
      });
      clear($("sheet"), lines);
      renderViewControl(s);
      paintBars(s);
    }

    function renderViewControl(s) {
      const el = $("viewCtl");
      if (s.inst === "guitar" && s.pos === "open" && s.capo > 0) {
        clear(
          el,
          h(
            "div",
            { class: "seg-ctl", role: "group", "aria-label": "Chart shows" },
            h("button", { type: "button", class: s.view === "concert" ? "on" : "", onclick: () => store.set({ view: "concert" }) }, "Real chords"),
            h("button", { type: "button", class: s.view === "shapes" ? "on" : "", "data-testid": "show-shapes", onclick: () => store.set({ view: "shapes" }) }, "Shapes, capo " + s.capo),
          ),
        );
      } else clear(el, h("span", { class: "hint" }, "Real chords, concert pitch"));
    }

    function barEl(u, s) {
      const b = bar(u);
      if (barShown(b.group, b.column, s) !== u) return null;
      return document.querySelector('.bar[data-group="' + b.group + '"][data-col="' + b.column + '"]');
    }

    function paintBars(s) {
      document.querySelectorAll(".bar").forEach((e) => {
        e.classList.remove("cur", "inloop");
        const c = e.querySelector(".cursor");
        if (c) c.remove();
      });
      const u = curBar(s);
      const el = barEl(u, s);
      if (el) {
        el.classList.add("cur");
        el.appendChild(h("span", { class: "cursor", style: { left: ((s.beat % song.per) * 100) / song.per + "%" } }));
      }
      if (s.loopOn && s.loop) for (let i = s.loop[0]; i <= s.loop[1]; i++) {
        const le = barEl(i, s);
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
      const gr = song.song.groups[bar(u).group];
      const passes = gr.occurrences.length;
      $("barInfo").textContent = "Bar " + (u + 1) + " of " + song.bars.length;
      $("passInfo").textContent = "Line " + gr.label + (passes > 1 ? ", pass " + (bar(u).occurrence + 1) + " of " + passes : "");
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
      const prog = $("prog");
      clear(prog);
      const text = [];
      sections.forEach((sec, n) => {
        // One row per section; the chips are direct children of .prog, as the stylesheet expects.
        if (n > 0) prog.append(h("div", { style: { flexBasis: "100%", height: "0" } }));
        if (sections.length > 1) prog.append(h("b", { class: "prog-sec" }, sec.label));
        sec.chords.forEach(([pc, q], i) => prog.append(h("span", null, chordNode(app.nameFor({ pc, quality: q }, 0, s)), h("small", null, sec.romans[i]))));
        if (sec.name) text.push((sections.length > 1 ? sec.label + ": " : "") + sec.name.charAt(0).toUpperCase() + sec.name.slice(1) + ".");
      });
      $("progText").textContent = text.join(" ");
      const items = [];
      const seen = new Set();
      for (const d of song.doubts()) {
        if (d.chord.fixed || seen.has(d.chord.doubt.id)) continue;
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
      const full = ["transpose", "capo", "inst", "pos", "view", "corrections"].some((k) => changed.has(k));
      if (full || pass !== lastPass) renderSheet(s);
      else if (changed.has("beat") || changed.has("loop") || changed.has("loopOn")) paintBars(s);
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
      barFromEl: (el) => barShown(+el.getAttribute("data-group"), +el.getAttribute("data-col"), store.get()),
    };
  };
})();
