// Editing the chart: the strip under the chart's toolbar, and the bar editor (a dialog by the bar, a
// sheet on a phone). The chords typed are kept by app.typeBars (core/edits.js, core/keyed.js).
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear } = W;
  const PHONE = window.matchMedia("(max-width: 600px)");
  const INSERTS = ["#", "b", "/", ".", "N.C.", "%"];
  const SAID = { "#": "Sharp", b: "Flat", "/": "Hold the chord (slash)", ".": "Hold the chord (dot)", "N.C.": "No chord", "%": "The bar before" };
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
    // The editor works in the key on screen (the band's key, a singer's); the store keeps concert pitch,
    // like the analysis. A label moved by n semitones:
    const mod12 = (x) => ((x % 12) + 12) % 12;
    function moved(label, n) {
      const c = W.chords.parse(label);
      if (c.refused || c.pc < 0) return label;
      return W.edits.label({ pc: mod12(c.pc + n), quality: c.quality, bass: c.bass === null ? null : mod12(c.bass + n) });
    }
    const T = () => store.get().transpose;
    const concert = (label) => W.chords.parse(moved(label, -T()));
    // A label typed in the key on screen, named as the chart names it (the key's sharps or flats).
    let atBar = 0; // the bar open in the editor: a typed label is spelled in its key (spec 012)
    const shown = (label) => W.prettyText(app.nameFor(concert(label), 0, store.get(), atBar));
    const ascii = (text) => text.replace(/♯/g, "#").replace(/♭/g, "b");

    // "D/F♯ for 2 beats, F♯ in the bass, then G for 2".
    function reading(chords) {
      const parts = chords.map(([n, label], k) => {
        const c = W.chords.parse(label);
        const name = h("b", null, shown(label));
        const beats = k === 0 ? (n === 1 ? W.t("for 1 beat") : W.t("for {n} beats", { n })) : n === 1 ? W.t("for 1") : W.t("for {n}", { n });
        const real = concert(label);
        const bass = c.bass === null || c.bass === undefined ? null : W.t("{note} in the bass", { note: W.prettyText(song.noteName(real.bass, T())) });
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
      return p ? W.partName(p) : W.t("Bar {n}", { n: u + 1 });
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
      const was = open;
      $("barEd").hidden = true;
      $("edScrim").hidden = true;
      document.body.classList.remove("bar-open");
      document.querySelectorAll(".ed-tail").forEach((t) => t.remove());
      open = null;
      opener = null;
      // The keyboard back on the bar, as the chart draws it now (a save draws the chart again).
      const back = was === null ? null : chart.barEl(was);
      if (restore && back) back.focus({ preventScroll: true });
    }

    // `still`: placed again where the bar is now (scrolling), without scrolling the page itself.
    function place(box, anchor, still) {
      document.querySelectorAll(".ed-tail").forEach((t) => t.remove());
      if (PHONE.matches) {
        $("edScrim").hidden = false;
        box.style.left = "";
        box.style.top = "";
        keepAboveKeyboard();
        // The bar stays in sight, above the sheet.
        const r = anchor.getBoundingClientRect();
        const top = box.getBoundingClientRect().top;
        if (r.bottom > top - 8 || r.top < 0) window.scrollBy({ top: r.bottom - (top - 16) });
        return;
      }
      $("edScrim").hidden = true;
      box.style.bottom = "";
      // The bar near the top of the view first, so the editor opens under it with room to spare.
      const seen = window.innerHeight - ($("dock") ? $("dock").offsetHeight : 0);
      let r = anchor.getBoundingClientRect();
      if (!still && r.bottom + 12 + box.offsetHeight > seen - 8) {
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
    // On a phone the sheet stays above the keyboard, no taller than the screen left to it.
    function keepAboveKeyboard() {
      const vv = window.visualViewport;
      const box = $("barEd");
      box.style.bottom = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) + "px" : "0px";
      box.style.maxHeight = (vv ? vv.height : window.innerHeight) - 16 + "px";
    }
    // The keyboard rising pushes the sheet up: the bar is kept above it.
    function keepBarInSight() {
      const el = open === null ? null : chart.barEl(open);
      if (!el) return;
      const r = el.getBoundingClientRect();
      const top = $("barEd").getBoundingClientRect().top;
      if (r.bottom > top - 8 || r.top < 0) window.scrollBy({ top: r.bottom - (top - 16) });
    }
    if (window.visualViewport) {
      for (const ev of ["resize", "scroll"]) {
        window.visualViewport.addEventListener(ev, () => {
          if (open === null || !PHONE.matches) return;
          keepAboveKeyboard();
          if (ev === "resize") keepBarInSight();
        });
      }
    }
    // On a computer the dialog stays by its bar while the page scrolls or the window changes.
    let following = 0;
    const follow = () => {
      if (open === null || PHONE.matches || following) return;
      following = requestAnimationFrame(() => {
        following = 0;
        const el = open === null ? null : chart.barEl(open);
        if (el) place($("barEd"), el, true);
      });
    };
    window.addEventListener("scroll", follow, { passive: true });
    window.addEventListener("resize", follow);

    function openBar(u, from) {
      atBar = u;
      if (u < 0 || u >= song.bars.length) return close(true);
      open = u;
      opener = from || chart.barEl(u);
      const box = $("barEd");
      const field = h("input", {
        class: "field", type: "text", id: "barEdField", value: notation(u), "data-testid": "bar-field",
        autocapitalize: "off", autocorrect: "off", spellcheck: "false", autocomplete: "off", enterkeyhint: "next",
        "aria-label": W.t("Chords of the bar, one a beat"), "aria-describedby": "barEdRead",
      });
      const read = h("p", { class: "read", id: "barEdRead", "aria-live": "polite", "data-testid": "bar-reading" });
      const chips = h("div", { class: "chips" });
      const typed = app.typedBar(u);
      const others = repeats(u);
      // On by default, unless a repeat was typed otherwise already (it would be overwritten).
      const mine = JSON.stringify(typed);
      const clash = others.some((v) => app.typedBar(v) && JSON.stringify(app.typedBar(v)) !== mine);
      const also = others.length
        ? h("input", { type: "checkbox", checked: clash ? null : "", "data-testid": "bar-also" })
        : null;
      const doubt = doubtIn(u);
      // The bar before, in the key on screen (what "%" and a leading hold take).
      const previous = () =>
        u > 0 ? (app.typedBar(u - 1) || song.bars[u - 1].chords.map((c) => [c.beats, W.edits.label(c)])).map(([n, l]) => [n, moved(l, T())]) : null;
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
            h("button", { type: "button", class: "chip", "data-testid": "bar-hear-chord", "aria-label": W.t("Hear {chord} in this bar", { chord: shown(l) }), onclick: () => app.audition(u, concert(l)) },
              W.chordNode(app.nameFor(concert(l), 0, store.get(), u)), h("i", { "aria-hidden": "true" }, "▶"))),
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
        // Walking through bars with Enter types nothing that was not changed (a bar with a chord to check
        // is the exception: Enter there confirms it).
        const onScreen = JSON.stringify(song.bars[u].chords.map((c) => [c.beats, moved(W.edits.label(c), T())]));
        const unchanged = !typed && !doubt && JSON.stringify(parsed.chords) === onScreen;
        let said = null;
        if (!unchanged) {
          const bars = [u, ...(also && also.checked ? others : [])];
          const shared = app.typeBars(bars, parsed.chords.map(([n, l]) => [n, moved(l, -T())])); // kept in concert pitch
          const where = shared ? W.t("The band sees it on every device.") : W.t("This browser remembers it for this song.");
          said = bars.length > 1 ? W.t("Saved: bar {n} and its {m} repeats. {where}", { n: u + 1, m: bars.length - 1, where }) : W.t("Saved: bar {n}. {where}", { n: u + 1, where });
        }
        if (next && u + 1 < song.bars.length) openBar(u + 1, chart.barEl(u + 1));
        else close(true);
        if (said) app.toast(said); // after the sheet closed: the note does not jump on a phone
      }
      // A candidate fills the beats of the doubt it answers.
      function fill(candidate) {
        const now = W.edits.parseBar(field.value, song.per, previous());
        const shownNow = now.chords || song.bars[u].chords.map((c) => [c.beats, moved(W.edits.label(c), T())]);
        const beats = shownNow.flatMap(([n, l]) => Array(n).fill(l));
        for (let k = 0; k < doubt.chord.beats; k++) beats[doubt.from + k] = moved(W.edits.label(candidate), T());
        field.value = beats.map((l, k) => (k && l === beats[k - 1] ? "." : ascii(shown(l)))).join(" ");
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
        h("div", { class: "row" }, field, hearBar(u)),
        PHONE.matches ? h("div", { class: "keys" }, INSERTS.map((k) => h("button", { type: "button", "aria-label": W.t(SAID[k]), onclick: () => insert(k) }, SHOWN[k] || k))) : null,
        read,
        chips,
        doubt
          ? h("div", { class: "cands", "data-testid": "bar-candidates" }, h("span", null, W.t("Heard here")),
              doubt.chord.doubt.alternatives.map((a) => h("button", { type: "button", class: "cand", "data-testid": "bar-candidate", onclick: () => fill(a) },
                W.chordNode(app.nameFor(a, 0, store.get(), u)), " ", h("small", null, W.t("{n}%", { n: a.share })))))
          : null,
        also ? h("label", { class: "also" }, also, W.t("Also {parts}, the same bar", { parts: listOf([...new Set(others.map((v) => (partOf(v) === partOf(u) ? W.t("{part}, played again", { part: partOf(v) }) : partOf(v))))]) })) : null,
        startPart(u),
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
      document.body.classList.add("bar-open");
      place(box, opener || document.body);
      field.focus({ preventScroll: true });
      field.select();
    }

    // ▶ This bar: a press plays it once; held down, it loops until released.
    function hearBar(u) {
      let held = null;
      let looped = false;
      const stop = () => {
        clearTimeout(held);
        held = null;
        if (looped) app.stopBarLoop();
      };
      return h("button", {
        type: "button", class: "btn hear-bar", "data-testid": "bar-play",
        onpointerdown: () => {
          looped = false;
          held = setTimeout(() => {
            looped = true;
            app.loopBar(u);
          }, 400);
        },
        onpointerup: stop,
        onpointerleave: stop,
        onpointercancel: stop,
        onclick: () => {
          if (!looped) app.playBar(u);
          looped = false;
        },
      }, "▶ ", W.t("This bar"));
    }

    // A part starting on this bar, named on the spot (the parts and their lines follow).
    function startPart(u) {
      const name = h("input", { class: "part-start-name", type: "text", maxlength: "40", hidden: "", "data-testid": "part-start-name",
        "aria-label": W.t("Name of the part starting at bar {n}", { n: u + 1 }), placeholder: W.t("Bridge, Tag, Solo…") });
      // A bar that already starts a part: the same field renames it.
      const part = app.sectionOf(u);
      const starts = !!part && part.start === u;
      if (starts) name.value = W.partName(part);
      const go = h("button", { type: "button", class: "btn", "data-testid": "part-start", onclick: () => {
        if (name.hidden) {
          name.hidden = false;
          name.focus();
          return;
        }
        if (!name.value.trim()) return name.focus();
        if (starts && name.value.trim() === W.partName(part)) return close(true); // unchanged: nothing typed
        app.namePart(u, name.value);
        close(true);
        app.toast(starts ? W.t("The part at bar {n} is renamed.", { n: u + 1 }) : W.t("A part starts at bar {n}.", { n: u + 1 }));
      } }, starts ? W.t("Rename the part") : W.t("Start a part here"));
      name.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          e.stopPropagation();
          go.click();
        }
      });
      return h("div", { class: "part-start" }, go, name);
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
      const typed = [bars === 1 ? W.t("1 typed bar") : W.t("{n} typed bars", { n: bars }), parts === 1 ? W.t("1 part name") : W.t("{n} part names", { n: parts })];
      const ok = window.confirm(W.t("Take back {what}, for the whole band?", { what: typed.join(W.t(" and ")) }));
      if (!ok) return;
      const undo = app.untypeAll();
      app.toast(W.t("The chart is the analysis's again."), { label: W.t("Undo"), run: undo });
    }

    function renderStrip(s) {
      const strip = $("editStrip");
      const shows = s.editing && !s.stage ? [W.lang(), s.corrections].join("|") : "";
      strip.hidden = !shows;
      document.body.classList.toggle("editing", !!shows);
      if (!shows || strip.dataset.shows === shows) return;
      strip.dataset.shows = shows;
      clear(
        strip,
        h("span", { class: "what" }, W.t("Editing the chart")),
        h("span", { class: "how" }, PHONE.matches ? W.t("Tap a bar to type its chords.") : W.t("Click a bar to type its chords.")),
        h("span", { class: "acts" },
          Object.keys(app.typedParts.values()).length
            ? h("button", { type: "button", class: "btn ghost-link", "data-testid": "untype-parts", onclick: () => {
                const n = Object.keys(app.typedParts.values()).length;
                if (!window.confirm(W.t("Take back {what}, for the whole band?", { what: n === 1 ? W.t("1 part name") : W.t("{n} part names", { n }) }))) return;
                const undo = app.untypeParts();
                app.toast(W.t("The parts are the analysis's again."), { label: W.t("Undo"), run: undo });
              } }, W.t("Parts back to the analysis"))
            : null,
          h("button", { type: "button", class: "btn", "data-testid": "bar-lines", "aria-haspopup": "dialog", onclick: () => app.openBarLines() }, W.t("Bar lines…")),
          h("button", { type: "button", class: "btn ghost-link", "data-testid": "untype-all", onclick: untypeAll }, W.t("Back to the analysis…")),
          h("button", { type: "button", class: "btn primary", "data-testid": "edit-done", onclick: () => store.set({ editing: false }) }, W.t("Done"))),
      );
    }

    store.on((s, changed) => {
      if (changed.has("editing") || changed.has("stage") || changed.has("corrections")) {
        renderStrip(s);
        if (!s.editing || s.stage) close(false);
      }
    });

    return {
      render: renderStrip,
      openBar,
      isOpen: () => open !== null,
    };
  };
})();
