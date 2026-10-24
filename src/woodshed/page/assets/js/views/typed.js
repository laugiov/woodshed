// Typing a line of the words by hand (spec 029): in the line editor's shell (#lineEd, views/popover.js), a line typed
// as a singer writes it under the bars, `|` before the word on beat one. The page reads it back as the library will
// (core/typed-words.js), the library reads it again, computes every time and shares it with the band (app.py
// set_words). A new line from "Type a line here" (an empty bar on the sheet, or the bar editor); a typed line from
// a tap on its words, Enter on it, or M (the move group first).
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, fmt } = W;
  const MOD = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘" : "Ctrl";
  // Keys a phone's keyboard hides behind its symbols page.
  const KEYS = [["|", "Bar line"], ["-", "Join two syllables"], ["_", "Hold a syllable"], ["(", "Backing vocal starts"], [")", "Backing vocal ends"]];
  const OVERLAP = "another typed line is sung there: move it or take it off first"; // woodshed.typed.OVERLAP

  W.views = W.views || {};

  W.views.typed = function typedView(app, chart, editor) {
    const { song } = app;
    const meta = song.song;
    const per = song.per;
    const TW = W.typedWords;
    const box = $("lineEd");
    const PHONE = W.popover.PHONE;
    let open = null; // the key of the line being typed

    const lines = () => (app.wordsData && Array.isArray(app.wordsData.lines) ? app.wordsData.lines : []);
    const lineOf = (key) => lines().find((ln) => ln && ln.key === key) || null;
    const lineEl = (key) => document.querySelector('#sheet .lline[data-key="' + key + '"]');
    const downbeat = (u) => meta.first_beat + u * per;
    const newKey = () => "t" + [...crypto.getRandomValues(new Uint8Array(4))].map((b) => b.toString(16).padStart(2, "0")).join("");
    const partName = (u) => {
      const sec = app.sectionOf(u);
      return sec ? W.partName(sec) : "";
    };

    // Where a word goes, as the read back says it: "on 1", "on the and of 2".
    function onBeat(at) {
      const off = at - downbeat(TW.barOf(meta, at));
      const b = Math.floor(off + 1e-6);
      const q = Math.round((off - b) * 4);
      const n = b + 1;
      if (q === 2) return W.t("on the and of {n}", { n });
      if (q === 1) return W.t("on {n} and a quarter", { n });
      if (q === 3) return W.t("on {n} and three quarters", { n });
      return W.t("on {n}", { n });
    }
    function reading(res) {
      const bars = new Map();
      for (const w of res.words) {
        const u = TW.barOf(meta, w.at);
        if (!bars.has(u)) bars.set(u, []);
        bars.get(u).push(W.t("“{word}” {beat}", { word: w.text, beat: onBeat(w.at) }));
      }
      return [...bars].map(([u, said]) => W.t("Bar {n}: {words}.", { n: u + 1, words: said.join(", ") })).join(" ");
    }
    function refusal(res) {
      if (res.error === "crowded") return W.t("Bar {n} holds more than four syllables a beat: put a | before the words of the next bar.", { n: res.bar });
      return W.t({
        empty: "Type the words of the line.",
        length: "200 characters at most.",
        bars: "A line holds 16 bars at most: start a new line.",
        words: "A line holds 40 words at most: start a new line.",
        end: "Past the song's last bar.",
      }[res.error] || res.error);
    }

    // The line read as the library will read it, and what it does to the lines around it.
    function read(text, at, key) {
      const old = lineOf(key);
      const entry = app.wordFixes()[key];
      const keep = entry && entry.typed ? { notation: entry.notation, words: entry.lines[0].words } : null;
      let res = TW.line(text, at, meta, keep, null);
      if (res.error) return { res };
      const s0 = res.words[0].start;
      const others = lines().filter((ln) => ln && ln.typed && ln.key !== key).map(TW.span).filter(Boolean);
      if (others.some(([a, b]) => a <= s0 && s0 < b)) return { res, overlap: true };
      const nxt = others.map(([a]) => a).filter((a) => a > s0).sort((a, b) => a - b)[0];
      if (nxt !== undefined) {
        res = TW.line(text, at, meta, keep, nxt);
        if (res.words.some((w) => w.start >= nxt)) return { res, overlap: true };
      }
      // The placed lines this one would hide (spec 029 B4): the placement with the band's fixes, without this line.
      const fixes = app.wordFixes();
      delete fixes[key];
      const base = app.placedWords ? W.wordEdits.apply(app.placedWords, fixes).lines : [];
      const span = TW.span(res);
      const covers = base.filter((ln) => ln && ln.sung && !ln.typed && TW.span(ln) && TW.span(ln)[0] < span[1] && span[0] < TW.span(ln)[1]);
      return { res, covers, old };
    }

    function close(restore) {
      const was = open;
      open = null;
      app.lines.close();
      const back = was === null ? null : lineEl(was);
      if (restore && back) back.focus({ preventScroll: true });
    }

    // `opts`: {wi, focus}: the word picked, and "move" (the move group), a button's test id, or the field.
    function openLine(key, at, opts) {
      if (!app.canFixWords()) return app.toast(W.t("Typing the words needs the library (woodshed app)."));
      opts = opts || {};
      app.lines.close();
      const entry = app.wordFixes()[key];
      const existing = !!(entry && entry.typed);
      const line = existing ? lineOf(key) : null;
      if (existing && !line) return;
      if (existing) at = downbeat(TW.barOf(meta, entry.lines[0].words[0].at));
      const first = at; // the bar it opened on: a pickup may start a bar or more earlier ("Start a bar earlier")
      let u = TW.barOf(meta, at);
      open = key;
      const start = existing ? entry.notation : "";
      const field = h("textarea", {
        class: "field", id: "lineEdField", rows: PHONE.matches ? "2" : "1", maxlength: "200", spellcheck: "false", translate: "no",
        autocomplete: "off", autocapitalize: "sentences", enterkeyhint: "done", "data-testid": "typed-field",
        "aria-label": existing ? W.t("Words of the typed line, bar lines included") : W.t("Words of the new line, from bar {n}", { n: u + 1 }),
        "aria-describedby": "typedRead typedTip",
      });
      field.value = start;
      // The read back is shown at once and said once typing pauses (a reading a keystroke is noise); a refusal is
      // said at once.
      const status = h("p", { class: "read", id: "typedRead", "data-testid": "typed-read" });
      const live = h("p", { class: "sr-only", "aria-live": "polite", "data-testid": "typed-say" });
      let pause = 0;
      const say = (text, warn) => {
        status.className = "read" + (warn ? " warn" : "");
        clear(status, text);
        clearTimeout(pause);
        if (warn) live.textContent = status.textContent;
        else pause = setTimeout(() => (live.textContent = status.textContent), 700);
      };
      let state = null;
      const update = () => {
        if (/[\r\n]/.test(field.value)) field.value = field.value.replace(/[\r\n]+/g, " ");
        grow();
        if (!field.value.trim()) {
          state = null;
          field.removeAttribute("aria-invalid");
          return say(W.t("The words start on beat one of bar {n}; type | before the word on beat one of the next bar.", { n: u + 1 }), false);
        }
        state = read(field.value, at, key);
        const bad = state.res.error || state.overlap;
        field.toggleAttribute("aria-invalid", !!bad);
        if (state.res.error) return say(refusal(state.res), true);
        if (state.overlap) return say(W.t("Another typed line is sung there: move it or take it off first."), true);
        // What it hides, in the warning colour after the reading (the reading itself is not a warning).
        const covers = state.covers.length === 1
          ? W.t("Covers the placed line “{words}”: hidden while this one is there.", { words: state.covers[0].text })
          : state.covers.length ? W.t("Covers {n} placed lines: hidden while this one is there.", { n: state.covers.length }) : null;
        say([reading(state.res), covers ? [" ", h("span", { class: "warn-text" }, covers)] : null], false);
      };
      const grow = () => {
        field.style.height = "auto";
        field.style.height = field.scrollHeight + (field.offsetHeight - field.clientHeight) + "px";
      };
      field.addEventListener("input", update);
      field.addEventListener("keydown", (e) => {
        if (e.isComposing) return;
        if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          if (!e.shiftKey) save(false);
        }
      });
      field.addEventListener("focus", () => box.classList.toggle("typing", PHONE.matches));
      field.addEventListener("blur", (e) => {
        if (e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest("[data-testid=typed-keys], [data-testid=line-more]")) return;
        setTimeout(() => document.activeElement !== field && box.classList.remove("typing"), 300);
      });
      const insert = (text) => {
        const from = field.selectionStart ?? field.value.length;
        const pad = text === "|" && from > 0 && field.value[from - 1] !== " " ? " " : "";
        field.value = field.value.slice(0, from) + pad + text + field.value.slice(field.selectionEnd ?? from);
        const caret = from + pad.length + text.length;
        field.setSelectionRange(caret, caret);
        update();
        field.focus();
      };
      const keys = h("div", { class: "wkeys", "data-testid": "typed-keys" },
        KEYS.map(([k, name]) => h("button", { type: "button", "aria-label": W.t(name), title: W.t(name), onpointerdown: (e) => e.preventDefault(), onclick: () => insert(k) }, k)));

      const busy = (on) => {
        for (const b of box.querySelectorAll("button")) b.disabled = on && !b.classList.contains("cancel");
      };
      const failed = (r) => {
        busy(false);
        const err = r.data && r.data.error;
        if (r.status === 0) say(W.t("The library did not answer: the line is not changed."), true);
        else if (err === OVERLAP) say(W.t("Another typed line is sung there: move it or take it off first."), true);
        else say(W.t(err || "the library refused it"), true);
        field.focus();
      };
      // The bar after this line: Ctrl or ⌘ + Enter goes on typing there.
      const after = (res) => {
        const v = TW.barOf(meta, res.words[res.words.length - 1].at) + 1;
        return v < song.bars.length ? v : null;
      };
      async function save(more) {
        const text = field.value.replace(/\s+/g, " ").trim();
        if (!state || state.res.error || state.overlap) {
          if (!text) say(W.t("Type the words of the line."), true);
          field.setAttribute("aria-invalid", "true");
          return field.focus();
        }
        const next = more ? after(state.res) : null;
        const goOn = () => {
          if (next !== null) openLine(newKey(), downbeat(next), {});
          else close(true);
        };
        if (existing && at === first && text === start.replace(/\s+/g, " ").trim()) return goOn(); // nothing changed: nothing sent
        busy(true);
        const tag = existing ? (entry.lines[0].tag || "") : partName(u);
        await app.lines.commit(key, { [key]: { typed: { text, at, tag } } },
          () => W.t("“{words}” saved.", { words: app.lineWords(key) }), goOn, failed,
          { [key]: existing ? { undo: true } : null });
      }
      const takeOff = async () => {
        const words = app.lineWords(key);
        busy(true);
        await app.lines.commit(key, { [key]: null }, () => W.t("“{words}” is off the sheet.", { words }), () => close(false), failed, { [key]: { undo: true } });
      };
      const reopen = (wi, focus) => openLine(key, null, { wi, focus: focus || "move" });
      const moves = existing ? app.moves.group(key, opts.wi === undefined ? 0 : opts.wi, reopen) : null;
      const whereText = () => (existing && at === first
        ? W.t("Typed line · {part} · {from} to {to}", { part: partName(u) || W.t("Bar {n}", { n: u + 1 }), from: fmt(line.words[0].start), to: fmt(line.words[line.words.length - 1].end) })
        : partName(u) ? W.t("{part} · from bar {n}", { part: partName(u), n: u + 1 }) : W.t("From bar {n}", { n: u + 1 }));
      const where = h("span", { class: "where-from" }, whereText());
      // A pickup (spec 029 review): the line starts a bar earlier than the bar it was opened on.
      const earlier = h("button", { type: "button", class: "back earlier", "data-testid": "typed-earlier", onclick: () => {
        if (u <= 0) return;
        at -= per;
        u -= 1;
        clear(where, whereText());
        earlier.disabled = u <= 0;
        update();
        field.focus();
      } }, W.t("Start a bar earlier"));
      earlier.disabled = u <= 0;
      const extra = h("div", { class: "extra", onfocusin: () => box.classList.remove("typing") },
        h("p", { class: "tip", id: "typedTip", "data-testid": "typed-tip" }, W.t("| is a bar line, before the word on beat one. Words between bar lines share the bar by syllables; - joins two syllables, _ holds one, (ooh) is a backing vocal.")),
        moves,
        PHONE.matches ? null : h("p", { class: "tip" }, W.t("Enter saves, {mod}+Enter saves and opens the next line.", { mod: MOD })));
      clear(
        box,
        h("h3", { id: "lineEdTitle" }, h("span", { translate: "no" }, existing ? app.lineWords(key) : W.t("New line")), h("small", null, where, " ", earlier)),
        h("div", { class: "row" }, field),
        keys,
        h("div", { class: "state" }, status, live),
        extra,
        h("div", { class: "acts" },
          h("span", { class: "left" },
            h("button", { type: "button", class: "btn more", "data-testid": "line-more", onclick: () => {
              box.classList.remove("typing");
              const first = extra.querySelector("button, select");
              if (first) first.focus();
            } }, W.t("More")),
            existing ? h("button", { type: "button", class: "back", "data-testid": "typed-off", onclick: takeOff }, W.t("Take this line off")) : null),
          h("span", { class: "right" },
            h("button", { type: "button", class: "btn cancel", "data-testid": "typed-cancel", onclick: () => close(true) }, W.t("Cancel")),
            h("button", { type: "button", class: "btn", "data-testid": "typed-save", title: W.t("Enter"), onclick: () => save(false) }, W.t("Save")),
            h("button", { type: "button", class: "btn primary", "data-testid": "typed-save-next", title: W.t("{mod}+Enter", { mod: MOD }), "aria-keyshortcuts": "Control+Enter Meta+Enter", onclick: () => save(true) }, W.t("Save, next line")))),
      );
      app.lines.shown(key, () => save(true), () => close(true));
      box.hidden = false;
      box.classList.remove("typing");
      document.body.classList.add("line-open");
      const anchor = (existing && lineEl(key)) || chart.barEl(u) || document.body;
      W.popover.place(box, anchor);
      update();
      const focus = opts.focus;
      const target = focus === "move" ? box.querySelector("[data-testid=move-word]") : focus ? box.querySelector('[data-testid="' + focus + '"]') : null;
      if (target) target.focus({ preventScroll: true });
      else {
        field.focus({ preventScroll: true });
        field.setSelectionRange(field.value.length, field.value.length);
      }
    }

    return {
      // A new line from bar u (an empty bar, or the bar editor's "Type a line here").
      openNew: (u) => openLine(newKey(), downbeat(u), {}),
      // A typed line, from its word tapped (that word picked), Enter on it, or M (the move group first).
      // On a phone a tapped word opens on the move group (no keyboard over the ruler): tap a word, then its slot.
      open: (key, word, move) => openLine(key, null, {
        wi: word && word.hasAttribute("data-wi") ? +word.getAttribute("data-wi") : 0,
        focus: move || (word && PHONE.matches) ? "move" : null,
      }),
      isOpen: () => open !== null,
      render() {},
    };
  };
})();
