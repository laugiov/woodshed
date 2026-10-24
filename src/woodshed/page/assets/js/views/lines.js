// Fixing a line of the words on the sheet (spec 028): the line editor, under the line on a computer, a sheet
// over the keyboard on a phone (the bar editor's shell, views/popover.js). The library places only that line
// again, in its own window, and shares it with the band (app.py set_words); nothing is placed here.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, fmt } = W;
  const MOD = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘" : "Ctrl";
  const SPREAD = "spread over the line's time, not heard: listen to it"; // lyrics.SPREAD_CHECK

  W.views = W.views || {};

  W.views.lines = function lines(app, chart, editor) {
    const { song, store } = app;
    const box = $("lineEd");
    const PHONE = W.popover.PHONE;
    let open = null; // the index of the line being edited, in lyrics.json
    let undo = null; // {n, change}: the line as it was before the last change made here

    const rowOf = (i) => (app.words ? app.words.rows().rows.find((r) => r.line.index === i) : null) || null;
    const lineEl = (i) => document.querySelector('#sheet .lline[data-index="' + i + '"]');
    const placedText = (i) => app.placedWords.lines[i].text;
    // The line as the library has it, as the editor asks for it: its words, another voice, gone, or as placed.
    function asked(i) {
      const e = app.wordFixes()[i];
      if (!e) return null;
      if (e.gone) return { gone: "not-sung" };
      const text = e.lines ? e.lines[0].text : placedText(i);
      return e.voice === "other" ? { text, voice: "other" } : { text };
    }
    // The words in the field: the line's text, its backing vocals in brackets when the text has none.
    function fieldText(line) {
      const backing = Array.isArray(line.backing) ? line.backing.filter((b) => typeof b === "string" && b) : [];
      return backing.length && !line.text.includes("(") ? line.text + " (" + backing.join(") (") + ")" : line.text;
    }

    function close(restore) {
      const was = open;
      box.hidden = true;
      $("edScrim").hidden = true;
      document.body.classList.remove("line-open");
      document.querySelectorAll(".ed-tail").forEach((t) => t.remove());
      open = null;
      const back = was === null ? null : lineEl(was);
      if (restore && back) back.focus({ preventScroll: true });
    }

    // The library's answer to a change: the fixes of this placement, drawn at once.
    async function send(change) {
      const r = await app.shareWords(change);
      if (r.ok) app.useWordEdits(r.data.lines, true);
      return r;
    }

    // A change made here: sent, then the toast with Undo (kept in the strip until the next change).
    async function commit(i, change, said, after, status) {
      const before = {};
      for (const k of Object.keys(change)) before[k] = asked(+k);
      const r = await send(change);
      if (!r.ok) {
        if (status) status(r);
        else app.toast(r.status === 0 ? W.t("The library did not answer: the line is not changed.") : W.t(r.data.error || "the library refused it"));
        return false;
      }
      undo = { n: i, change: before };
      store.set({ corrections: store.get().corrections + 1 }); // the strip shows Undo
      if (after) after();
      app.toast(said(r.data), { label: W.t("Undo"), run: runUndo });
      return true;
    }
    async function runUndo() {
      if (!undo) return false;
      const was = undo;
      undo = null;
      const r = await send(was.change);
      if (!r.ok) {
        undo = was;
        app.toast(W.t("The library did not answer: the line is not changed."));
      }
      store.set({ corrections: store.get().corrections + 1 });
      const el = was.n === null ? null : lineEl(was.n);
      if (el) el.focus({ preventScroll: true });
      return true;
    }
    app.wordsUndo = () => !!undo && store.get().editing;
    app.undoWords = () => {
      if (!undo) return false;
      runUndo();
      return true;
    };

    // What a saved line says: saved, and what to listen to (a number, a line spread over its time).
    function savedText(i, data) {
      const e = data.lines[i];
      const out = [W.t("Line {n} saved.", { n: i + 1 })];
      const line = e && e.lines ? e.lines[0] : null;
      const number = line && line.words.find((w) => w.start === null && /\d/.test(w.text));
      if (number) out.push(W.t("{word} is not heard: write numbers as words.", { word: number.text }));
      if (line && line.check === SPREAD) out.push(W.t("Spread over the line's time, not heard: listen to it."));
      return out.join(" ");
    }

    // ▶ This line: the bars that hold it, once.
    function hearLine(r) {
      const first = r.bars[0].bar;
      const last = r.bars[r.bars.length - 1].bar;
      return h("button", { type: "button", class: "btn hear-bar", "data-testid": "line-play", onclick: () => app.playBars(first, last - first + 1) }, "▶ ", W.t("This line"));
    }

    // The chords of the line's bars: each opens the bar editor on its bar (its repeats, its candidates as today).
    function chips(r) {
      const s = store.get();
      return r.bars.filter((b) => !b.cont).map((b) => {
        const names = song.bars[b.bar].chords.map((c) => W.prettyText(app.nameFor(c, 0, s, b.bar)));
        return h("button", {
          type: "button", class: "bar-chip", "data-testid": "line-bar",
          "aria-label": W.t("Bar {n}: {chords}", { n: b.bar + 1, chords: names.join(", ") }),
          onclick: () => {
            const i = open;
            close(false);
            const line = lineEl(i);
            const nb = line && line.querySelector('.nb[data-bar="' + b.bar + '"]');
            editor.openBar(b.bar, nb || line || chart.barEl(b.bar));
          },
        }, W.t("Bar {n}", { n: b.bar + 1 }), " ", h("b", { translate: "no" }, names.join(" ")), " ", h("i", { "aria-hidden": "true" }, "✎"));
      });
    }

    function openLine(i, word) {
      if (!app.canFixWords()) return app.toast(W.t("Fixing a line's words needs the library (woodshed app)."));
      const r = rowOf(i);
      if (!r) return close(false);
      if (open !== null) close(false);
      open = i;
      const line = r.line;
      const entry = app.wordFixes()[i];
      const other = line.voice === "other";
      const start = fieldText(line);
      const field = h("textarea", {
        class: "field", id: "lineEdField", rows: PHONE.matches ? "2" : "1", maxlength: "200", spellcheck: "false", translate: "no",
        autocomplete: "off", enterkeyhint: "done", "data-testid": "line-field", "aria-label": W.t("Words of line {n}", { n: i + 1 }), "aria-describedby": "lineEdStatus",
      });
      field.value = start;
      const status = h("p", { class: "read", id: "lineEdStatus", "aria-live": "polite", "data-testid": "line-status" },
        W.t("Only this line is placed again, between {from} and {to}. The lines around it do not move.", { from: fmt(line.start), to: fmt(line.end) }));
      const retry = h("button", { type: "button", class: "btn", hidden: "", "data-testid": "line-retry", onclick: () => save(false) }, W.t("Retry"));
      const say = (text, warn) => {
        status.className = "read" + (warn ? " warn" : "");
        clear(status, text);
      };
      // A failure said in the editor, the text kept: offline (Retry), no room, the words placed again meanwhile.
      const failed = (res) => {
        busy(false);
        if (res.status === 0) {
          say(W.t("The library did not answer: the line is not changed."), true);
          retry.hidden = false;
          return;
        }
        const w = res.data && Array.isArray(res.data.window) ? res.data.window : null;
        if (w) {
          field.setAttribute("aria-invalid", "true");
          say(W.t("Not enough time for these words between {from} and {to}.", { from: fmt(w[0]), to: fmt(w[1]) }), true);
        } else say(W.t((res.data && res.data.error) || "the library refused it"), true);
        field.focus();
      };
      const buttons = () => [...box.querySelectorAll("button")];
      const busy = (on) => {
        for (const b of buttons()) b.disabled = on && !b.classList.contains("cancel");
        if (on) {
          retry.hidden = true;
          say([h("span", { class: "spin-line", "aria-hidden": "true" }), W.t("Placing…")]);
        }
      };
      field.addEventListener("input", () => {
        if (/[\r\n]/.test(field.value)) field.value = field.value.replace(/[\r\n]+/g, " "); // one line (split and join come later)
        field.removeAttribute("aria-invalid");
      });
      field.addEventListener("keydown", (e) => {
        if (e.isComposing) return;
        if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          if (!e.shiftKey) save(false); // Enter saves; it never breaks the line
        } else if (e.key === "Escape") {
          e.preventDefault();
          close(true);
        }
      });
      // On a phone with the keyboard up, the sheet keeps the field, the status and Cancel and Save; the rest is
      // behind More (the keyboard goes down when it is pressed).
      field.addEventListener("focus", () => box.classList.toggle("typing", PHONE.matches));
      // The keyboard down (the field left for anywhere but More): the whole sheet again, once the tap has landed.
      field.addEventListener("blur", (e) => {
        if (e.relatedTarget && e.relatedTarget.matches && e.relatedTarget.matches("[data-testid=line-more]")) return;
        setTimeout(() => document.activeElement !== field && box.classList.remove("typing"), 300);
      });

      const next = () => {
        const rows = app.words ? app.words.rows().rows : [];
        const k = rows.findIndex((x) => x.line.index === i);
        return k >= 0 && k + 1 < rows.length ? rows[k + 1].line.index : null;
      };
      const go = (more) => () => {
        const after = more ? next() : null;
        if (after !== null) openLine(after, null);
        else close(true);
      };
      async function save(more) {
        const text = field.value.replace(/\s+/g, " ").trim();
        if (!text) {
          field.setAttribute("aria-invalid", "true");
          say(W.t("Type the words of the line, or take it out of this recording."), true);
          return field.focus();
        }
        if (text === start.replace(/\s+/g, " ").trim()) return go(more)(); // nothing changed: nothing sent
        busy(true);
        await commit(i, { [i]: other ? { text, voice: "other" } : { text } }, (data) => savedText(i, data), go(more), failed);
      }
      const act = (change, said) => async () => {
        busy(true);
        await commit(i, { [i]: change }, () => said, go(false), failed);
      };
      const text = () => field.value.replace(/\s+/g, " ").trim() || line.text;
      const tools = h("div", { class: "tools" },
        h("button", { type: "button", class: "tool", "data-testid": "line-other", "aria-pressed": String(other),
          onclick: () => (other ? act({ text: text() }, W.t("Line {n} is the singer's again.", { n: i + 1 }))() : act({ text: text(), voice: "other" }, W.t("Line {n}: another voice.", { n: i + 1 }))()) },
        W.t("Other voice / spoken")),
        h("button", { type: "button", class: "tool", "data-testid": "line-gone", onclick: act({ gone: "not-sung" }, W.t("Line {n} is not in this recording.", { n: i + 1 })) }, W.t("Not in this recording")));
      const partOf = app.sectionOf(r.firstBar);
      const extra = h("div", { class: "extra", onfocusin: () => box.classList.remove("typing") },
        PHONE.matches ? hearLine(r) : null,
        h("div", { class: "bars-of-line" }, h("span", null, W.t("Chords:")), chips(r)),
        tools,
        PHONE.matches ? null : h("p", { class: "tip", "data-testid": "line-keys" }, W.t("Enter saves, {mod}+Enter saves and opens the next line.", { mod: MOD })));
      clear(
        box,
        h("h3", { id: "lineEdTitle" }, W.t("Line {n}", { n: i + 1 }),
          h("small", null, partOf ? W.t("{part} · {from} to {to}", { part: W.partName(partOf), from: fmt(line.start), to: fmt(line.end) }) : W.t("{from} to {to}", { from: fmt(line.start), to: fmt(line.end) }))),
        h("div", { class: "row" }, field, PHONE.matches ? null : hearLine(r)),
        h("div", { class: "state" }, status, retry),
        extra,
        h("div", { class: "acts" },
          h("span", { class: "left" },
            h("button", { type: "button", class: "btn more", "data-testid": "line-more", onclick: () => {
              box.classList.remove("typing");
              const first = extra.querySelector("button");
              if (first) first.focus();
            } }, W.t("More")),
            entry ? h("button", { type: "button", class: "back", "data-testid": "line-back", onclick: act(null, W.t("Line {n} is the placement's again.", { n: i + 1 })) }, W.t("Back to the placement")) : null),
          h("span", { class: "right" },
            h("button", { type: "button", class: "btn cancel", "data-testid": "line-cancel", onclick: () => close(true) }, W.t("Cancel")),
            h("button", { type: "button", class: "btn", "data-testid": "line-save", title: W.t("Enter"), onclick: () => save(false) }, W.t("Save")),
            h("button", { type: "button", class: "btn primary", "data-testid": "line-save-next", title: W.t("{mod}+Enter", { mod: MOD }), "aria-keyshortcuts": "Control+Enter Meta+Enter", onclick: () => save(true) }, W.t("Save, next line")))),
      );
      saveNext = () => save(true);
      box.hidden = false;
      box.classList.remove("typing");
      document.body.classList.add("line-open");
      const anchor = lineEl(i);
      W.popover.place(box, anchor || document.body);
      field.focus({ preventScroll: true });
      // The word tapped, selected: ready to be typed over.
      const tapped = word && word.querySelector(".wt") ? word.querySelector(".wt").textContent : "";
      let at = -1;
      if (tapped && anchor) {
        const same = [...anchor.querySelectorAll(".lw .wt")].filter((x) => x.textContent === tapped);
        const nth = same.indexOf(word.querySelector(".wt"));
        for (let k = 0, from = 0; k <= nth; k++, from = at + tapped.length) at = field.value.indexOf(tapped, from);
      }
      if (at >= 0) field.setSelectionRange(at, at + tapped.length);
      else field.setSelectionRange(field.value.length, field.value.length);
    }

    let saveNext = null;
    // The dialog keeps the keyboard: Escape anywhere cancels, Ctrl or ⌘ + Enter saves and opens the next line.
    box.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close(true);
      } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.isComposing && saveNext) {
        e.preventDefault();
        e.stopPropagation();
        saveNext();
      } else if (e.key === "Tab") W.popover.trap(box, e);
    });
    $("edScrim").addEventListener("click", () => open !== null && close(true));

    // On a phone the sheet stays above the keyboard, the line above the sheet; on a computer by the line.
    if (window.visualViewport) {
      for (const ev of ["resize", "scroll"]) {
        window.visualViewport.addEventListener(ev, () => {
          if (open === null || !PHONE.matches) return;
          W.popover.keepAboveKeyboard(box);
          if (ev === "resize") requestAnimationFrame(() => open !== null && W.popover.keepInSight(box, lineEl(open)));
        });
      }
    }
    let following = 0;
    const follow = () => {
      if (open === null || PHONE.matches || following) return;
      following = requestAnimationFrame(() => {
        following = 0;
        const el = open === null ? null : lineEl(open);
        if (el) W.popover.place(box, el, true);
      });
    };
    window.addEventListener("scroll", follow, { passive: true });
    window.addEventListener("resize", follow);

    // Back to the placement, from a row taken out of this recording.
    function back(i) {
      commit(i, { [i]: null }, () => W.t("Line {n} is the placement's again.", { n: i + 1 }), () => {
        const el = lineEl(i);
        if (el) el.focus({ preventScroll: true });
      });
    }

    // Every line fixed taken back, for the whole band: said first, undone in one tap.
    function untypeAll() {
      const keys = Object.keys(app.wordFixes());
      if (!keys.length) return;
      const ask = keys.length === 1 ? W.t("Take back 1 fixed line, for the whole band?") : W.t("Take back {n} fixed lines, for the whole band?", { n: keys.length });
      if (!window.confirm(ask)) return;
      commit(null, Object.fromEntries(keys.map((k) => [k, null])), () => W.t("The words are the placement's again."), () => {
        const el = $("editStrip").querySelector('[data-testid="words-undo"]') || $("editStrip").querySelector("button");
        if (el) el.focus();
      });
    }

    store.on((s, changed) => {
      if ((changed.has("editing") || changed.has("stage")) && (!s.editing || s.stage)) {
        close(false);
        if (!s.editing) undo = null;
      }
    });

    return { open: openLine, back, untypeAll, isOpen: () => open !== null, render() {} };
  };
})();
