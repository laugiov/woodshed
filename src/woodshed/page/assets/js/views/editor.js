// Editing the chart: the strip under the chart's toolbar, and the bar editor (a dialog by the bar, a
// sheet on a phone). The chords typed are kept by app.typeBars (core/edits.js, core/keyed.js).
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear } = W;
  const PHONE = window.matchMedia("(max-width: 600px)");
  const INSERTS = ["#", "b", "/", ".", "N.C.", "%"];
  const SHOWN = { "#": "♯", b: "♭" };

  W.views.editor = function editor(app, chart) {
    const { song, store } = app;
    const meta = song.song;
    let open = null; // the bar being edited
    let opener = null;

    // A refusal, said in words; chords.json's codes, the root as typed.
    function why(error, token) {
      const root = token ? (/^[A-Ga-g][#♯b♭]?/.exec(token) || [""])[0].replace(/^./, (x) => x.toUpperCase()) : "";
      const say = {
        empty: () => W.t("Type the chords of the bar, for example G or D/F#."),
        "too-many": () => W.t("More chords than beats in this bar."),
        beats: () => W.t("With a dot or a slash, one sign a beat: {n} in this bar.", { n: song.per }),
        "nothing-before": () => W.t("Nothing before this bar to hold or repeat."),
        "bar-line": () => W.t("One bar at a time."),
        "maj-alone": () => W.t("{root}maj7 or {root}?", { root }),
        two: () => W.t("{root}sus2 or {root}add9?", { root }),
        "six-nine": () => W.t("{root}6/9 is not drawn here: {root}6.", { root }),
        altered: () => W.t("Altered chords are not drawn here: write the plain chord ({root}7).", { root }),
        unknown: () => W.t("Not a chord this page can draw."),
      };
      const text = (say[error] || say.unknown)();
      return token ? W.t("{token}: {why}", { token, why: text }) : text;
    }

    // The bar's chords in chart notation: one name a chord when they share the bar evenly, else one
    // sign a beat, a dot holding the chord before.
    function notation(u) {
      const s = store.get();
      const chords = song.bars[u].chords;
      const name = (c) => (c.pc < 0 ? "N.C." : W.prettyText(app.nameFor(c, 0, s)).replace(/♯/g, "#").replace(/♭/g, "b"));
      const even = chords.every((c) => c.beats === chords[0].beats) && song.per % chords.length === 0;
      if (even) return chords.map(name).join(" ");
      return chords.flatMap((c) => [name(c), ...Array(c.beats - 1).fill(".")]).join(" ");
    }

    // The label a typed chord is shown with, in the key on screen.
    const shown = (label) => W.prettyText(app.nameFor(W.chords.parse(label), 0, store.get()));

    // "D/F♯ for 2 beats, F♯ in the bass, then G for 2".
    function reading(chords) {
      const parts = chords.map(([n, label], k) => {
        const c = W.chords.parse(label);
        const name = h("b", null, shown(label));
        const beats = k === 0 ? (n === 1 ? W.t("for 1 beat") : W.t("for {n} beats", { n })) : n === 1 ? W.t("for 1") : W.t("for {n}", { n });
        const bass = c.bass === null || c.bass === undefined ? null : W.t("{note} in the bass", { note: W.prettyText(song.noteName(c.bass, store.get().transpose)) });
        return [name, " ", beats, bass ? [", ", bass] : null];
      });
      return parts.flatMap((p, k) => (k ? [W.t(", then "), p] : [p]));
    }

    // The same bar where this line is played again: the bars of the same column in lines alike.
    function repeats(u) {
      const b = song.bars[u];
      const g = meta.groups[b.group];
      const out = [];
      meta.groups.forEach((other) => {
        if (other.label !== g.label) return;
        for (const line of other.occurrences) if (line[b.column] !== undefined && line[b.column] !== u) out.push(line[b.column]);
      });
      return out;
    }
    const partOf = (u) => {
      const p = app.sectionOf(u);
      return p ? W.partName(p.name) : W.t("Bar {n}", { n: u + 1 });
    };
    function listOf(names) {
      if (names.length <= 1) return names.join("");
      return names.slice(0, -1).join(", ") + W.t(" and ") + names[names.length - 1];
    }

    // The analysis's doubt in this bar, if any: its candidates are one tap away.
    function doubtIn(u) {
      const bar = meta.bars[u];
      let at = 0;
      for (const c of bar.chords) {
        if (c.doubt && c.doubt.kind === "chord") return { chord: c, from: at };
        at += c.beats;
      }
      return null;
    }

    function close(restore) {
      $("barEd").hidden = true;
      $("edScrim").hidden = true;
      document.querySelectorAll(".ed-tail").forEach((t) => t.remove());
      open = null;
      if (restore && opener && document.contains(opener)) opener.focus({ preventScroll: true });
      opener = null;
    }

    function place(box, anchor) {
      document.querySelectorAll(".ed-tail").forEach((t) => t.remove());
      if (PHONE.matches) {
        $("edScrim").hidden = false;
        box.style.left = "";
        box.style.top = "";
        keepAboveKeyboard();
        return;
      }
      $("edScrim").hidden = true;
      box.style.bottom = "";
      // The bar near the top of the view first, so the editor opens under it with room to spare.
      const seen = window.innerHeight - ($("dock") ? $("dock").offsetHeight : 0);
      let r = anchor.getBoundingClientRect();
      if (r.bottom + 12 + box.offsetHeight > seen - 8) {
        window.scrollBy({ top: r.top - 140 });
        r = anchor.getBoundingClientRect();
      }
      const w = box.offsetWidth;
      const left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left + r.width / 2 - w / 2));
      const below = seen - 8 - (r.bottom + 12);
      const up = below < box.offsetHeight && r.top - 20 > below;
      box.style.left = left + "px";
      box.style.top = (up ? Math.max(8, r.top - 12 - box.offsetHeight) : r.bottom + 12) + "px";
      const tail = h("div", { class: "ed-tail" + (up ? " up" : ""), "aria-hidden": "true" });
      tail.style.left = r.left + r.width / 2 - 7 + "px";
      tail.style.top = (up ? r.top - 19 : r.bottom + 5) + "px";
      document.body.append(tail);
    }
    // On a phone the sheet stays above the keyboard.
    function keepAboveKeyboard() {
      const vv = window.visualViewport;
      $("barEd").style.bottom = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) + "px" : "0px";
    }
    if (window.visualViewport) window.visualViewport.addEventListener("resize", () => open !== null && PHONE.matches && keepAboveKeyboard());

    function openBar(u, from) {
      if (u < 0 || u >= song.bars.length) return close(true);
      open = u;
      opener = from || chart.barEl(u);
      const box = $("barEd");
      const field = h("input", {
        class: "field", type: "text", id: "barEdField", value: notation(u), "data-testid": "bar-field",
        autocapitalize: "off", autocorrect: "off", spellcheck: "false", autocomplete: "off", enterkeyhint: "done",
        "aria-label": W.t("Chords of the bar, one a beat"), "aria-describedby": "barEdRead",
      });
      const read = h("p", { class: "read", id: "barEdRead", "aria-live": "polite", "data-testid": "bar-reading" });
      const chips = h("div", { class: "chips" });
      const typed = app.typedBar(u);
      const others = repeats(u);
      const also = others.length
        ? h("input", { type: "checkbox", checked: "", "data-testid": "bar-also" })
        : null;
      const doubt = doubtIn(u);
      const previous = () => (u > 0 ? (app.typedBar(u - 1) || song.bars[u - 1].chords.map((c) => [c.beats, W.edits.label(c)])) : null);
      let parsed = null;
      function update() {
        parsed = W.edits.parseBar(field.value, song.per, previous());
        if (parsed.error) {
          const tokens = field.value.trim().split(/\s+/);
          read.className = "read warn";
          clear(read, why(parsed.error, parsed.at === undefined ? null : tokens[parsed.at]));
          field.setAttribute("aria-invalid", "true");
          clear(chips);
          return;
        }
        field.removeAttribute("aria-invalid");
        read.className = "read";
        clear(read, reading(parsed.chords));
        const seen = new Set();
        clear(
          chips,
          parsed.chords.filter(([, l]) => !seen.has(l) && seen.add(l) && l !== "N.C.").map(([, l]) =>
            h("button", { type: "button", class: "chip", "data-testid": "bar-hear-chord", "aria-label": W.t("Hear {chord} in this bar", { chord: shown(l) }), onclick: () => app.audition(u, W.chords.parse(l)) },
              W.chordNode(app.nameFor(W.chords.parse(l), 0, store.get())), h("i", { "aria-hidden": "true" }, "▶"))),
        );
      }
      field.addEventListener("input", update);
      field.addEventListener("keydown", (e) => {
        if (e.isComposing) return;
        if (e.key === "Enter") {
          e.preventDefault();
          save(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          close(true);
        }
      });
      function save(next) {
        if (!parsed || parsed.error) {
          field.focus();
          return;
        }
        const bars = [u, ...(also && also.checked ? others : [])];
        const shared = app.typeBars(bars, parsed.chords);
        const where = shared ? W.t("The band sees it on every device.") : W.t("This browser remembers it for this song.");
        app.toast(bars.length > 1 ? W.t("Saved: bar {n} and its {m} repeats. {where}", { n: u + 1, m: bars.length - 1, where }) : W.t("Saved: bar {n}. {where}", { n: u + 1, where }));
        if (next && u + 1 < song.bars.length) openBar(u + 1, chart.barEl(u + 1));
        else close(true);
      }
      // A candidate fills the beats of the doubt it answers.
      function fill(candidate) {
        const now = W.edits.parseBar(field.value, song.per, previous());
        const beats = (now.chords || song.bars[u].chords.map((c) => [c.beats, W.edits.label(c)])).flatMap(([n, l]) => Array(n).fill(l));
        for (let k = 0; k < doubt.chord.beats; k++) beats[doubt.from + k] = W.edits.label(candidate);
        field.value = beats.map((l, k) => (k && l === beats[k - 1] ? "." : shown(l).replace(/♯/g, "#").replace(/♭/g, "b"))).join(" ");
        update();
        field.focus();
      }
      const insert = (text) => {
        const at = field.selectionStart ?? field.value.length;
        const pad = text.length > 1 && at > 0 && field.value[at - 1] !== " " ? " " : "";
        field.value = field.value.slice(0, at) + pad + text + field.value.slice(field.selectionEnd ?? at);
        const caret = at + pad.length + text.length;
        field.setSelectionRange(caret, caret);
        update();
        field.focus();
      };
      clear(
        box,
        h("h3", { id: "barEdTitle" }, W.t("Bar {n}", { n: u + 1 }), h("small", null, W.t("{part} · {n} beats", { part: partOf(u), n: song.per }))),
        h("div", { class: "row" }, field, h("button", { type: "button", class: "btn hear-bar", "data-testid": "bar-play", onclick: () => app.playBar(u) }, "▶ ", W.t("This bar"))),
        PHONE.matches ? h("div", { class: "keys" }, INSERTS.map((k) => h("button", { type: "button", "aria-label": k, onclick: () => insert(k) }, SHOWN[k] || k))) : null,
        read,
        chips,
        doubt
          ? h("div", { class: "cands", "data-testid": "bar-candidates" }, h("span", null, W.t("Heard here")),
              doubt.chord.doubt.alternatives.map((a) => h("button", { type: "button", class: "cand", "data-testid": "bar-candidate", onclick: () => fill(a) },
                W.chordNode(app.nameFor(a, 0, store.get())), " ", h("small", null, W.t("{n}%", { n: a.share })))))
          : null,
        also ? h("label", { class: "also" }, also, W.t("Also {parts}, the same bar", { parts: listOf([...new Set(others.map(partOf))]) })) : null,
        h("p", { class: "tip" }, W.t("As on a chord sheet: Asus4, Cmaj7, Bdim, D/F#. A dot holds the chord, % repeats the bar before.")),
        h(
          "div",
          { class: "acts" },
          typed ? h("button", { type: "button", class: "back", "data-testid": "bar-untype", onclick: () => {
            app.untypeBar(u);
            app.toast(W.t("Bar {n} is the analysis's again.", { n: u + 1 }));
            close(true);
          } }, W.t("Back to the analysis")) : h("span"),
          h("span", { class: "right" },
            h("button", { type: "button", class: "btn", "data-testid": "bar-cancel", onclick: () => close(true) }, W.t("Cancel")),
            h("button", { type: "button", class: "btn", "data-testid": "bar-save", onclick: () => save(false) }, W.t("Save")),
            h("button", { type: "button", class: "btn primary", "data-testid": "bar-save-next", onclick: () => save(true) }, W.t("Save, next bar"))),
        ),
      );
      update();
      box.hidden = false;
      place(box, opener || document.body);
      field.focus({ preventScroll: true });
      field.select();
    }

    // The dialog keeps the keyboard; Escape anywhere in it closes it.
    $("barEd").addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close(true);
        return;
      }
      if (e.key !== "Tab") return;
      const list = [...$("barEd").querySelectorAll("button:not([disabled]), input")];
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
    $("edScrim").addEventListener("click", () => close(true));

    // Back to the analysis for everything typed: said first, undone in one tap.
    function untypeAll() {
      const bars = Object.keys(app.typedBars.values()).length;
      const parts = Object.keys(app.typedParts.values()).length;
      if (!bars && !parts) return app.toast(W.t("Nothing typed on this chart."));
      const ok = window.confirm(W.t("Take back {bars} typed bars and {parts} part names, for the whole band?", { bars, parts }));
      if (!ok) return;
      const undo = app.untypeAll();
      app.toast(W.t("The chart is the analysis's again."), { label: W.t("Undo"), run: undo });
    }

    function renderStrip(s) {
      const strip = $("editStrip");
      const shows = s.editing && !s.stage ? [W.lang()].join("|") : "";
      strip.hidden = !shows;
      document.body.classList.toggle("editing", !!shows);
      if (!shows || strip.dataset.shows === shows) return;
      strip.dataset.shows = shows;
      clear(
        strip,
        h("span", { class: "what" }, W.t("Editing the chart")),
        h("span", { class: "how" }, PHONE.matches ? W.t("Tap a bar to type its chords.") : W.t("Click a bar to type its chords.")),
        h("span", { class: "acts" },
          h("button", { type: "button", class: "btn ghost-link", "data-testid": "untype-all", onclick: untypeAll }, W.t("Back to the analysis…")),
          h("button", { type: "button", class: "btn primary", "data-testid": "edit-done", onclick: () => store.set({ editing: false }) }, W.t("Done"))),
      );
    }

    store.on((s, changed) => {
      if (changed.has("editing") || changed.has("stage")) {
        renderStrip(s);
        if (!s.editing) close(false);
      }
    });

    return {
      render: renderStrip,
      openBar,
      isOpen: () => open !== null,
    };
  };
})();
