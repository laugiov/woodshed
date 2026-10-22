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
    let reloading = false;
    const stop = () => {
      clearInterval(polling);
      polling = 0;
    };

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

    // The new bar lines are in the page on disk: load it, once the music stops. This device asked
    // for them (its status says it), or another device did (the band's stream says it: views/band.js).
    function moved(status) {
      stop();
      if (reloading) return;
      reloading = true;
      try {
        sessionStorage.setItem(DONE, "1");
      } catch (err) {
        /* no storage: the new bars show, without the note */
      }
      if (store.get().playing) {
        const text = W.t("The bar lines moved. They appear when you stop playing.");
        if (status && dialog.open) say(status, text);
        else app.toast(text);
        const off = store.on((s) => {
          if (!s.playing) {
            off();
            location.reload();
          }
        });
      } else {
        if (status) say(status, W.t("The bar lines moved. Loading them…"));
        location.reload();
      }
    }
    app.barsMoved = () => moved(null);

    // Shown when the dialog is open, else said on the page: closing it does not stop the job.
    function failed(status, go, text) {
      stop();
      go.disabled = false;
      if (dialog.open) say(status, text, true);
      else app.toast(text);
    }

    // The library's answer about this song's job, until it is done (as views/words.js follows the words).
    function follow(id, status, go) {
      stop();
      polling = setInterval(async () => {
        let data;
        try {
          data = await (await fetch("/api/songs", { cache: "no-store" })).json();
        } catch (err) {
          return; // the next tick asks again
        }
        const job = data.jobs.find((j) => j.id === id);
        if (!job) return failed(status, go, W.t("The library was restarted before the bar lines moved: try again."));
        if (job.status === "failed") failed(status, go, W.t("The bar lines did not move: {why}", { why: W.t(job.message) }));
        else if (job.status === "done") moved(status);
        else if (job.status === "queued") say(status, W.t("Waiting for the song being analysed…"));
        else say(status, W.t("Analysing the song again with the new bar lines…"));
      }, 1500);
    }

    // The command that makes the same page again, with the band's bar lines: the settings it was
    // made with, the file name quoted for the shell.
    function commandFor(phase) {
      const a = meta.analysis || {};
      const quote = (s) => '"' + String(s).replace(/(["$`\\])/g, "\\$1") + '"';
      const args = ["woodshed", quote(meta.file || meta.title)];
      if (per !== 4) args.push("--beats-per-bar", String(per));
      if (a.sevenths) args.push("--sevenths");
      if (typeof a.bpm_hint === "number") args.push("--bpm", String(a.bpm_hint));
      if (a.stems === false) args.push("--no-stems");
      return args.concat("--bar-phase", String(phase)).join(" ");
    }

    let cancel = null;

    async function move(status, go) {
      go.disabled = true;
      say(status, W.t("Sending…"));
      try {
        const r = await fetch("/api/bars", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Woodshed-Token": await token() },
          body: JSON.stringify({ page: folder, bar_phase: offsetFor(chosen) }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.error ? W.t(data.error) : W.t("the library refused it ({status})", { status: r.status }));
        say(status, W.t("Analysing the song again with the new bar lines…"));
        cancel.textContent = W.t("Close"); // the job goes on without the dialog
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
      const command = h("code", { class: "cmd", translate: "no", "data-testid": "bars-command" });
      const showCommand = () => (command.textContent = commandFor(offsetFor(chosen)));
      const copy = h("button", {
        type: "button", class: "btn", "data-testid": "bars-copy",
        onclick: async () => {
          try {
            await navigator.clipboard.writeText(command.textContent);
            app.toast(W.t("Command copied."));
          } catch (err) {
            getSelection().selectAllChildren(command); // no clipboard here: selected, to copy by hand
          }
        },
      }, W.t("Copy"));
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
      if (!served) how = [h("p", null, W.t("Opened from disk, the command line moves them, in the folder of the recording:")), h("div", { class: "cmd-row" }, command, copy)];
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
          (cancel = h("button", { type: "button", class: "btn", "data-testid": "bars-cancel", onclick: () => dialog.close() }, W.t("Cancel"))),
          served && !store.get().wordsElsewhere ? go : null),
      );
    }

    app.openBarLines = () => {
      if (!dialog) {
        dialog = h("dialog", { class: "words-dialog bars-dialog", "aria-labelledby": "barsTitle", "data-testid": "bars-dialog" });
        document.body.append(dialog);
      }
      if (polling) return dialog.showModal(); // a job runs: its status, as it was left
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
