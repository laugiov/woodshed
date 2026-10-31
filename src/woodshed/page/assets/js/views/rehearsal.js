// The rehearsal sheet (spec 031): the band's old chord sheets inside woodshed. One song, one screen if it can: the
// title, the notes, the sections with simple chords over the words, bar lines where nothing is sung, the chord boxes;
// nothing else. Opened from the page (or #rehearsal in the address), it stays open from song to song of the set.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, chordNode } = W;

  // A section repeating the one just before (same chords, same words) is one heading: "Chorus ×2".
  const base = (name) => String(name || "").replace(/\s*\d+$/, "");
  const sig = (sec) => JSON.stringify([sec.lines || null, sec.blocks || null]);
  function collapse(sections) {
    const out = [];
    for (const sec of sections) {
      const last = out[out.length - 1];
      if (last && base(last.name) === base(sec.name) && sig(last) === sig(sec)) {
        last.times += 1;
        last.name = base(last.name);
      } else out.push({ ...sec, times: 1 });
    }
    return out;
  }
  W.rehearsal = { collapse };

  const LEVELS = [["triads", "Triads"], ["usual", "Usual"], ["heard", "As heard"]];
  const chunks = (list, n) => list.reduce((rows, x, i) => (i % n ? rows[rows.length - 1].push(x) : rows.push([x]), rows), []);

  W.views = W.views || {};

  W.views.rehearsal = function rehearsal(app) {
    const { song, store } = app;
    const body = $("rhBody");
    let level = LEVELS.some(([k]) => k === app.deviceGet("woodshed:rhlevel")) ? app.deviceGet("woodshed:rhlevel") : "usual";
    let manual = Number(app.deviceGet("woodshed:rhsize")) || 0; // a size set by hand, else fitted
    const boxesKept = app.deviceGet("woodshed:rhboxes");
    let boxes = boxesKept === null ? innerWidth >= 760 : boxesKept === "1"; // off on a phone unless asked
    let page = 0;
    let pages = 1;

    // The song as the sheet writes it: sections of lines (words with chords) and of bar rows, in time order.
    function model(s) {
      const shift = app.showShapes(s) ? s.capo : 0;
      const name = (c, u) => (c.pc < 0 ? "N.C." : app.nameFor(W.chords.simplify(c, level), shift, s, u));
      const list = app.sections();
      const sections = list && list.length ? list : [{ start: 0, end: song.bars.length }];
      const { rows, owner } = app.words ? app.words.rows() : { rows: [], owner: song.bars.map(() => -1) };
      return collapse(sections.map((sec) => {
        const blocks = [];
        for (const r of rows) {
          if (r.firstBar < sec.start || r.firstBar >= sec.end) continue;
          const words = r.bars.flatMap((b) => b.items.map((it) => ({
            chord: it.chords.map((p) => name(p.chord, p.bar)).filter((n, i, all) => i === 0 || n !== all[i - 1]).join(" "),
            text: it.kind === "word" ? it.text : "",
          })));
          blocks.push({ at: r.line.start, li: r.li, words });
        }
        let run = [];
        const flush = () => {
          if (!run.length) return;
          const bars = run.map((u) => song.bars[u].chords.map((c) => name(c, u)).filter((n, i, all) => i === 0 || n !== all[i - 1]));
          blocks.push({ at: song.bars[run[0]].start, bars: chunks(bars, 4) });
          run = [];
        };
        for (let u = sec.start; u < sec.end; u++) {
          if (owner[u] < 0) run.push(u);
          else flush();
        }
        flush();
        blocks.sort((a, b) => a.at - b.at);
        return { name: list && list.length ? W.partName(sec) : "", blocks: blocks.map(({ at, ...x }) => x) };
      }));
    }

    const seg = (label, items) => h("span", { class: "seg-ctl rh-opt", role: "group", "aria-label": label }, items);
    const pressed = (on, testid, text, onclick) => h("button", { type: "button", class: on ? "on" : "", "aria-pressed": String(on), "data-testid": testid, onclick }, text);
    function drawHead(s) {
      clear($("rhTitle"), app.shownTitle());
      const facts = [[W.t("Key"), song.keyPathText(s.transpose)], [W.t("BPM"), String(Math.round(app.songBpm))]];
      if (app.showShapes(s)) facts.push([W.t("Capo"), W.t("{n} · shapes", { n: s.capo })]);
      else if (s.inst === "guitar" && s.pos === "open" && s.capo > 0) facts.push([W.t("Capo"), String(s.capo)]);
      clear($("rhFacts"), facts.map(([k, v]) => h("span", null, k + " ", h("b", null, v))));
      const capo = s.inst === "guitar" && s.pos === "open" && s.capo > 0;
      clear($("rhTools"),
        h("button", { type: "button", class: "btn", "data-testid": "rh-smaller", "aria-label": W.t("Smaller text"), title: W.t("Smaller text"), onclick: () => resize(-2) }, "A−"),
        h("button", { type: "button", class: "btn", "data-testid": "rh-bigger", "aria-label": W.t("Bigger text"), title: W.t("Bigger text"), onclick: () => resize(2) }, "A+"),
        seg(W.t("Chords"), LEVELS.map(([k, label]) => pressed(level === k, "rh-level-" + k, W.t(label), () => {
          level = k;
          app.deviceSet("woodshed:rhlevel", k);
          draw();
        }))),
        capo ? seg(W.t("Chart shows"), [
          pressed(s.view === "concert", "rh-show-concert", W.t("Real chords"), () => store.set({ view: "concert" })),
          pressed(s.view === "shapes", "rh-show-shapes", W.t("Shapes"), () => store.set({ view: "shapes" })),
        ]) : null,
        s.inst === "guitar" && app.shapeFor ? seg(W.t("Chord boxes"), [pressed(boxes, "rh-boxes-toggle", W.t("Chord boxes"), () => {
          boxes = !boxes;
          app.deviceSet("woodshed:rhboxes", boxes ? "1" : "0");
          draw();
        })]) : null,
        h("button", { type: "button", class: "btn", "data-testid": "rehearsal-close", "aria-label": W.t("Close the rehearsal sheet"), title: W.t("Close the rehearsal sheet"), onclick: () => close() }, "✕"));
      const lines = s.bandNote ? s.bandNote.split("\n") : [];
      $("rhNotes").hidden = !lines.length;
      clear($("rhNotes"), lines.map((l) => h("p", { translate: "no" }, l)));
    }

    function drawBody(s) {
      clear(body, model(s).map((sec) => h("section", { class: "rh-sec" },
        sec.name ? h("h3", null, sec.name, sec.times > 1 ? h("span", { class: "x" }, "×" + sec.times) : null) : null,
        sec.blocks.map((b) => b.bars
          ? b.bars.map((row) => h("p", { class: "rh-bars", translate: "no" }, h("i", null, "| "),
            row.map((bar, k) => [bar.map((n, i) => [i ? "  " : "", chordNode(n)]), h("i", null, k === row.length - 1 ? " |" : " | ")])))
          : h("p", { class: "rh-line", "data-li": b.li, translate: "no" }, b.words.map((w) =>
            h("span", { class: "rh-w" }, h("b", { class: "rh-c" }, w.chord ? chordNode(w.chord) : ""), h("span", null, w.text || " "))))))));
      // The chord boxes: the song's own chords as played (the shapes with a capo), after the level's simplification.
      const shown = boxes && s.inst === "guitar" && app.shapeFor;
      $("rhBoxes").hidden = !shown;
      if (shown) {
        const seen = new Map();
        song.bars.forEach((bar) => bar.chords.forEach((c) => {
          if (c.pc < 0) return;
          const x = W.chords.simplify(c, level);
          const key = W.chords.key(x);
          if (!seen.has(key)) seen.set(key, x);
        }));
        const shift = app.showShapes(s) ? s.capo : 0;
        clear($("rhBoxes"), [...seen.values()].slice(0, 14).map((x) => {
          const shape = app.shapeFor(x, s);
          return shape ? h("figure", null, app.guitarDiagram(shape), h("figcaption", { translate: "no" }, chordNode(app.nameFor(x, shift, s)))) : null;
        }));
      }
    }

    // One song, one screen: the largest text at which it fits its columns, else pages turned sideways.
    const step = () => body.clientWidth + (parseFloat(getComputedStyle(body).columnGap) || 0);
    const fitsAt = (px) => {
      body.style.setProperty("--rh-size", px + "px");
      return body.scrollWidth <= body.clientWidth + 1 && body.scrollHeight <= body.clientHeight + 1;
    };
    function fit() {
      body.style.columnCount = innerWidth >= 1200 ? 3 : innerWidth >= 760 ? 2 : 1;
      let size = 16;
      if (manual) size = manual;
      else if (fitsAt(16)) {
        let lo = 16;
        let hi = 40;
        while (hi - lo > 0.5) {
          const mid = (lo + hi) / 2;
          if (fitsAt(mid)) lo = size = mid;
          else hi = mid;
        }
      }
      fitsAt(size);
      pages = Math.max(1, Math.round(body.scrollWidth / step()));
      turn(Math.min(page, pages - 1));
    }
    function turn(k) {
      page = Math.max(0, Math.min(pages - 1, k));
      body.scrollTo({ left: page * step(), behavior: "instant" });
      $("rhPager").hidden = pages < 2;
      clear($("rhPager"),
        h("button", { type: "button", class: "btn", "aria-label": W.t("Previous page"), disabled: page === 0 ? "" : null, onclick: () => turn(page - 1) }, "‹"),
        h("span", null, page + 1 + " / " + pages),
        h("button", { type: "button", class: "btn", "aria-label": W.t("Next page"), disabled: page === pages - 1 ? "" : null, onclick: () => turn(page + 1) }, "›"));
    }
    function resize(by) {
      const now = parseFloat(body.style.getPropertyValue("--rh-size")) || 16;
      manual = Math.max(14, Math.min(64, Math.round(now + by)));
      app.deviceSet("woodshed:rhsize", String(manual));
      fit();
    }

    // The line the band is at: marked, and its page shown if it is on another.
    let marked = -2;
    function mark(s) {
      const li = app.words ? app.words.lineAt(s.time).now : -1;
      if (li === marked) return;
      marked = li;
      body.querySelectorAll(".rh-line.cur").forEach((el) => el.classList.remove("cur"));
      const el = li >= 0 ? body.querySelector('.rh-line[data-li="' + li + '"]') : null;
      if (!el) return;
      el.classList.add("cur");
      const at = Math.floor((el.offsetLeft - body.offsetLeft + 1) / step());
      if (at !== page && at >= 0) turn(at);
    }

    function draw() {
      const s = store.get();
      if (!s.rehearsal) return;
      drawHead(s);
      drawBody(s);
      fit();
      marked = -2;
      mark(s);
    }

    // While the sheet is open its keys are its own: the arrows and a pedal turn pages, Space plays, Escape closes.
    const keys = (e) => {
      if (e.target instanceof Element && e.target.closest("input, textarea")) return;
      e.stopPropagation();
      if (e.type !== "keydown") return;
      if (["ArrowRight", "ArrowDown", "PageDown"].includes(e.key)) turn(page + 1);
      else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(e.key)) turn(page - 1);
      else if (e.key === "Escape") close();
      else if (e.key === " " && !(e.target instanceof Element && e.target.closest("button"))) app.togglePlay();
      else return;
      e.preventDefault();
    };
    function open() {
      if (store.get().rehearsal) return;
      store.set({ rehearsal: true });
      if (location.hash !== "#rehearsal") history.replaceState(null, "", location.pathname + location.search + "#rehearsal");
      $("rehearsal").hidden = false;
      window.addEventListener("keydown", keys, true);
      window.addEventListener("keyup", keys, true);
      draw();
      $("rehearsal").focus({ preventScroll: true });
    }
    function close() {
      if (!store.get().rehearsal) return;
      store.set({ rehearsal: false });
      history.replaceState(null, "", location.pathname + location.search);
      $("rehearsal").hidden = true;
      window.removeEventListener("keydown", keys, true);
      window.removeEventListener("keyup", keys, true);
      $("rehearsalBtn").focus({ preventScroll: true });
    }
    app.openRehearsal = open;
    $("rehearsalBtn").addEventListener("click", open);

    let resizing = 0;
    window.addEventListener("resize", () => {
      clearTimeout(resizing);
      resizing = setTimeout(() => store.get().rehearsal && fit(), 150);
    });
    if (document.fonts) document.fonts.ready.then(() => store.get().rehearsal && fit());
    store.on((s, changed) => {
      if (!s.rehearsal) return;
      if (["view", "capo", "transpose", "inst", "pos", "corrections", "bandNote", "bandTitle", "bandArtist", "lang"].some((k) => changed.has(k))) draw();
      else if (changed.has("time") || changed.has("beat")) mark(s);
    });
    W.onLang.push(() => draw());
    if (location.hash === "#rehearsal") setTimeout(open, 0);
    return {};
  };
})();
