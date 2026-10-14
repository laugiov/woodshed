// Header (title, facts, instrument), practice path, credits, stage mode, toast, menus, doubt pop.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, chordNode, fmt } = W;

  const INSTRUMENTS = [["guitar", "Guitar"], ["bass", "Bass"], ["piano", "Keys"], ["drums", "Drums"], ["voice", "Voice"]];
  const PART = { guitar: "guitar", bass: "bass", piano: "keys", drums: "drums", voice: "voice" };
  const LEARN = {
    guitar: ["Learn the shapes", "Your part alone. Click a shape to hear it."],
    bass: ["Learn the line", "The bass alone, with its tab."],
    piano: ["Learn the voicings", "The chords alone, as played on the record."],
    drums: ["Learn the groove", "The drums alone, with the notation."],
    voice: ["Find your key", "The voice alone. Set your voice type on the right."],
  };

  W.views = W.views || {};

  W.views.header = function header(app) {
    const { song, store } = app;
    const meta = song.song;

    function renderFacts(s) {
      const open = song.doubts().filter((d) => !d.chord.fixed);
      const spots = new Set(open.map((d) => d.chord.doubt.id)).size;
      const key = song.keyName(s.transpose);
      const minor = key.endsWith("m");
      clear(
        $("facts"),
        h("span", null, h("b", null, String(app.songBpm)), " BPM"),
        h("span", null, h("b", null, meta.beats_per_bar + "/4")),
        h("span", null, "Key ", h("b", null, chordNode(minor ? key.slice(0, -1) : key), minor ? " minor" : " major")),
        h("span", null, fmt(meta.duration)),
        spots
          ? h("button", { type: "button", class: "warnfact", "data-goto": open[0].bar, "data-testid": "spots" }, spots + " spot" + (spots > 1 ? "s" : "") + " to check by ear")
          : h("span", { class: "okfact" }, "Nothing to check by ear"),
        meta.analysis.chords_reliable ? null : h("span", { class: "warnfact", "data-testid": "unreliable" }, "Little harmony found: chords may be wrong"),
      );
    }

    function renderInstruments(s) {
      clear(
        $("instruments"),
        INSTRUMENTS.map(([id, label]) =>
          h("button", { type: "button", class: s.inst === id ? "on" : "", "data-inst": id, "data-testid": "inst-" + id, onclick: () => app.setInstrument(id) }, label),
        ),
      );
    }

    function renderPath(s) {
      const stems = song.tracks.length > 1;
      const [t2, d2] = stems ? LEARN[s.inst] : ["Learn the chords", "The chart and your panel, with the full mix."];
      const steps = [
        ["Listen", "Full band, original tempo. Follow the chart."],
        [t2, d2],
        ["Loop it slow", "From 70% tempo, 5 BPM faster each pass."],
        ["Play along", stems ? "Your part is muted. The band is yours." : "The full mix, with a count-in."],
      ];
      clear(
        $("path"),
        steps.map(([title, detail], i) =>
          h(
            "button",
            { type: "button", class: "step" + (s.step === i + 1 ? " on" : ""), "data-step": i + 1, "data-testid": "step-" + (i + 1), onclick: () => app.setStep(i + 1) },
            h("span", { class: "n" }, "Step " + (i + 1)),
            h("span", { class: "t" }, title),
            h("span", { class: "d" }, detail),
          ),
        ),
      );
    }

    function renderCredits() {
      const a = meta.analysis;
      const lines = [
        "Made with woodshed " + meta.meta.version + " from " + meta.file + ", on this computer: nothing was uploaded.",
        a.stems
          ? "Instrument tracks separated with Demucs (MIT)" + (a.beats === "beat_this" ? ", beats and downbeats found with beat_this (MIT)." : ".")
          : "Analysed from the full mix only (no stems): instrument parts need woodshed with stems.",
        "Notation drawn with VexFlow (MIT). Preview sounds: FluidR3_GM SoundFont by Frank Wen (MIT). Fonts: Barlow Condensed, Atkinson Hyperlegible, JetBrains Mono, Noto Music (SIL Open Font License).",
      ];
      clear($("foot"), lines.map((l) => h("span", null, l)));
    }

    store.on((s, changed) => {
      if (changed.has("transpose") || changed.has("corrections")) renderFacts(s);
      if (changed.has("inst")) renderInstruments(s);
      if (changed.has("inst") || changed.has("step")) renderPath(s);
    });

    return {
      render(s) {
        $("songTitle").textContent = meta.title;
        const pending = song.view.pending;
        if (pending) {
          const minutes = Math.max(1, Math.round(pending.eta_seconds / 60));
          $("pending").textContent =
            "Separating the instruments on this computer. Reload this page in about " + minutes + " min" +
            " for the instrument tracks and parts; until then it plays the full mix.";
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
      clear($("stShape"), app.nowHint(c, s));
      clear($("stNext"), up[0] ? chordNode(app.nameFor(up[0], shift, s)) : "end");
      clear($("stThen"), up[1] ? chordNode(app.nameFor(up[1], shift, s)) : "");
      const b = song.bars[u];
      const gr = song.song.groups[b.group];
      const len = gr.occurrences[b.occurrence].length;
      clear($("stMap"), Array.from({ length: len }, (_, k) => h("i", { class: k === b.column ? "on" : k < b.column ? "done" : "" })));
      const passes = gr.occurrences.length;
      $("stTop").textContent = "Bar " + (u + 1) + " · line " + gr.label + (passes > 1 ? ", pass " + (b.occurrence + 1) + " of " + passes : "") + " · " + s.bpm + " BPM";
    }
    store.on((s, changed) => {
      if (changed.has("stage") || (s.stage && (changed.has("beat") || changed.has("transpose") || changed.has("capo") || changed.has("bpm")))) render(s);
    });
    return { render };
  };

  // Toast, menus and the doubt pop share one place and one way to close (Escape, click outside).
  W.views.popups = function popups(app) {
    const { song } = app;
    let toastTimer = 0;

    function toast(message) {
      const t = $("toast");
      t.textContent = message;
      t.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => (t.hidden = true), 2600);
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

    function openDoubt(button) {
      const [u, k] = button.getAttribute("data-ref").split("_").map(Number);
      const chord = song.bars[u].chords[k];
      const s = app.store.get();
      const pop = $("pop");
      clear(
        pop,
        h("h3", null, "Which one do you hear?"),
        h("p", null, chord.doubt.why),
        chord.doubt.alternatives.map((alt, i) =>
          h(
            "div",
            { class: "alt", "data-testid": "alternative" },
            h("span", { class: "an" }, W.chordNode(app.nameFor(alt, 0, s))),
            h("span", { class: "meter" }, h("i", { style: { width: alt.share + "%" } })),
            h("span", { class: "pc" }, alt.share + "%"),
            h(
              "span",
              { class: "acts" },
              h("button", { type: "button", "aria-label": "Hear it in this bar", "data-testid": "hear-alternative", onclick: () => app.audition(u, alt) }, "▶"),
              h("button", { type: "button", class: "pick", "data-testid": i === 0 ? "pick-first" : "pick", onclick: () => app.correct(u, k, alt) }, "Use"),
            ),
          ),
        ),
        h("p", null, "▶ plays this bar of the recording with the candidate chord over it. Pick what matches your ear."),
      );
      pop.hidden = false;
      opener = button;
      place(pop, button, true);
      const f = pop.querySelector("button");
      if (f) f.focus();
    }

    return { toast, closeAll, openMenu, openDoubt };
  };
})();
