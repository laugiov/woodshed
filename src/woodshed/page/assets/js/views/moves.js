// Moving a word without dragging (spec 029, WCAG 2.5.7): in the line editor, the word picked (the one tapped, or in
// the list), ◀ ▶ half a beat, and a ruler of the line's bars whose slots a tap puts the word on. The library moves
// it (app.py, woodshed.typed.move): the words it overtakes pushed along, never into the next line; a typed word stays
// typed, a placed one makes its line a line fixed by hand. One request a move, with Undo.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h } = W;

  W.views = W.views || {};

  // Where a beat is, in words: "bar 6, beat 3", "bar 6, the and of 3" (the drum panel's words).
  W.beatWhere = function beatWhere(song, at) {
    const meta = song.song;
    const u = W.typedWords.barOf(meta, at);
    const off = at - (meta.first_beat + u * song.per);
    const b = Math.floor(off + 1e-6);
    const q = Math.round((off - b) * 4);
    const n = b + 1;
    if (q === 2) return W.t("bar {bar}, the and of {n}", { bar: u + 1, n });
    if (q === 1) return W.t("bar {bar}, beat {n} and a quarter", { bar: u + 1, n });
    if (q === 3) return W.t("bar {bar}, beat {n} and three quarters", { bar: u + 1, n });
    return W.t("bar {bar}, beat {n}", { bar: u + 1, n });
  };

  // The library's refusals of a move, said as sentences (woodshed.typed NEXT, BEFORE).
  const REFUSED = {
    "the next line starts here: join the lines first": "The next line starts here: join the lines first.",
    "the line before is still sung here": "The line before is still sung here.",
  };

  W.views.moves = function moves(app) {
    const { song } = app;
    const meta = song.song;
    const TW = W.typedWords;
    const num = (x) => typeof x === "number" && Number.isFinite(x);

    // The line `ref` names as the sheet shows it: a typed line by its key, a placed line by its index.
    function lineOf(ref) {
      const lines = app.wordsData && Array.isArray(app.wordsData.lines) ? app.wordsData.lines : [];
      if (TW.KEY.test(String(ref))) return lines.find((ln) => ln && ln.key === ref);
      const rows = W.wordEdits.byIndex(app.wordsData)[+ref] || [];
      return rows.length === 1 ? rows[0] : null; // a split line (spec 028 B) moves its words in the line editor
    }
    const timed = (w) => !!w && num(w.start) && num(w.end);
    const atOf = (w) => (num(w.at) ? w.at : TW.beatAt(meta, w.start));

    // The group: `reopen(wi, focus)` draws the editor again on the same line once the word moved.
    function group(ref, wi, reopen) {
      const line = lineOf(ref);
      if (!line || !Array.isArray(line.words)) return null;
      const words = line.words;
      const movable = words.map((w, k) => (timed(w) ? k : -1)).filter((k) => k >= 0);
      if (!movable.length) return null;
      let pick = movable.includes(wi) ? wi : movable[0];
      const where = h("span", { class: "where", id: "moveWhere", "aria-live": "polite", "data-testid": "move-where" });
      const say = (warn) => {
        where.classList.toggle("warn", !!warn);
        W.clear(where, W.t("“{word}”: {where}", { word: words[pick].text, where: W.beatWhere(song, atOf(words[pick])) }));
      };
      const select = h("select", { "data-testid": "move-word", "aria-label": W.t("The word to move"), translate: "no",
        onchange: () => {
          pick = +select.value;
          say();
          paint();
        } },
      movable.map((k) => h("option", { value: String(k) }, words[k].text)));
      select.value = String(pick);
      function send(target, focus) {
        const word = words[pick].text;
        const k = pick;
        return app.lines.commit(
          ref,
          { [ref]: { timed: [[k, target]] } },
          () => W.t("Moved “{word}” to {where}.", { word, where: W.beatWhere(song, target) }),
          () => reopen(k, focus),
          (r) => {
            const err = r.data && r.data.error;
            where.classList.add("warn");
            W.clear(where, r.status === 0 ? W.t("The library did not answer: the line is not changed.") : W.t(REFUSED[err] || err || "the library refused it"));
          },
          { [ref]: { undo: true } },
        );
      }
      const step = (dir) => {
        const a = atOf(words[pick]);
        return dir > 0 ? Math.floor(a * 2 + 1e-6) / 2 + 0.5 : Math.ceil(a * 2 - 1e-6) / 2 - 0.5;
      };
      const earlier = h("button", { type: "button", class: "btn nudge", "data-testid": "move-earlier", "aria-label": W.t("Half a beat earlier"), title: W.t("Half a beat earlier"), "aria-describedby": "moveWhere", onclick: () => send(step(-1), "move-earlier") }, "◀");
      const later = h("button", { type: "button", class: "btn nudge", "data-testid": "move-later", "aria-label": W.t("Half a beat later"), title: W.t("Half a beat later"), "aria-describedby": "moveWhere", onclick: () => send(step(1), "move-later") }, "▶");
      // The ruler: the line's bars and the one after, half beats as slots; for the eye and the finger (the buttons
      // and the list are the keyboard's).
      const first = TW.barOf(meta, atOf(words[movable[0]]));
      const last = Math.min(song.bars.length - 1, TW.barOf(meta, atOf(words[movable[movable.length - 1]])) + 1, first + (W.popover.PHONE.matches ? 2 : 3));
      const ruler = h("div", { class: "ruler", "aria-hidden": "true", "data-testid": "move-ruler", style: "grid-template-columns: repeat(" + (last - first + 1) + ", minmax(0, 1fr))" });
      const slots = [];
      for (let u = first; u <= last; u++) {
        const cell = h("div", { class: "cell", style: "grid-template-columns: repeat(" + (W.popover.PHONE.matches ? song.per : song.per * 2) + ", minmax(0, 1fr))" }, h("span", { class: "num" }, String(u + 1)));
        // Under a finger, whole beats only (a half beat is 15 px on a phone): ◀ ▶ give the "ands".
        const step = W.popover.PHONE.matches ? 2 : 1;
        for (let s = 0; s < song.per * 2; s += step) {
          const at = meta.first_beat + u * song.per + s / 2;
          const slot = h("button", { type: "button", tabindex: "-1", class: "slot" + (s % 2 ? "" : " beat"), "aria-hidden": "true", "data-testid": "move-slot", "data-at": String(at), onclick: () => send(at, null) });
          slots.push(slot);
          cell.append(slot);
        }
        ruler.append(cell);
      }
      function paint() {
        for (const slot of slots) {
          const at = +slot.getAttribute("data-at");
          const here = movable.filter((k) => Math.abs(Math.round(atOf(words[k]) * 2) / 2 - at) < 1e-6);
          W.clear(slot, here.length ? h("span", { class: "dot" }) : null);
          slot.classList.toggle("lit", here.includes(pick));
        }
      }
      paint();
      say();
      return h("div", { class: "moves", "data-testid": "move-group" },
        h("div", { class: "mrow" }, h("span", null, W.t("Move a word:")), select, earlier, later, where),
        ruler,
        h("p", { class: "mrow tip-tap" }, W.t("Or tap where it goes.")));
    }

    return { group };
  };
})();
