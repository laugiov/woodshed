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
    let elsewhere = false; // this device does not add words (mayAdd)
    const stopPolling = () => {
      clearInterval(polling);
      polling = null;
    };

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
    // What the library says while placing the words (lyrics.add_to_page), in core/i18n-fr.js; an
    // error's text is the library's own, in English.
    function heard(message) {
      const m = /^(\d+) of (\d+) lines placed on the voice$/.exec(message);
      return m ? W.t("{sung} of {n} lines placed on the voice", { sung: m[1], n: m[2] }) : W.t(message);
    }

    async function token() {
      const r = await fetch("/api/token", { cache: "no-store" });
      const data = await r.json();
      if (!r.ok || typeof data.token !== "string") throw new Error(W.t("the library did not answer: is woodshed app still running?"));
      return data.token;
    }

    // Said again after the reload that shows the words: the page that asked knows it is done.
    const DONE = "woodshed:words-placed:" + folder; // one origin serves every song of the library
    function placed(message, notes) {
      stopPolling();
      const said = [message].concat((notes || []).map(note)).join(". ");
      try {
        sessionStorage.setItem(DONE, said);
      } catch (err) {
        /* no storage: the words show, without the message */
      }
      if (app.store.get().playing) {
        reloadWhenStopped = true; // the words appear when the music stops, not in the middle of it
        say(W.t("{message}. They appear when you stop playing.", { message }));
      } else {
        say(W.t("{message}. Loading them…", { message }));
        location.reload();
      }
    }

    // A note of the library on the words placed; the fixes of the sheet it left out, counted (app.py _commit_words).
    function note(text) {
      const m = /^(\d+) lines fixed on the sheet were left out: their text changed\.$/.exec(text);
      return m ? W.t("{n} lines fixed on the sheet were left out: their text changed.", { n: m[1] }) : W.t(text);
    }

    // The lines fixed on the sheet (spec 028): placing the words again keeps the fixes whose line reads the same.
    function fixedNote() {
      const el = $("wordsFixed");
      if (!el) return;
      const n = Object.keys(app.wordFixes()).filter((k) => !W.typedWords.KEY.test(k)).length; // typed lines are kept as they are
      el.hidden = !n;
      el.textContent = n === 1
        ? W.t("1 line is fixed on the sheet: placing the words again keeps each fix whose line still reads the same here.")
        : W.t("{n} lines are fixed on the sheet: placing the words again keeps each fix whose line still reads the same here.", { n });
    }

    // How long is left, from how fast the share grew since it started moving.
    let since = null;
    function left(percent) {
      if (!(percent > 0)) return "";
      if (since === null) since = { t: Date.now(), p: percent };
      const done = percent - since.p;
      if (done < 5 || percent >= 95) return "";
      const seconds = Math.round(((Date.now() - since.t) / 1000) * ((100 - percent) / done));
      return " · " + (seconds < 90 ? W.t("about {n} s left", { n: Math.max(5, Math.round(seconds / 5) * 5) }) : W.t("about {n} min left", { n: Math.round(seconds / 60) }));
    }

    // The library's answer about this song's job, until it is done.
    function follow(id) {
      stopPolling();
      since = null;
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
          if (song && song.words && !app.words) return placed(W.t("The words are placed"));
          stopPolling();
          ready(true);
          return say(W.t("The library was restarted before the words were placed: place them again."), true);
        }
        if (job.status === "failed") {
          stopPolling();
          ready(true);
          say(W.t("The words could not be placed: {why}", { why: job.message }), true);
        } else if (job.status === "done") {
          working(true, 100);
          placed(heard(job.message), job.notes);
        } else if (job.status === "queued") {
          working(true);
          say(W.t("Waiting for the song being analysed…"));
        } else {
          working(true, job.percent);
          say(sentence(heard(job.message || "listening to the voice")) + left(job.percent));
        }
      }, 1500);
    }

    async function place() {
      const text = $("wordsText").value;
      if (!text.trim()) return say(W.t("Paste the words first."), true);
      ready(false);
      working(true);
      say(W.t("Sending…"));
      try {
        const r = await fetch("/api/lyrics", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Woodshed-Token": await token() },
          body: JSON.stringify({ page: folder, text }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.error ? W.t(data.error) : W.t("the library refused them ({status})", { status: r.status }));
        say(W.t("Listening to the voice: about a minute, longer the first time (the speech model is downloaded once)."));
        working(true);
        follow(data.id);
      } catch (err) {
        say(err.message, true);
        ready(true);
      }
    }

    const closeRow = () =>
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn", "data-testid": "words-close", onclick: () => dialog.close() }, W.t("Close")));

    function body(draft) {
      const old = window.WOODSHED_LYRICS && typeof window.WOODSHED_LYRICS.text === "string" ? window.WOODSHED_LYRICS.text : "";
      const intro = h(
        "p",
        { class: "hint", id: "wordsHow" },
        W.t("One line per sung line. Part names in brackets ([Chorus]) help; rows of chords are ignored. Write numbers as words."),
      );
      if (!hasVoice) {
        return [h("p", null, W.t("The words are placed on the singer's track, and this page has none yet. Build the song with its instrument tracks (stems) first.")), closeRow()];
      }
      if (!served) {
        const where = folder ? h("span", { translate: "no" }, folder) : W.t("the page");
        return [
          h("p", null, W.nodes(W.t("This page is opened from the disk: save the words in a text file (words.txt), then run, in the folder that holds {folder}:"), { folder: where })),
          h("pre", { class: "cmd", "data-testid": "words-command", translate: "no" }, 'woodshed lyrics "' + (folder || "Song.woodshed") + '" words.txt'),
          h("p", { class: "hint" }, W.t("Or open the song from the library (woodshed app) to paste them here.")),
          intro,
          closeRow(),
        ];
      }
      const text = h("textarea", {
        id: "wordsText", rows: "14", spellcheck: "false", "aria-label": W.t("The words of the song"), "aria-describedby": "wordsHow",
        "data-testid": "words-text", placeholder: W.t("[Verse 1]\nThe first line as it is sung\nThe second line\n\n[Chorus]\n…"), translate: "no",
      });
      text.value = typeof draft === "string" ? draft : old;
      return [
        intro,
        text,
        h("p", { class: "hint" }, W.t("Placed on this computer by MMS, a speech model by Meta (CC BY-NC 4.0: non-commercial use), downloaded once (1.2 GB). The words stay in your library.")),
        h("p", { class: "hint", id: "wordsFixed", "data-testid": "words-fixed", hidden: "" }),
        h("p", { id: "wordsStatus", class: "status", role: "status", "data-testid": "words-status" }),
        h(
          "div",
          { class: "words-progress", id: "wordsProgress", hidden: "" },
          h("span", { class: "spin", "aria-hidden": "true" }),
          h("progress", { id: "wordsBar", max: "100", "aria-label": W.t("Placing the words") }),
          h("span", { id: "wordsPct", class: "pct", "data-testid": "words-percent" }),
        ),
        h(
          "div",
          { class: "dialog-actions" },
          h("button", { type: "button", class: "btn", onclick: () => dialog.close() }, W.t("Close")),
          h("button", { type: "button", class: "btn primary", id: "wordsPlace", "data-testid": "words-place", onclick: place }, old ? W.t("Place them again") : W.t("Place the words")),
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
      // Nothing to do here for this device: no button that leads to a refusal.
      headerBtn.hidden = true;
      elsewhere = true;
      app.store.set({ wordsElsewhere: true });
      if (dialog) fill();
    }

    // The dialog's content, said again in the other language with what it holds kept: the paste,
    // and a placement under way (its next answer says where it is in the new language).
    function fill() {
      const area = $("wordsText");
      const status = $("wordsStatus");
      const progress = $("wordsProgress");
      const kept = status && {
        text: status.textContent, warn: status.classList.contains("warn"), busy: !progress.hidden,
        value: $("wordsBar").getAttribute("value"), pct: $("wordsPct").textContent, disabled: $("wordsPlace").disabled,
      };
      if (elsewhere) {
        clear(dialog, h("h2", { id: "wordsTitle" }, W.t("The words")), h("p", { "data-testid": "words-elsewhere" }, W.t("Words are added from the computer that runs the library, like songs.")), closeRow());
        return;
      }
      clear(dialog, h("h2", { id: "wordsTitle" }, app.words ? W.t("The words") : W.t("Add the words")), body(area ? area.value : undefined));
      fixedNote();
      if (!kept || !$("wordsStatus")) return;
      say(kept.text, kept.warn);
      $("wordsProgress").hidden = !kept.busy;
      if (kept.value !== null) $("wordsBar").setAttribute("value", kept.value);
      $("wordsPct").textContent = kept.pct;
      $("wordsPlace").disabled = kept.disabled;
    }

    function open() {
      if (!dialog) {
        dialog = h("dialog", { class: "words-dialog", "aria-labelledby": "wordsTitle", "data-testid": "words-dialog" });
        document.body.appendChild(dialog);
        fill();
      } // built once: closed and opened again, it keeps a paste not sent yet, and a placement under way
      fixedNote();
      if (!dialog.open) dialog.showModal();
      const area = $("wordsText");
      if (area) area.focus();
    }

    // In the header too, where it is seen: in the accent colour while the song has no words.
    const headerBtn = $("wordsBtn");
    if (hasVoice) {
      headerBtn.hidden = false;
      headerBtn.textContent = app.words ? W.t("Words") : W.t("+ Add the words");
      headerBtn.classList.toggle("primary", !app.words);
      headerBtn.addEventListener("click", open);
      if (served) mayAdd(); // a phone of the band: asked once, when the page opens
    }

    // The words placed before this load: said once, now that they show.
    try {
      const said = sessionStorage.getItem(DONE);
      if (said) {
        sessionStorage.removeItem(DONE);
        setTimeout(() => app.toast(W.t("Words placed: {what}", { what: said })), 300);
      }
    } catch (err) {
      /* no storage */
    }

    app.store.on((s, changed) => {
      if (reloadWhenStopped && changed.has("playing") && !s.playing) location.reload();
    });

    // A link from the library ("add the words") opens the dialog.
    if (location.hash === "#words") {
      history.replaceState(null, "", location.pathname + location.search);
      setTimeout(open, 0);
    }

    // The other language: the header's button and the dialog, with what the dialog holds.
    function relabel() {
      if (hasVoice) headerBtn.textContent = app.words ? W.t("Words") : W.t("+ Add the words");
      if (dialog) fill();
    }

    return { open, relabel, render() {} };
  };
})();
