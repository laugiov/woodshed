// Fixing a line of the words on the sheet (spec 028): the line editor, under the line on a computer, a sheet
// over the keyboard on a phone (the bar editor's shell, views/popover.js). The library places only that line
// again, in its own window, and shares it with the band (app.py set_words); nothing is placed here.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, fmt } = W;
  const MOD = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘" : "Ctrl";
  const SPREAD = "spread over the line's time, not heard: listen to it"; // lyrics.SPREAD_CHECK
  const STALE = "the words were placed again: reload the page"; // app.py StaleWords

  W.views = W.views || {};

  W.views.lines = function lines(app, chart, editor) {
    const { song, store } = app;
    const box = $("lineEd");
    const PHONE = W.popover.PHONE;
    let open = null; // the index of the line being edited, in lyrics.json
    let openRow = 0; // the row it was opened from: a split line has several (spec 028 B)
    let undo = null; // {n, change, expect}: the line as it was before the last change made here, and as that change left it

    // A line as one row of the sheet: a split line's rows (spec 028 B) put together, its bars and its time.
    function rowOf(i) {
      const rows = app.words ? app.words.rows().rows.filter((r) => r.line.index === i) : [];
      if (!rows.length) return null;
      const seen = new Set();
      const bars = rows.flatMap((r) => r.bars).filter((b) => !seen.has(b.bar) && seen.add(b.bar));
      const line = { ...rows[0].line, start: Math.min(...rows.map((r) => r.line.start)), end: Math.max(...rows.map((r) => r.line.end)) };
      return { ...rows[0], line, bars, rows: rows.length };
    }
    // A placed line by its index (a split line by its row), a line typed by hand by its key (views/typed.js shares
    // this editor's shell).
    const lineEl = (i, piece) => (W.typedWords.KEY.test(String(i))
      ? document.querySelector('#sheet .lline[data-key="' + i + '"]')
      : document.querySelector('#sheet .lline[data-index="' + i + '"][data-piece="' + (piece || 0) + '"]') ||
        document.querySelector('#sheet .lline[data-index="' + i + '"]'));
    const placedText = (i) => app.placedWords.lines[i].text;
    // The lines joined into line i (spec 028 B), as the library keeps them.
    function held(i) {
      const out = [];
      for (let j = i + 1; app.wordFixes()[j] && app.wordFixes()[j].gone === "joined"; j++) out.push(j);
      return out;
    }
    // A line joined into the one before it goes with that line and every line joined into it, and back.
    function group(i) {
      let base = i;
      while (base > 0 && app.wordFixes()[base] && app.wordFixes()[base].gone === "joined") base--;
      return [base, ...held(base)];
    }
    // The line as the library has it, as the editor asks for it: its words (a split line's lines, one a row),
    // another voice, gone, joined into the line before, or as placed.
    function asked(i) {
      const e = app.wordFixes()[i];
      if (!e) return null;
      if (e.gone) return { gone: e.gone };
      const text = e.lines ? e.lines.map((ln) => ln.text).join("\n") : placedText(i);
      return e.voice === "other" ? { text, voice: "other" } : { text };
    }
    // The words as typed, each line of a split tidied, the empty ones dropped.
    const tidy = (text) => text.split("\n").map((t) => t.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
    // The words in the field: the line's text, its backing vocals in brackets when the text has none.
    function fieldText(line) {
      const backing = Array.isArray(line.backing) ? line.backing.filter((b) => typeof b === "string" && b) : [];
      return backing.length && !line.text.includes("(") ? line.text + " (" + backing.join(") (") + ")" : line.text;
    }

    function close(restore) {
      const was = open;
      const row = openRow;
      box.hidden = true;
      $("edScrim").hidden = true;
      document.body.classList.remove("line-open");
      document.querySelectorAll(".ed-tail").forEach((t) => t.remove());
      open = null;
      cancelShown = null;
      const back = was === null ? null : lineEl(was, row);
      if (restore && back) back.focus({ preventScroll: true });
    }

    // The library's answer to a change: the fixes of this placement, drawn at once.
    async function send(change, expect) {
      const r = await app.shareWords(change, expect);
      if (r.ok) app.useWordEdits(r.data.lines, true);
      return r;
    }
    // A refusal said plainly: no answer, a line another device changed since, the words placed again elsewhere.
    function refused(r) {
      if (r.status === 0) return W.t("The library did not answer: the line is not changed.");
      const data = r.data || {};
      if (Array.isArray(data.changed) && data.changed.length) {
        return W.t("“{words}” changed on another device: Undo leaves it as it is.", { words: app.lineWords(+data.changed[0]) });
      }
      if (data.error === STALE) return W.t("The words were placed again: reload the page.");
      return W.t(data.error || "the library refused it");
    }

    // A change made here: sent, then the toast with Undo (kept in the strip until the next change).
    // The lines joined into a line changed go with it (the library lets them go): its Undo brings them back too.
    // `back`: the change that undoes this one, when asking for the line as it was cannot (a typed line, a word moved).
    async function commit(i, change, said, after, status, back) {
      const before = back ? { ...back } : {};
      if (!back) for (const k of Object.keys(change)) for (const n of [+k, ...group(+k)]) before[n] = asked(n);
      const r = await send(change);
      if (!r.ok) {
        if (status) status(r);
        else app.toast(refused(r));
        return false;
      }
      const expect = {};
      for (const k of Object.keys(before)) expect[k] = r.data.lines[k] === undefined ? null : r.data.lines[k];
      undo = { n: i, change: before, expect };
      store.set({ corrections: store.get().corrections + 1 }); // the strip shows Undo
      if (after) after();
      app.toast(said(r.data), { label: W.t("Undo"), run: runUndo });
      return true;
    }
    async function runUndo() {
      if (!undo) return false;
      const was = undo;
      undo = null;
      const r = await send(was.change, was.expect); // refused when another device changed the line since
      if (!r.ok) {
        if (r.status === 0) undo = was; // offline: it may be tried again
        // Refused (another device changed the line, the words placed again): the page as the band has it, one tap.
        app.toast(refused(r), r.status === 0 ? undefined : { label: W.t("Reload"), run: () => location.reload() });
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
      const out = [W.t("“{words}” saved.", { words: app.lineWords(i) })];
      const pieces = e && e.lines ? e.lines : [];
      const number = pieces.flatMap((ln) => ln.words).find((w) => w.start === null && /\d/.test(w.text));
      if (number) out.push(W.t("{word} is not heard: write numbers as words.", { word: number.text }));
      if (pieces.some((ln) => ln.check === SPREAD)) out.push(W.t("Spread over the line's time, not heard: listen to it."));
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

    // The next line of the placement that could be joined into line i: sung, on the sheet, in the same part, and
    // four lines at most once joined.
    function joinable(i, rows) {
      const j = i + 1 + held(i).length;
      const placed = app.placedWords.lines;
      const next = rowOf(j);
      if (!next || !placed[j] || placed[j].block !== placed[i].block || placed[j].tag !== placed[i].tag) return null;
      return held(i).length < 3 && rows + next.rows - 1 <= 4 ? j : null;
    }
    // A line's words in the field: one row a line of a split.
    function wordsOf(i, line) {
      const e = app.wordFixes()[i];
      return e && e.lines && e.lines.length > 1 ? e.lines.map(fieldText).join("\n") : fieldText(line);
    }

    function openLine(i, word, from, move) {
      if (!app.canFixWords()) return app.toast(W.t("Fixing a line's words needs the library (woodshed app)."));
      const r = rowOf(i);
      if (!r) return close(false);
      if (open !== null) close(false);
      open = i;
      openRow = from && from.getAttribute ? +(from.getAttribute("data-piece") || 0) : 0;
      const line = r.line;
      const entry = app.wordFixes()[i];
      const other = line.voice === "other";
      const start = wordsOf(i, line);
      const joinTo = joinable(i, r.rows);
      const field = h("textarea", {
        class: "field", id: "lineEdField", rows: PHONE.matches ? "2" : "1", maxlength: "200", spellcheck: "false", translate: "no",
        autocomplete: "off", enterkeyhint: "done", "data-testid": "line-field", "aria-label": W.t("Words of line {n}", { n: i + 1 }), "aria-describedby": "lineEdStatus",
      });
      field.value = start;
      const status = h("p", { class: "read", id: "lineEdStatus", "aria-live": "polite", "data-testid": "line-status" },
        W.t("Only this line is placed again, between {from} and {to}. The lines around it do not move.", { from: fmt(line.start), to: fmt(line.end) }));
      const retry = h("button", { type: "button", class: "btn", hidden: "", "data-testid": "line-retry", onclick: () => save(false) }, W.t("Retry"));
      const reload = h("button", { type: "button", class: "btn", hidden: "", "data-testid": "line-reload", onclick: () => location.reload() }, W.t("Reload"));
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
          const room = { from: fmt(w[0]), to: fmt(w[1]) };
          say(joinTo === null ? W.t("Not enough time for these words between {from} and {to}.", room)
            : W.t("Not enough time for these words between {from} and {to}: join it with the next line.", room), true);
        } else say(refused(res), true);
        reload.hidden = !(res.data && res.data.error === STALE); // this page's words are not the library's now
        field.focus();
      };
      const buttons = () => [...box.querySelectorAll("button")];
      const busy = (on) => {
        for (const b of buttons()) b.disabled = on && !b.classList.contains("cancel");
        if (on) {
          retry.hidden = true;
          reload.hidden = true;
          say([h("span", { class: "spin-line", "aria-hidden": "true" }), W.t("Placing…")]);
        }
      };
      // The field grows with a long line: all of it in sight while it is typed.
      const grow = () => {
        field.style.height = "auto";
        field.style.height = field.scrollHeight + (field.offsetHeight - field.clientHeight) + "px";
      };
      // Four lines at most: a fifth row pasted goes on the fourth.
      field.addEventListener("input", () => {
        const rows = field.value.replace(/\r\n?/g, "\n").split("\n");
        const v = rows.length > 4 ? [...rows.slice(0, 3), rows.slice(3).join(" ")].join("\n") : rows.join("\n");
        if (v !== field.value) field.value = v;
        grow();
        field.removeAttribute("aria-invalid");
      });
      // A split at the cursor (spec 028 B): Shift+Enter or "Split at the cursor"; Save places the lines together.
      // Never inside a word: the break goes to the nearest gap between two words (the earlier one on a tie).
      function gapNear(v, a) {
        const word = /\S/;
        if (!(a > 0 && a < v.length && word.test(v[a - 1]) && word.test(v[a]))) return a;
        let back = a;
        while (back > 0 && word.test(v[back - 1])) back--;
        let ahead = a;
        while (ahead < v.length && word.test(v[ahead])) ahead++;
        const options = [back > 0 ? back : null, ahead < v.length ? ahead : null].filter((x) => x !== null);
        return options.length ? options.sort((x, y) => Math.abs(x - a) - Math.abs(y - a))[0] : a;
      }
      function splitAt() {
        const v = field.value;
        const a = gapNear(v, field.selectionStart);
        const left = v.slice(0, a).replace(/[ \t]+$/, "");
        const right = v.slice(a === field.selectionStart ? field.selectionEnd : a).replace(/^[ \t]+/, "");
        if (v.split("\n").length >= 4) {
          say(W.t("A line is split in four at most."), true);
        } else if (left.trim() && right.trim() && !left.endsWith("\n") && !right.startsWith("\n")) {
          field.value = left + "\n" + right;
          field.setSelectionRange(left.length + 1, left.length + 1);
          field.removeAttribute("aria-invalid");
          grow();
          say(W.t("Split: {n} lines. Save places them.", { n: field.value.split("\n").length }));
        } else {
          say(W.t("Put the cursor between two words."), true);
        }
        field.focus();
      }
      field.addEventListener("keydown", (e) => {
        if (e.isComposing) return;
        if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          if (e.shiftKey) splitAt();
          else save(false); // Enter saves; Shift+Enter breaks the line
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
        const after = k >= 0 ? rows.slice(k).find((x) => x.line.index !== i) : null; // past a split line's rows
        return after ? after.line.index : null;
      };
      const go = (more) => () => {
        const after = more ? next() : null;
        if (after !== null) openLine(after, null);
        else close(true);
      };
      async function save(more) {
        const text = tidy(field.value);
        if (!text) {
          field.setAttribute("aria-invalid", "true");
          say(W.t("Type the words of the line, or take it out of this recording."), true);
          return field.focus();
        }
        if (text === tidy(start)) return go(more)(); // nothing changed: nothing sent
        busy(true);
        await commit(i, { [i]: other ? { text, voice: "other" } : { text } }, (data) => savedText(i, data), go(more), failed);
      }
      const act = (change, said) => async () => {
        busy(true);
        await commit(i, { [i]: change }, said, go(false), failed);
      };
      const text = () => tidy(field.value) || line.text;
      // Two lines as one, placed in the window of both (spec 028 B): the next line's words after these.
      const join = async () => {
        busy(true);
        const words = text() + " " + wordsOf(joinTo, rowOf(joinTo).line);
        const change = { [i]: other ? { text: words, voice: "other" } : { text: words }, [joinTo]: { gone: "joined" } };
        await commit(i, change, () => W.t("“{words}” joined with the next line.", { words: app.lineWords(i) }), go(false), failed);
      };
      const tools = h("div", { class: "tools" },
        h("button", { type: "button", class: "tool", "data-testid": "line-split", onmousedown: (e) => e.preventDefault(), onclick: splitAt }, W.t("Split at the cursor")),
        joinTo === null ? null : h("button", { type: "button", class: "tool", "data-testid": "line-join", onclick: join }, W.t("Join with the next line")),
        h("button", { type: "button", class: "tool", "data-testid": "line-other", "aria-pressed": String(other),
          onclick: () => (other
            ? act({ text: text() }, () => W.t("“{words}” is the singer's again.", { words: app.lineWords(i) }))()
            : act({ text: text(), voice: "other" }, () => W.t("“{words}”: another voice.", { words: app.lineWords(i) }))()) },
        W.t("Other voice / spoken")),
        h("button", { type: "button", class: "tool", "data-testid": "line-gone", onclick: act({ gone: "not-sung" }, () => W.t("“{words}” is not in this recording.", { words: app.lineWords(i) })) }, W.t("Not in this recording")));
      const partOf = app.sectionOf(r.firstBar);
      // A word moved without dragging (spec 029): the word tapped, ◀ ▶, a slot of the ruler.
      const wi = move && move.wi !== undefined ? move.wi : word && word.hasAttribute("data-wi") ? +word.getAttribute("data-wi") : 0;
      const moves = app.moves.group(String(i), wi, (k, focus) => openLine(i, null, from, { wi: k, focus: focus || "move" }));
      const extra = h("div", { class: "extra", onfocusin: () => box.classList.remove("typing") },
        PHONE.matches ? hearLine(r) : null,
        h("div", { class: "bars-of-line" }, h("span", null, W.t("Chords:")), chips(r)),
        tools,
        moves,
        PHONE.matches ? null : h("p", { class: "tip", "data-testid": "line-keys" }, W.t("Enter saves, {mod}+Enter saves and opens the next line.", { mod: MOD }), " ", W.t("Shift+Enter splits at the cursor.")));
      clear(
        box,
        // Named by its first words (a number would read as a bar's), its number with its part and time.
        h("h3", { id: "lineEdTitle" }, h("span", { translate: "no" }, app.lineWords(i)),
          h("small", null, W.t("Line {n}", { n: i + 1 }) + " · " + (partOf ? W.t("{part} · {from} to {to}", { part: W.partName(partOf), from: fmt(line.start), to: fmt(line.end) }) : W.t("{from} to {to}", { from: fmt(line.start), to: fmt(line.end) })))),
        h("div", { class: "row" }, field, PHONE.matches ? null : hearLine(r)),
        h("div", { class: "state" }, status, retry, reload),
        extra,
        h("div", { class: "acts" },
          h("span", { class: "left" },
            h("button", { type: "button", class: "btn more", "data-testid": "line-more", onclick: () => {
              box.classList.remove("typing");
              const first = extra.querySelector("button");
              if (first) first.focus();
            } }, W.t("More")),
            entry ? h("button", { type: "button", class: "back", "data-testid": "line-back", "aria-label": W.t("Back to the placement: line {n}", { n: i + 1 }), onclick: act(null, () => W.t("“{words}” is the placement's again.", { words: app.lineWords(i) })) }, W.t("Back to the placement")) : null),
          h("span", { class: "right" },
            h("button", { type: "button", class: "btn cancel", "data-testid": "line-cancel", onclick: () => close(true) }, W.t("Cancel")),
            h("button", { type: "button", class: "btn", "data-testid": "line-save", title: W.t("Enter"), onclick: () => save(false) }, W.t("Save")),
            h("button", { type: "button", class: "btn primary", "data-testid": "line-save-next", title: W.t("{mod}+Enter", { mod: MOD }), "aria-keyshortcuts": "Control+Enter Meta+Enter", onclick: () => save(true) }, W.t("Save, next line")))),
      );
      saveNext = () => save(true);
      box.hidden = false;
      box.classList.remove("typing");
      document.body.classList.add("line-open");
      const anchor = lineEl(i, openRow);
      W.popover.place(box, anchor || document.body);
      grow();
      field.focus({ preventScroll: true });
      // The word tapped, selected: ready to be typed over.
      const tapped = word && word.querySelector(".wt") ? word.querySelector(".wt").textContent : "";
      let at = -1;
      if (tapped && anchor) {
        // In the words of every row before it too: a split line's rows are one field.
        const rowsBefore = [...document.querySelectorAll('#sheet .lline[data-index="' + i + '"]')].filter((el) => +el.getAttribute("data-piece") < openRow);
        const all = [...rowsBefore, anchor].flatMap((el) => [...el.querySelectorAll(".lw .wt")]);
        const same = all.filter((x) => x.textContent === tapped);
        const nth = same.indexOf(word.querySelector(".wt"));
        for (let k = 0, from = 0; k <= nth; k++, from = at + tapped.length) at = field.value.indexOf(tapped, from);
      }
      if (at >= 0) field.setSelectionRange(at, at + tapped.length);
      else field.setSelectionRange(field.value.length, field.value.length);
      const focus = move && move.focus;
      const target = focus === "move" ? box.querySelector("[data-testid=move-word]") : focus ? box.querySelector('[data-testid="' + focus + '"]') : null;
      if (target) {
        box.classList.remove("typing");
        target.focus({ preventScroll: true });
      }
    }

    let saveNext = null;
    let cancelShown = null; // the typed line's editor in this shell (views/typed.js): its own Cancel
    // Another editor drawn in this shell: its line followed on scroll, its keys (Escape, Ctrl or ⌘ + Enter) its own.
    function shown(key, next, cancel) {
      open = key;
      saveNext = next;
      cancelShown = cancel;
    }
    // The dialog keeps the keyboard: Escape anywhere cancels, Ctrl or ⌘ + Enter saves and opens the next line.
    box.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        if (cancelShown) cancelShown();
        else close(true);
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
          if (ev === "resize") requestAnimationFrame(() => open !== null && W.popover.keepInSight(box, lineEl(open, openRow)));
        });
      }
    }
    let following = 0;
    const follow = () => {
      if (open === null || PHONE.matches || following) return;
      following = requestAnimationFrame(() => {
        following = 0;
        const el = open === null ? null : lineEl(open, openRow);
        if (el) W.popover.place(box, el, true);
      });
    };
    window.addEventListener("scroll", follow, { passive: true });
    window.addEventListener("resize", follow);

    // Back to the placement, from a row taken out of this recording, or joined into the line before (the whole
    // join taken back: the line it went to is the placement's again).
    // The library gives the line it went to the fix it had before the join (spec 028 B).
    function back(i) {
      commit(i, { [i]: null }, () => W.t("“{words}” is the placement's again.", { words: app.lineWords(i) }), () => {
        const el = lineEl(i);
        if (el) el.focus({ preventScroll: true });
      });
    }

    // Every line fixed taken back, for the whole band: said first, undone in one tap.
    function untypeAll() {
      const keys = Object.keys(app.wordFixes()).filter((k) => !W.typedWords.KEY.test(k)); // never the lines typed by hand
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

    return { open: openLine, back, untypeAll, commit, shown, close: () => close(false), isOpen: () => open !== null, render() {} };
  };
})();
