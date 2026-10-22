// Moving the bar lines (the whole song): "Where is beat one?". Served by woodshed app, the library
// analyses the song again with the beat chosen as one (POST /api/bars); opened from disk, the page
// gives the command. The beats do not move, so the chords and parts typed stay where they were.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, clear } = W;

  W.views.barLines = function barLines(app) {
    const { song, store } = app;
    const meta = song.song;
    const per = song.per;
    const served = location.protocol === "http:" || location.protocol === "https:";
    const folder = decodeURIComponent(location.pathname.split("/").slice(-2)[0] || "");
    const DONE = "woodshed:bars-moved:" + folder; // said again after the reload that shows the new bars
    const current = ((meta.first_beat % per) + per) % per; // beats before the first bar line now
    let dialog = null;
    let polling = 0;
    let chosen = 1; // the beat of bar 1 the band counts "one" on (1: as it is)

    const offsetFor = (beat) => (current + beat - 1) % per;
    const counted = (n, one, many) => (n === 1 ? W.t(one) : W.t(many, { n }));

    function say(el, text, warn) {
      el.textContent = text;
      el.classList.toggle("warn", !!warn);
    }

    async function token() {
      const r = await fetch("/api/token", { cache: "no-store" });
      const data = await r.json();
      if (!r.ok || typeof data.token !== "string") throw new Error(W.t("the library did not answer: is woodshed app still running?"));
      return data.token;
    }

    function moved(status) {
      clearInterval(polling);
      try {
        sessionStorage.setItem(DONE, "1");
      } catch (err) {
        /* no storage: the new bars show, without the note */
      }
      if (store.get().playing) {
        say(status, W.t("The bar lines moved. They appear when you stop playing."));
        const off = store.on((s) => {
          if (!s.playing) {
            off();
            location.reload();
          }
        });
      } else {
        say(status, W.t("The bar lines moved. Loading them…"));
        location.reload();
      }
    }

    // The library's answer about this song's job, until it is done (as views/words.js follows the words).
    function follow(id, status, go) {
      clearInterval(polling);
      polling = setInterval(async () => {
        let data;
        try {
          data = await (await fetch("/api/songs", { cache: "no-store" })).json();
        } catch (err) {
          return; // the next tick asks again
        }
        const job = data.jobs.find((j) => j.id === id);
        if (!job) {
          clearInterval(polling);
          go.disabled = false;
          return say(status, W.t("The library was restarted before the bar lines moved: try again."), true);
        }
        if (job.status === "failed") {
          clearInterval(polling);
          go.disabled = false;
          say(status, W.t("The bar lines did not move: {why}", { why: job.message }), true);
        } else if (job.status === "done") moved(status);
        else if (job.status === "queued") say(status, W.t("Waiting for the song being analysed…"));
        else say(status, W.t("Analysing the song again with the new bar lines…"));
      }, 1500);
    }

    async function move(status, go) {
      go.disabled = true;
      say(status, W.t("Sending…"));
      try {
        const r = await fetch("/api/bars", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Woodshed-Token": await token() },
          body: JSON.stringify({ page: folder, offset: offsetFor(chosen) }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.error ? W.t(data.error) : W.t("the library refused it ({status})", { status: r.status }));
        say(status, W.t("Analysing the song again with the new bar lines…"));
        follow(data.id, status, go);
      } catch (err) {
        go.disabled = false;
        say(status, err.message, true);
      }
    }

    function render() {
      const bars = Object.keys(app.typedBars.values()).length;
      const parts = Object.keys(app.typedParts.values()).length;
      const status = h("p", { class: "status", role: "status", "data-testid": "bars-status" });
      const command = h("p", { class: "cmd", translate: "no", "data-testid": "bars-command" });
      const showCommand = () => (command.textContent = 'woodshed "' + (meta.file || meta.title) + '" --offset ' + offsetFor(chosen));
      const go = h("button", { type: "button", class: "btn primary", "data-testid": "bars-move", disabled: "", onclick: () => move(status, go) }, W.t("Move the bar lines"));
      const beats = h(
        "div",
        { class: "beats-pick", role: "group", "aria-label": W.t("The beat of bar 1 the band counts one on") },
        [...Array(per).keys()].map((k) =>
          h("button", {
            type: "button", class: k === 0 ? "on" : "", "aria-pressed": String(k === 0), "data-testid": "bars-beat",
            onclick: (e) => {
              chosen = k + 1;
              for (const b of beats.children) {
                b.classList.toggle("on", b === e.currentTarget);
                b.setAttribute("aria-pressed", String(b === e.currentTarget));
              }
              go.disabled = chosen === 1;
              showCommand();
            },
          }, String(k + 1), k === 0 ? h("small", null, W.t("now")) : null)),
      );
      showCommand();
      const kept = [counted(bars, "1 typed bar", "{n} typed bars"), counted(parts, "1 part name", "{n} part names")].join(W.t(" and "));
      let how;
      if (!served) how = [h("p", null, W.t("Opened from disk, the command line moves them, in the folder of the recording:")), command];
      else if (store.get().wordsElsewhere) how = [h("p", null, W.t("The bar lines are moved from the computer that runs woodshed."))];
      else {
        how = [
          h("p", { class: "read" }, W.t("woodshed analyses the song again from its tracks: about a minute. Your {kept} stay on their beats; the chords picked among candidates start over.", { kept })),
          status,
        ];
      }
      clear(
        dialog,
        h("h2", { id: "barsTitle" }, W.t("Where is beat one?"), " ", h("small", null, W.t("The whole song"))),
        h("p", null, W.t("Tap the beat the band counts “one” on, in bar 1:")),
        beats,
        how,
        h("div", { class: "dialog-actions" },
          h("button", { type: "button", class: "btn", "data-testid": "bars-cancel", onclick: () => dialog.close() }, W.t("Cancel")),
          served && !store.get().wordsElsewhere ? go : null),
      );
    }

    app.openBarLines = () => {
      if (!dialog) {
        dialog = h("dialog", { class: "words-dialog bars-dialog", "aria-labelledby": "barsTitle", "data-testid": "bars-dialog" });
        document.body.append(dialog);
        dialog.addEventListener("close", () => clearInterval(polling));
      }
      chosen = 1;
      render();
      dialog.showModal();
    };

    // After the reload that shows the new bar lines.
    try {
      if (sessionStorage.getItem(DONE)) {
        sessionStorage.removeItem(DONE);
        setTimeout(() => app.toast(W.t("The bar lines moved. Your typed chords and parts are where they were.")), 300);
      }
    } catch (err) {
      /* no storage: nothing to say */
    }

    return { render() {} };
  };
})();
