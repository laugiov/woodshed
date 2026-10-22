// Header (title, facts, instrument), practice path, credits, stage mode, toast, menus, doubt pop.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, chordNode, fmt } = W;

  const INSTRUMENTS = () => [["guitar", W.t("Guitar")], ["bass", W.t("Bass")], ["piano", W.t("Keys")], ["drums", W.t("Drums")], ["voice", W.t("Voice")]];
  const PART = { guitar: "guitar", bass: "bass", piano: "keys", drums: "drums", voice: "voice" };
  const LEARN = () => ({
    guitar: [W.t("Learn the shapes"), W.t("Your part alone. Click a shape to hear it.")],
    bass: [W.t("Learn the line"), W.t("The bass alone, with its tab.")],
    piano: [W.t("Learn the voicings"), W.t("The chords alone, as played on the record.")],
    drums: [W.t("Learn the groove"), W.t("The drums alone, with the notation.")],
    voice: [W.t("Find your key"), W.t("The voice alone. Set your voice type on the right.")],
  });

  W.views = W.views || {};

  W.views.header = function header(app) {
    const { song, store } = app;
    const meta = song.song;

    function renderFacts(s) {
      const open = song.doubts().filter((d) => !d.chord.fixed && d.chord.doubt.kind === "chord");
      const spots = new Set(open.map((d) => d.chord.doubt.id)).size;
      const key = song.keyName(s.transpose);
      const minor = key.endsWith("m");
      clear(
        $("facts"),
        h("span", null, h("b", null, String(app.songBpm)), " BPM"),
        h("span", null, h("b", null, meta.beats_per_bar + "/4")),
        h("span", null, W.nodes(W.t("Key {key}"), { key: h("b", null, chordNode(minor ? key.slice(0, -1) : key), " " + (minor ? W.t("minor") : W.t("major"))) })),
        h("span", null, fmt(Math.round(meta.duration))), // rounded, as the library lists it
        spots
          ? h("button", { type: "button", class: "warnfact", "data-goto": open[0].bar, "data-testid": "spots" }, spots === 1 ? W.t("1 spot to check by ear") : W.t("{n} spots to check by ear", { n: spots }))
          : h("span", { class: "okfact" }, W.t("Nothing to check by ear")),
        meta.analysis.chords_reliable ? null : h("span", { class: "warnfact", "data-testid": "unreliable" }, W.t("Little harmony found: chords may be wrong")),
        s.bandNote ? h("span", { class: "band-note", "data-testid": "band-note" }, W.nodes(W.t("Note: {note}"), { note: h("span", { translate: "no" }, s.bandNote) })) : null,
      );
    }

    function renderInstruments(s) {
      clear(
        $("instruments"),
        INSTRUMENTS().map(([id, label]) =>
          h("button", { type: "button", class: s.inst === id ? "on" : "", "data-inst": id, "data-testid": "inst-" + id, onclick: () => app.setInstrument(id) }, label),
        ),
      );
    }

    function renderPath(s) {
      const stems = song.tracks.length > 1;
      const [t2, d2] = stems ? LEARN()[s.inst] : [W.t("Learn the chords"), W.t("The chart and your panel, with the full mix.")];
      const steps = [
        [W.t("Listen"), W.t("Full band, original tempo. Follow the chart.")],
        [t2, d2],
        [W.t("Loop it slow"), W.t("From 70% tempo, 5 BPM faster each pass.")],
        [W.t("Play along"), stems ? W.t("Your part is muted. The band is yours.") : W.t("The full mix, with a count-in.")],
      ];
      clear(
        $("path"),
        steps.map(([title, detail], i) =>
          h(
            "button",
            { type: "button", class: "step" + (s.step === i + 1 ? " on" : ""), "data-step": i + 1, "data-testid": "step-" + (i + 1), onclick: () => app.setStep(i + 1) },
            h("span", { class: "n" }, W.t("Step {n}", { n: i + 1 })),
            h("span", { class: "t" }, title),
            h("span", { class: "d" }, detail),
          ),
        ),
      );
    }

    function renderCredits() {
      const a = meta.analysis;
      const file = h("span", { translate: "no" }, meta.file);
      const lines = [
        W.nodes(W.t("Made with woodshed {version} from {file}, on this computer: nothing was uploaded.", { version: meta.meta.version }), { file }),
        a.stems
          ? a.beats === "beat_this"
            ? W.t("Instrument tracks separated with Demucs (MIT), beats and downbeats found with beat_this (MIT).")
            : W.t("Instrument tracks separated with Demucs (MIT).")
          : W.t("Analysed from the full mix only (no stems): instrument parts need woodshed with stems."),
        W.t("Notation drawn with VexFlow (MIT). Preview sounds: FluidR3_GM SoundFont by Frank Wen (MIT). Fonts: Barlow Condensed, Atkinson Hyperlegible, JetBrains Mono, Noto Music (SIL Open Font License)."),
      ];
      clear($("foot"), lines.map((l) => h("span", null, l)));
    }

    store.on((s, changed) => {
      if (changed.has("transpose") || changed.has("corrections") || changed.has("bandNote")) renderFacts(s);
      if (changed.has("inst")) renderInstruments(s);
      if (changed.has("inst") || changed.has("step")) renderPath(s);
    });

    return {
      render(s) {
        $("songTitle").textContent = meta.title;
        // Served by `woodshed app`: the library is one level up. Opened from disk, there is none.
        $("backLink").hidden = location.protocol === "file:";
        const pending = song.view.pending;
        if (pending) {
          const minutes = Math.max(1, Math.round(pending.eta_seconds / 60));
          $("pending").textContent = W.t(
            "Separating the instruments on this computer. Reload this page in about {n} min for the instrument tracks and parts; until then it plays the full mix.",
            { n: minutes },
          );
          $("pending").hidden = false;
        }
        renderFacts(s);
        renderInstruments(s);
        renderPath(s);
        renderCredits();
      },
      part: (inst) => PART[inst],
    };
  };

  W.views.stage = function stage(app) {
    const { song, store } = app;
    function render(s) {
      $("stage").hidden = !s.stage;
      if (!s.stage) return;
      const u = Math.floor(s.beat / song.per);
      const c = song.chordAtBeat(s.beat);
      const up = song.upcoming(s.beat, 2);
      const shift = app.showShapes(s) ? s.capo : 0;
      clear($("stNow"), chordNode(app.nameFor(c, shift, s)));
      const shapes = s.inst === "guitar" && app.shapeFor
        ? [[c, ""], [up[0], "next"]].filter(([x]) => x && x.pc >= 0).map(([x, cls]) => {
            const shape = app.shapeFor(x, s);
            return shape ? h("span", { class: cls, "aria-hidden": "true" }, app.guitarDiagram(shape), cls ? h("small", null, W.t("next")) : null) : null;
          })
        : [];
      clear($("stShape"), app.nowHint(c, s), shapes.length ? h("div", { class: "st-shapes", "data-testid": "stage-shapes" }, shapes) : null);
      clear($("stNext"), up[0] ? chordNode(app.nameFor(up[0], shift, s)) : W.t("end"));
      clear($("stThen"), up[1] ? chordNode(app.nameFor(up[1], shift, s)) : "");
      // Where the band is: the section, the bar in it, and the next section two bars ahead.
      const list = app.sections();
      const k = list.length ? song.sectionIndex(u, list) : -1;
      const sec = k >= 0 ? list[k] : { name: W.t("Bar {n}", { n: u + 1 }), start: u, end: u + 1 };
      const len = sec.end - sec.start;
      const per = Math.ceil(len / 16); // a dot per bar, or per few bars in a long section
      const at = Math.floor((u - sec.start) / per);
      clear($("stMap"), Array.from({ length: Math.ceil(len / per) }, (_, i) => h("i", { class: i === at ? "on" : i < at ? "done" : "" })));
      $("stSection").textContent = W.partName(sec);
      // The recording in another key (views/pitch.js) is said on the stand too.
      const shifted = s.pitchStatus && s.pitchStatus.state === "on" ? " · ♪ " + (s.transpose > 0 ? "+" : "−") + Math.abs(s.transpose) : "";
      $("stTop").textContent = W.t("bar {n} of {len}", { n: u - sec.start + 1, len }) + " · " + s.bpm + " BPM" + shifted;
      const next = k >= 0 ? list[k + 1] : null;
      const left = sec.end - u;
      const what = next ? W.partName(next) : k >= 0 && k === list.length - 1 ? W.t("End") : "";
      // The next part two bars ahead; stopped earlier in a part, what comes next, to be ready for it.
      const soon = left <= 2 ? (left === 1 ? W.t("{part} next bar", { part: what }) : W.t("{part} in {n} bars", { part: what, n: left })) : "";
      $("stComing").textContent = !what ? "" : soon || (!s.playing ? W.t("Next part: {part}", { part: what }) : "");
      renderLyrics(s, list);
    }

    // The words on the stand: the line sung now, a bar showing how far into it, then the next
    // lines, with the name of the part they start. The singer gets them full width; guitar and
    // keys next to the chords; bass and drums keep the chords and the bars.
    function renderLyrics(s, list) {
      const box = $("stLyrics");
      const words = app.words && app.sheetMode(s) === "lyrics" && s.inst !== "bass" && s.inst !== "drums";
      $("stage").classList.toggle("st-lyrics", !!words && s.inst !== "voice");
      $("stage").classList.toggle("st-voice", !!words && s.inst === "voice");
      box.hidden = !words;
      if (!words) return;
      const { rows } = app.words.rows();
      const at = app.lineNow(s);
      const k = at.now;
      // Between lines (a solo), no line is lit: the next ones wait, with the part they start.
      const from = k >= 0 ? k : at.next;
      const shown = rows.slice(from, from + 3);
      const out = [];
      shown.forEach((r, i) => {
        const sec = app.sectionOf(r.firstBar);
        const before = i > 0 ? app.sectionOf(shown[i - 1].firstBar) : app.sectionOf(Math.floor(s.beat / song.per));
        if (sec && before && sec.name !== before.name) out.push(h("div", { class: "st-next-part" }, W.partName(sec)));
        const now = i === 0 && k >= 0;
        out.push(h("div", { class: "st-line" + (now ? " now" : " later"), "data-testid": "stage-line" }, app.lyricLine(r, s, { stage: true })));
        if (now) {
          const span = Math.max(0.1, (rows[k + 1] ? rows[k + 1].line.start : r.line.end) - r.line.start);
          const done = Math.max(0, Math.min(1, (s.time - r.line.start) / span));
          out.push(h("div", { class: "st-progress", "aria-hidden": "true" }, h("i", { style: { width: (done * 100).toFixed(1) + "%" } })));
        }
      });
      clear(box, out);
    }
    store.on((s, changed) => {
      const keys = ["beat", "playing", "transpose", "capo", "pos", "bpm", "inst", "sheet", "view", "corrections", "pitchStatus"];
      if (changed.has("stage") || (s.stage && keys.some((key) => changed.has(key)))) render(s);
    });
    return { render };
  };

  // Toast, menus and the doubt pop share one place and one way to close (Escape, click outside).
  W.views.popups = function popups(app) {
    const { song } = app;
    let toastTimer = 0;

    // `action`: {label, run}, a button in the toast (Undo), kept longer on screen.
    function toast(message, action) {
      const t = $("toast");
      clear(t, message, action ? h("button", { type: "button", class: "undo", "data-testid": "toast-action", onclick: () => {
        t.hidden = true;
        action.run();
      } }, action.label) : null);
      t.hidden = false;
      clearTimeout(toastTimer);
      // Kept while the keyboard is on its button (Undo).
      const hide = () => (t.contains(document.activeElement) ? (toastTimer = setTimeout(hide, 2000)) : (t.hidden = true));
      toastTimer = setTimeout(hide, action ? 8000 : 2600);
    }

    let opener = null;
    // restoreFocus: after Escape, the keyboard goes back to the control that opened the panel.
    function closeAll(restoreFocus) {
      const open = [...document.querySelectorAll(".menu, #pop")].some((m) => !m.hidden);
      document.querySelectorAll(".menu").forEach((m) => (m.hidden = true));
      $("pop").hidden = true;
      if (open && restoreFocus && opener && document.contains(opener)) opener.focus();
      if (open) opener = null;
    }

    function place(el, anchor, below) {
      const r = anchor.getBoundingClientRect();
      const w = el.offsetWidth;
      const hh = el.offsetHeight;
      const left = Math.min(Math.max(16, below ? r.left : r.right - w), window.innerWidth - w - 16);
      let top = below || r.top < window.innerHeight / 2 ? r.bottom + 8 : r.top - hh - 8;
      if (top + hh > window.innerHeight - 16) top = Math.max(16, r.top - hh - 8);
      el.style.left = left + "px";
      el.style.top = Math.max(16, top) + "px";
    }

    function openMenu(id, anchor) {
      const m = $(id);
      const wasOpen = !m.hidden;
      closeAll();
      if (wasOpen) return;
      m.hidden = false;
      opener = anchor;
      place(m, anchor, false);
      const f = m.querySelector("button, input");
      if (f) f.focus();
    }

    // The chord the chart shows comes from the whole song (what comes before and after, the key, the
    // same part played again); the shares come from this bar heard alone. When they disagree, say so,
    // and keep the analysis's chord in the list: a correction can always go back to it.
    function openDoubt(button) {
      const [u, k] = button.getAttribute("data-ref").split("_").map(Number);
      const chord = song.bars[u].chords[k];
      const s = app.store.get();
      const same = song.same;
      const analysed = app.analysedChord(chord.doubt.id) || chord;
      const alts = chord.doubt.alternatives.slice();
      if (!alts.some((a) => same(a, analysed))) alts.push({ pc: analysed.pc, quality: analysed.quality, share: null });
      const node = (c) => W.chordNode(app.nameFor(c, 0, s));
      const named = (c) => W.prettyText(app.nameFor(c, 0, s));
      let note;
      if (chord.fixed && same(chord, analysed)) note = W.nodes(W.t("You confirmed {chord}, the analysis's chord."), { chord: node(chord) });
      else if (chord.fixed) note = W.nodes(W.t("Your correction: {chord}. The analysis had {analysed}."), { chord: node(chord), analysed: node(analysed) });
      else if (same(alts[0], analysed)) note = W.t(chord.doubt.why); // one of the analysis's texts, in core/i18n-fr.js
      else {
        note = W.nodes(W.t("The chart keeps {chord}: the bars around it point to it. Heard alone, this bar sounds more like {top}."), {
          chord: node(analysed),
          top: node(alts[0]),
        });
      }
      const pop = $("pop");
      clear(
        pop,
        h("h3", { id: "popTitle" }, W.t("Bar {n}: which one do you hear?", { n: u + 1 })),
        h("p", { "data-testid": "doubt-note" }, note),
        alts.map((alt, i) => {
          const tag = chord.fixed && same(alt, chord) ? W.t("yours") : same(alt, analysed) ? W.t("analysis") : null;
          const inUse = chord.fixed && same(alt, chord);
          const keep = !chord.fixed && same(alt, analysed); // the chart's chord, confirmed by ear
          return h(
            "div",
            { class: "alt" + (inUse ? " in-use" : ""), "data-testid": "alternative" },
            h("span", { class: "an" }, node(alt), tag ? h("span", { class: "tag" }, tag) : null),
            h("span", { class: "meter" }, alt.share === null ? null : h("i", { style: { width: alt.share + "%" } })),
            h("span", { class: "pc" }, alt.share === null ? "–" : W.t("{n}%", { n: alt.share })),
            h(
              "span",
              { class: "acts" },
              h("button", { type: "button", "aria-label": W.t("Hear {chord} in this bar", { chord: named(alt) }), "data-testid": "hear-alternative", onclick: () => app.audition(u, alt) }, "▶"),
              h(
                "button",
                {
                  type: "button", class: "pick", disabled: inUse ? "" : null, "data-testid": i === 0 ? "pick-first" : "pick", onclick: () => app.correct(u, k, alt),
                  "aria-label": keep ? W.t("Keep {chord}", { chord: named(alt) }) : W.t("Use {chord}", { chord: named(alt) }),
                },
                inUse ? W.t("In use") : keep ? W.t("Keep") : W.t("Use"),
              ),
            ),
          );
        }),
        chord.fixed
          ? h("p", { class: "pop-reset" }, h("button", {
              type: "button", class: "btn", "data-testid": "doubt-reset", onclick: () => app.uncorrect(chord.doubt.id),
              "aria-label": W.t("Back to the analysis: {chord}, to check by ear", { chord: named(analysed) }),
            }, W.t("Back to the analysis")))
          : null,
        h("p", null, W.t("▶ plays this bar of the recording with the candidate chord over it. Pick what matches your ear.")),
      );
      pop.hidden = false;
      opener = button;
      button.scrollIntoView({ block: "nearest" }); // a chord half off screen: the pop sits by it, not at the top
      place(pop, button, true);
      const f = pop.querySelector(".pick:not([disabled])") || pop.querySelector("button");
      if (f) f.focus();
    }
    // A dialog keeps the keyboard: Tab from its last button comes back to its first, and Shift+Tab
    // the other way; Escape closes it (app.js).
    $("pop").addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      const list = [...$("pop").querySelectorAll("button:not([disabled])")];
      if (!list.length) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    });

    return { toast, closeAll, openMenu, openDoubt };
  };
})();
