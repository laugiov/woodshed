// Tapping along (spec 029-2): the words pasted in the words dialog, laid as the song plays. An explicit mode: a
// panel shows the line to tap; Space, a pedal (Right arrow, Page Down) or the big button on a touch screen marks
// where it starts; Escape (or Done) leaves with the lines tapped so far. A tap is the beat sounding then, snapped
// to the nearest quarter beat and sent as its index in the song's beats: the library lays each line's words by
// syllables and computes every time (app.py set_words, woodshed.typed.tapped_lines). One request, one Undo.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, clear } = W;
  const TAP_KEYS = [" ", "ArrowRight", "PageDown"];

  W.views = W.views || {};

  W.views.tap = function tap(app) {
    const { store } = app;
    let on = null; // {text, lines, taps} while tapping along
    let panel = null;
    let pressed = 0; // the last pointer press on the button: its click is the same tap

    function draw() {
      const { lines, taps } = on;
      const k = Math.min(taps.length, lines.length - 1);
      const next = lines[k + 1];
      clear(
        panel,
        h(
          "div",
          { class: "tap-head" },
          h("strong", { class: "tap-count", "data-testid": "tap-count", "aria-live": "polite" }, W.t("Line {k} of {n}", { k: k + 1, n: lines.length })),
          h("span", { class: "hint" }, W.t("Tap Space or the pedal as each line starts. Escape stops.")),
          h("button", { type: "button", class: "btn", "data-testid": "tap-done", onclick: () => finish() }, W.t("Done")),
        ),
        h("p", { class: "tap-line", "data-testid": "tap-line", translate: "no" }, lines[k].text),
        next ? h("p", { class: "tap-next", translate: "no" }, next.text) : null,
        h(
          "button",
          {
            type: "button", class: "btn primary tap-button", "data-testid": "tap-button",
            onpointerdown: (e) => {
              e.preventDefault(); // the tap is now, not when the finger lifts
              pressed = Date.now();
              mark();
            },
            onclick: () => {
              if (Date.now() - pressed > 600) mark(); // a keyboard or a screen reader presses it
            },
          },
          W.t("Tap: the line starts"),
        ),
      );
    }

    // A tap: the beat sounding now, snapped; a tap no later than the one before is a double tap, dropped.
    function mark() {
      if (!on) return;
      const at = W.typedWords.snap(W.typedWords.beatAt(app.song.song, app.transport.time));
      const meta = app.song.song;
      if (at < 0 || W.typedWords.barOf(meta, at) >= app.song.bars.length) return; // before the first bar, after the last
      const last = on.taps[on.taps.length - 1];
      if (last !== undefined && at <= last) return;
      on.taps.push(at);
      if (on.taps.length >= on.lines.length) return finish();
      draw();
    }

    function said(data) {
      const n = data.laid.length;
      const out = [n === 1
        ? W.t("1 line laid by tapping along: move a word to its beat where it falls wrong.")
        : W.t("{n} lines laid by tapping along: move a word to its beat where it falls wrong.", { n })];
      if (data.left === 1) out.push(W.t("1 line not laid."));
      else if (data.left > 1) out.push(W.t("{n} lines not laid.", { n: data.left }));
      return out.join(" ");
    }

    function leave() {
      on = null;
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("keyup", onKeyUp, true);
      if (panel) panel.remove();
      panel = null;
    }

    async function finish() {
      if (!on) return;
      const { text, taps } = on;
      leave();
      if (store.get().playing) app.togglePlay();
      const back = document.getElementById("wordsBtn");
      if (back) back.focus({ preventScroll: true });
      if (taps.length) await app.lines.lay({ text, taps }, said);
    }

    // Before the page's own keys (Space plays, Escape closes): while tapping along they are the taps'.
    const stop = (e) => {
      e.preventDefault();
      e.stopImmediatePropagation();
    };
    function onKey(e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "Escape") {
        stop(e);
        finish();
      } else if (TAP_KEYS.includes(e.key)) {
        stop(e);
        if (!e.repeat) mark(); // a pedal held down is one tap
      }
    }
    function onKeyUp(e) {
      if (TAP_KEYS.includes(e.key)) stop(e); // a focused button is pressed on the key's release: not here
    }

    function start(text, lines) {
      if (on) leave();
      on = { text, lines, taps: [] };
      panel = h("section", { class: "tap-along", "data-testid": "tap-along", "aria-label": W.t("Tapping along") });
      document.body.appendChild(panel);
      draw();
      window.addEventListener("keydown", onKey, true);
      window.addEventListener("keyup", onKeyUp, true);
      panel.querySelector(".tap-button").focus({ preventScroll: true });
      if (!store.get().playing) app.togglePlay();
    }

    return { start, active: () => on !== null, relabel: () => on && draw(), render() {} };
  };
})();
