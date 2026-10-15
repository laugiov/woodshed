// The words of the song, pasted in the page: served by `woodshed app`, the library places them on
// the voice in the background (a minute of the speech model) and the page reloads with them.
// Opened from disk, the page has no app to do it: the dialog gives the command instead.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear } = W;

  W.views = W.views || {};

  W.views.words = function words(app) {
    const served = location.protocol === "http:" || location.protocol === "https:";
    const folder = decodeURIComponent(location.pathname.split("/").slice(-2)[0] || "");
    const hasVoice = app.song.tracks.some((t) => t.id === "solo-vocals"); // the words are placed on it
    let dialog = null;
    let polling = null;
    let reloadWhenStopped = false;

    function say(text, warn) {
      const el = $("wordsStatus");
      if (!el) return;
      el.textContent = text;
      el.classList.toggle("warn", !!warn);
    }

    function ready(on) {
      const button = $("wordsPlace");
      if (button) button.disabled = !on;
      if (on) working(false);
    }

    // A spinner while the library works; the bar fills as the voice is heard (no share yet: it moves).
    function working(on, percent) {
      const box = $("wordsProgress");
      if (!box) return;
      box.hidden = !on;
      const bar = $("wordsBar");
      if (typeof percent === "number") {
        bar.value = percent;
        $("wordsPct").textContent = percent + " %";
      } else {
        bar.removeAttribute("value");
        $("wordsPct").textContent = "";
      }
    }
    const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1);

    async function token() {
      const r = await fetch("/api/token", { cache: "no-store" });
      const data = await r.json();
      if (!r.ok || typeof data.token !== "string") throw new Error("the library did not answer: is woodshed app still running?");
      return data.token;
    }

    function placed(message) {
      clearInterval(polling);
      if (app.store.get().playing) {
        reloadWhenStopped = true; // the words appear when the music stops, not in the middle of it
        say(message + ". They appear when you stop playing.");
      } else {
        say(message + ". Loading them…");
        location.reload();
      }
    }

    // The library's answer about this song's job, until it is done.
    function follow(id) {
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
          // Forgotten by the library: it was restarted, or the job ended long ago. Words found now
          // on a page that had none are these; words placed again cannot be told from the old ones.
          const song = data.songs.find((s) => s.folder === folder);
          if (song && song.words && !app.words) return placed("The words are placed");
          clearInterval(polling);
          ready(true);
          return say("The library was restarted before the words were placed: place them again.", true);
        }
        if (job.status === "failed") {
          clearInterval(polling);
          ready(true);
          say("The words could not be placed: " + job.message, true);
        } else if (job.status === "done") {
          working(true, 100);
          placed(job.message);
        } else if (job.status === "queued") {
          working(true);
          say("Waiting for the song being analysed…");
        } else {
          working(true, job.percent);
          say(sentence(job.message || "listening to the voice"));
        }
      }, 1500);
    }

    async function place() {
      const text = $("wordsText").value;
      if (!text.trim()) return say("Paste the words first.", true);
      ready(false);
      working(true);
      say("Sending…");
      try {
        const r = await fetch("/api/lyrics", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Woodshed-Token": await token() },
          body: JSON.stringify({ page: folder, text }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.error || "the library refused them (" + r.status + ")");
        say("Listening to the voice: about a minute, longer the first time (the speech model is downloaded once).");
        working(true);
        follow(data.id);
      } catch (err) {
        say(err.message, true);
        ready(true);
      }
    }

    const closeRow = () =>
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn", "data-testid": "words-close", onclick: () => dialog.close() }, "Close"));

    function body() {
      const old = window.WOODSHED_LYRICS && typeof window.WOODSHED_LYRICS.text === "string" ? window.WOODSHED_LYRICS.text : "";
      const intro = h(
        "p",
        { class: "hint", id: "wordsHow" },
        "One line per sung line. Part names in brackets ([Chorus]) help; rows of chords are ignored. Write numbers as words.",
      );
      if (!hasVoice) {
        return [h("p", null, "The words are placed on the singer's track, and this page has none yet. Build the song with its instrument tracks (stems) first."), closeRow()];
      }
      if (!served) {
        return [
          h("p", null, "This page is opened from the disk: save the words in a text file (words.txt), then run, in the folder that holds " + (folder || "the page") + ":"),
          h("pre", { class: "cmd", "data-testid": "words-command" }, 'woodshed lyrics "' + (folder || "Song.woodshed") + '" words.txt'),
          h("p", { class: "hint" }, "Or open the song from the library (woodshed app) to paste them here."),
          intro,
          closeRow(),
        ];
      }
      const text = h("textarea", {
        id: "wordsText", rows: "14", spellcheck: "false", "aria-label": "The words of the song", "aria-describedby": "wordsHow",
        "data-testid": "words-text", placeholder: "[Verse 1]\nThe first line as it is sung\nThe second line\n\n[Chorus]\n…",
      });
      text.value = old;
      return [
        intro,
        text,
        h("p", { class: "hint" }, "Placed on this computer by MMS, a speech model by Meta (CC BY-NC 4.0: non-commercial use), downloaded once (1.2 GB). The words stay in your library."),
        h("p", { id: "wordsStatus", class: "status", role: "status", "data-testid": "words-status" }),
        h(
          "div",
          { class: "words-progress", id: "wordsProgress", hidden: "" },
          h("span", { class: "spin", "aria-hidden": "true" }),
          h("progress", { id: "wordsBar", max: "100", "aria-label": "Placing the words" }),
          h("span", { id: "wordsPct", class: "pct", "data-testid": "words-percent" }),
        ),
        h(
          "div",
          { class: "dialog-actions" },
          h("button", { type: "button", class: "btn", onclick: () => dialog.close() }, "Close"),
          h("button", { type: "button", class: "btn primary", id: "wordsPlace", "data-testid": "words-place", onclick: place }, old ? "Place them again" : "Place the words"),
        ),
      ];
    }

    // A phone of the band reads and plays; the computer that runs the app adds words, as it adds songs.
    async function mayAdd() {
      try {
        const data = await (await fetch("/api/songs", { cache: "no-store" })).json();
        if (data.can_upload !== false) return;
      } catch (err) {
        return; // sending says what is wrong
      }
      headerBtn.classList.remove("primary"); // nothing to do here for this device
      clear(dialog, h("h2", { id: "wordsTitle" }, "The words"), h("p", { "data-testid": "words-elsewhere" }, "Words are added from the computer that runs the library, like songs."), closeRow());
    }

    function open() {
      if (!dialog) {
        dialog = h("dialog", { class: "words-dialog", "aria-labelledby": "wordsTitle", "data-testid": "words-dialog" });
        document.body.appendChild(dialog);
        clear(dialog, h("h2", { id: "wordsTitle" }, app.words ? "The words" : "Add the words"), body());
        if (served && hasVoice) mayAdd();
      } // built once: closed and opened again, it keeps a paste not sent yet, and a placement under way
      if (!dialog.open) dialog.showModal();
      const area = $("wordsText");
      if (area) area.focus();
    }

    // In the header too, where it is seen: in the accent colour while the song has no words.
    const headerBtn = $("wordsBtn");
    if (hasVoice) {
      headerBtn.hidden = false;
      headerBtn.textContent = app.words ? "Words" : "+ Add the words";
      headerBtn.classList.toggle("primary", !app.words);
      headerBtn.addEventListener("click", open);
    }

    app.store.on((s, changed) => {
      if (reloadWhenStopped && changed.has("playing") && !s.playing) location.reload();
    });

    // A link from the library ("add the words") opens the dialog.
    if (location.hash === "#words") {
      history.replaceState(null, "", location.pathname + location.search);
      setTimeout(open, 0);
    }

    return { open, render() {} };
  };
})();
