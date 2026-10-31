// Header (title, facts, instrument), practice path, credits, stage mode, toast, menus, doubt pop.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, chordNode, fmt } = W;

  const INSTRUMENTS = () => [["guitar", W.t("Guitar")], ["bass", W.t("Bass")], ["piano", W.t("Keys")], ["drums", W.t("Drums")], ["voice", W.t("Voice")]];
  const PART = { guitar: "guitar", bass: "bass", piano: "keys", drums: "drums", voice: "voice" };
  const LEARN = () => ({
    guitar: [W.t("Learn the shapes"), W.t("Your part alone. Click a shape to hear it.")],
    bass: [W.t("Learn the line"), W.t("The bass alone, with its tab.")],
    piano: [W.t("Learn the voicings"), W.t("The chords alone, as played on the record.")],
    drums: [W.t("Learn the groove"), W.t("The drums alone, with the notation.")],
    voice: [W.t("Find your key"), W.t("The voice alone. Set your voice type on the right.")],
  });

  W.views = W.views || {};

  W.views.header = function header(app) {
    const { song, store } = app;
    const meta = song.song;

    // The song's key, or how it moves (spec 012): "C major → D major", "C major, 2 key changes".
    function keyNodes(s, cls) {
      const named = (name) => {
        const minor = name.endsWith("m");
        return h("b", null, chordNode(minor ? name.slice(0, -1) : name, cls), " " + (minor ? W.t("minor") : W.t("major")));
      };
      const n = song.regionCount;
      if (n === 1) return named(song.keyName(s.transpose));
      const first = named(song.keyName(s.transpose, 0));
      if (n === 2) return [first, " → ", named(song.keyName(s.transpose, 1))];
      return [first, W.t(", {n} key changes", { n: n - 1 })];
    }
    app.keyNodes = keyNodes;

    function renderFacts(s) {
      const open = song.doubts().filter((d) => !d.chord.fixed && d.chord.doubt.kind === "chord");
      const spots = new Set(open.map((d) => d.chord.doubt.id)).size;
      clear(
        $("facts"),
        h("span", null, h("b", null, String(app.songBpm)), " BPM"),
        h("span", null, h("b", null, meta.beats_per_bar + "/4")),
        h("span", { "data-testid": "key-facts" }, W.nodes(W.t("Key {key}"), { key: keyNodes(s) })),
        h("span", null, fmt(Math.round(meta.duration))), // rounded, as the library lists it
        spots
          ? h("button", { type: "button", class: "warnfact", "data-goto": open[0].bar, "data-testid": "spots" }, spots === 1 ? W.t("1 spot to check by ear") : W.t("{n} spots to check by ear", { n: spots }))
          : h("span", { class: "okfact" }, W.t("Nothing to check by ear")),
        meta.analysis.chords_reliable ? null : h("span", { class: "warnfact", "data-testid": "unreliable" }, W.t("Little harmony found: chords may be wrong")),
      );
    }

    // Drawn again under the button pressed: the keyboard stays on it (spec 025), and it says it is pressed.
    function renderInstruments(s) {
      const el = $("instruments");
      W.keepFocus(el, () =>
        clear(
          el,
          INSTRUMENTS().map(([id, label]) =>
            h("button", { type: "button", class: s.inst === id ? "on" : "", "aria-pressed": String(s.inst === id), "data-inst": id, "data-testid": "inst-" + id, onclick: () => app.setInstrument(id) }, label),
          ),
        ),
      );
    }

    function renderPath(s) {
      const stems = song.tracks.length > 1;
      // Keys not heard on a six-stem page: no voicings to learn, the chords of the chart (spec 015).
      const [t2, d2] = !stems
        ? [W.t("Learn the chords"), W.t("The chart and your panel, with the full mix.")]
        : s.inst === "piano" && app.notHeard("piano")
          ? [W.t("Learn the chords"), W.t("The chords of the chart, with the panel on the right.")]
          : LEARN()[s.inst];
      const steps = [
        [W.t("Listen"), W.t("Full band, original tempo. Follow the chart.")],
        [t2, d2],
        [W.t("Loop it slow"), W.t("From 70% tempo, 5 BPM faster each pass.")],
        [W.t("Play with the band"), stems ? W.t("Your part is muted. The band is yours.") : W.t("The full mix, with a count-in.")],
      ];
      W.keepFocus($("path"), () => clear(
        $("path"),
        steps.map(([title, detail], i) =>
          h(
            "button",
            { type: "button", class: "step" + (s.step === i + 1 ? " on" : ""), "data-step": i + 1, "data-testid": "step-" + (i + 1), onclick: () => app.setStep(i + 1) },
            h("span", { class: "n" }, W.t("Step {n}", { n: i + 1 })),
            h("span", { class: "t" }, title),
            h("span", { class: "d" }, detail),
          ),
        ),
      ));
    }

    // Which woodshed wrote the page's code and which found its chords (spec 026): `woodshed app` gives an
    // older page this version's code and keeps its analysis. Both come with the page: the same served or from disk.
    function versionLine() {
      const made = song.data.page || {};
      const page = made.version;
      const found = meta.meta.version;
      const revision = meta.meta.analysis;
      if (typeof page !== "string") return W.t("Chords and beats found by woodshed {analysis}", { analysis: found });
      // The revisions decide when both are known: an update from git can change the analysis, not the number.
      if (typeof revision === "number" && typeof made.analysis === "number") {
        if (revision < made.analysis) {
          return W.t("Page: woodshed {page} · chords and beats found by woodshed {analysis} (older analysis: add the song again to get the new one; chords you corrected may need checking again)", { page, analysis: found });
        }
        if (revision > made.analysis) {
          // Analysed by a later woodshed than the one running the page: the versions, no claim.
          return W.t("Page: woodshed {page} · chords and beats found by woodshed {analysis}", { page, analysis: found });
        }
        if (page !== found) return W.t("Page: woodshed {page} · chords and beats found by woodshed {analysis} (still current)", { page, analysis: found });
      }
      if (page === found) return W.t("Page and analysis: woodshed {version}", { version: page });
      return W.t("Page: woodshed {page}", { page });
    }

    function renderCredits() {
      const a = meta.analysis;
      const file = h("span", { translate: "no" }, meta.file);
      const lines = [
        versionLine(),
        W.nodes(W.t("Made from {file} on this computer: nothing was uploaded."), { file }),
        a.stems
          ? a.beats === "beat_this"
            ? W.t("Instrument tracks separated with Demucs (MIT), beats and downbeats found with beat_this (MIT).")
            : W.t("Instrument tracks separated with Demucs (MIT).")
          : W.t("Analysed from the full mix only (no stems): instrument parts need woodshed with stems."),
        W.t("Notation drawn with VexFlow (MIT). Preview sounds: FluidR3_GM SoundFont by Frank Wen (MIT). Fonts: Barlow Condensed, Atkinson Hyperlegible, JetBrains Mono, Noto Music (SIL Open Font License)."),
      ];
      clear($("foot"), lines.map((l) => h("span", null, l)));
    }

    // The song's own title and artist (spec 031): the band's, edited here, else the recording's.
    let naming = false;
    function renderTitle(s) {
      if (naming) return;
      const shown = app.shownTitle();
      $("songTitle").textContent = shown;
      document.title = shown + " · woodshed";
      $("titleEdit").hidden = !s.canShare;
      $("titleForm").hidden = true;
      $("songTitle").hidden = false;
    }
    function openTitle() {
      const s = store.get();
      const parts = s.bandTitle || s.bandArtist ? [s.bandArtist, s.bandTitle || meta.title] : meta.title.includes(" - ") ? [meta.title.slice(0, meta.title.indexOf(" - ")), meta.title.slice(meta.title.indexOf(" - ") + 3)] : ["", meta.title];
      naming = true;
      const artist = h("input", { type: "text", maxlength: "120", "data-testid": "title-artist", "aria-label": W.t("Artist"), placeholder: W.t("Artist") });
      const name = h("input", { type: "text", maxlength: "120", "data-testid": "title-name", "aria-label": W.t("Title"), placeholder: W.t("Title") });
      artist.value = parts[0];
      name.value = parts[1];
      const done = async (change) => {
        naming = false;
        if (change) {
          const band = await app.shareBand(change);
          if (band) store.set({ bandTitle: band.title || "", bandArtist: band.artist || "" });
          else app.toast(W.t("The title was not saved."));
        }
        renderTitle(store.get());
        $("titleEdit").focus();
      };
      const form = $("titleForm");
      form.onsubmit = (e) => {
        e.preventDefault();
        done({ artist: artist.value, title: name.value });
      };
      form.onkeydown = (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          done(null);
        }
      };
      clear(form, artist, name,
        h("button", { type: "submit", class: "btn primary" }, W.t("Save")),
        h("button", { type: "button", class: "btn ghost", onclick: () => done(null) }, W.t("Cancel")),
        h("button", { type: "button", class: "btn ghost", "data-testid": "title-reset", onclick: () => done({ artist: "", title: "" }) }, W.t("Back to the recording's title")));
      form.hidden = false;
      $("songTitle").hidden = true;
      $("titleEdit").hidden = true;
      name.focus();
    }
    $("titleEdit").addEventListener("click", openTitle);

    // The song's notes (spec 031): who starts, how it ends; written once, on every device of the band.
    let notesOpen = false;
    function renderNotes(s) {
      if (notesOpen) return;
      const lines = s.bandNote ? s.bandNote.split("\n") : [];
      const tool = !s.canShare
        ? null
        : lines.length
          ? h("button", { type: "button", class: "btn ghost notes-edit", "data-testid": "notes-edit", "aria-label": W.t("Edit the notes"), title: W.t("Edit the notes"), onclick: openNotes }, "✎")
          : h("button", { type: "button", class: "btn ghost notes-add", "data-testid": "notes-add", onclick: openNotes }, W.t("+ Notes"));
      clear($("songNotes"),
        lines.length ? h("div", { class: "band-note", "data-testid": "band-note" }, h("span", { class: "note-label" }, W.t("Notes")), lines.map((l) => h("p", { translate: "no" }, l))) : null,
        tool);
      $("songNotes").hidden = !lines.length && !tool;
    }
    function openNotes() {
      notesOpen = true;
      const area = h("textarea", { class: "notes-input", rows: "4", maxlength: "1000", "data-testid": "notes-input", "aria-label": W.t("Notes on this song"), placeholder: W.t("Who starts, how it ends, cues…") });
      area.value = store.get().bandNote;
      const insert = (label) => {
        const v = area.value;
        area.value = v + (v && !v.endsWith("\n") ? "\n" : "") + label + " ";
        area.focus();
        area.setSelectionRange(area.value.length, area.value.length);
      };
      const done = async (keep) => {
        if (!notesOpen) return;
        notesOpen = false;
        if (keep && area.value !== store.get().bandNote) {
          const band = await app.shareBand({ note: area.value });
          if (band) store.set({ bandNote: band.note || "" });
          else app.toast(W.t("The notes were not saved."));
        }
        renderNotes(store.get());
      };
      area.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          done(false);
        } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) done(true);
      });
      const keepFocus = (e) => e.preventDefault(); // a quick insert leaves the cursor in the text
      clear($("songNotes"), h("div", { class: "notes-editor" }, area, h("div", { class: "notes-tools" },
        h("button", { type: "button", class: "btn", "data-testid": "notes-start", onmousedown: keepFocus, onclick: () => insert(W.t("Start:")) }, W.t("Start:")),
        h("button", { type: "button", class: "btn", "data-testid": "notes-end", onmousedown: keepFocus, onclick: () => insert(W.t("End:")) }, W.t("End:")),
        h("button", { type: "button", class: "btn primary", "data-testid": "notes-save", onclick: () => done(true) }, W.t("Save")),
        h("button", { type: "button", class: "btn ghost", onclick: () => done(false) }, W.t("Cancel")))));
      $("songNotes").hidden = false;
      area.focus();
    }

    store.on((s, changed) => {
      if (changed.has("bandTitle") || changed.has("bandArtist") || changed.has("canShare")) renderTitle(s);
      if (changed.has("bandNote") || changed.has("canShare")) renderNotes(s);
      if (changed.has("transpose") || changed.has("corrections")) renderFacts(s);
      if (changed.has("inst")) renderInstruments(s);
      if (changed.has("inst") || changed.has("step")) renderPath(s);
    });

    return {
      render(s) {
        renderTitle(s);
        renderNotes(s);
        // Served by `woodshed app`: the library is one level up. Opened from disk, there is none.
        $("backLink").hidden = location.protocol === "file:";
        const pending = song.view.pending;
        if (pending) {
          const minutes = Math.max(1, Math.round(pending.eta_seconds / 60));
          $("pending").textContent = W.t(
            "Separating the instruments on this computer. Reload this page in about {n} min for the instrument tracks and parts; until then it plays the full mix.",
            { n: minutes },
          );
          $("pending").hidden = false;
        }
        renderFacts(s);
        renderInstruments(s);
        renderPath(s);
        renderCredits();
      },
      part: (inst) => PART[inst],
    };
  };

  W.views.stage = function stage(app) {
    const { song, store } = app;
    function render(s) {
      $("stage").hidden = !s.stage;
      if (!s.stage) return;
      $("stage").classList.toggle("keyed", song.regionCount > 1); // its key line keeps its height
      const u = Math.floor(s.beat / song.per);
      const c = song.chordAtBeat(s.beat);
      const up = song.upcoming(s.beat, 2);
      const shift = app.showShapes(s) ? s.capo : 0;
      clear($("stNow"), chordNode(app.nameFor(c, shift, s)));
      const shapes = s.inst === "guitar" && app.shapeFor
        ? [[c, ""], [up[0], "next"]].filter(([x]) => x && x.pc >= 0).map(([x, cls]) => {
            const shape = app.shapeFor(x, s);
            return shape ? h("span", { class: cls, "aria-hidden": "true" }, app.guitarDiagram(shape), cls ? h("small", null, W.t("next")) : null) : null;
          })
        : [];
      clear($("stShape"), app.nowHint(c, s), shapes.length ? h("div", { class: "st-shapes", "data-testid": "stage-shapes" }, shapes) : null);
      clear($("stNext"), up[0] ? chordNode(app.nameFor(up[0], shift, s)) : W.t("end"));
      clear($("stThen"), up[1] ? chordNode(app.nameFor(up[1], shift, s)) : "");
      // Where the band is: the section, the bar in it, and the next section two bars ahead.
      const list = app.sections();
      const k = list.length ? song.sectionIndex(u, list) : -1;
      const sec = k >= 0 ? list[k] : { name: W.t("Bar {n}", { n: u + 1 }), start: u, end: u + 1 };
      const len = sec.end - sec.start;
      const per = Math.ceil(len / 16); // a dot per bar, or per few bars in a long section
      const at = Math.floor((u - sec.start) / per);
      clear($("stMap"), Array.from({ length: Math.ceil(len / per) }, (_, i) => h("i", { class: i === at ? "on" : i < at ? "done" : "" })));
      $("stSection").textContent = W.partName(sec);
      // The recording in another key (views/pitch.js) is said on the stand too.
      const shifted = s.pitchStatus && s.pitchStatus.state === "on" ? " · ♪ " + (s.transpose > 0 ? "+" : "−") + Math.abs(s.transpose) : "";
      // On a song whose key changes, the key of the bar playing is always on the top line (spec 013).
      const keyed = song.regionCount > 1;
      const keyOf = (region) => song.keyWords(song.keyName(s.transpose, region));
      const here = keyed ? " · " + keyOf(song.regionOf(u)) : "";
      $("stTop").textContent = W.t("bar {n} of {len}", { n: u - sec.start + 1, len }) + here + " · " + s.bpm + " BPM" + shifted;
      const next = k >= 0 ? list[k + 1] : null;
      const left = sec.end - u;
      // A next part that starts in another key than the bar before it says it (spec 012, 013).
      const nextRegion = next ? song.regionOf(next.start) : null;
      const inKey = keyed && next && nextRegion !== song.regionOf(next.start - 1) ? " · " + W.t("in {key}", { key: keyOf(nextRegion) }) : "";
      const what = next ? W.partName(next) : k >= 0 && k === list.length - 1 ? W.t("End") : "";
      // The next part two bars ahead; stopped earlier in a part, what comes next, to be ready for it.
      const soon = left <= 2 ? (left === 1 ? W.t("{part} next bar", { part: what }) : W.t("{part} in {n} bars", { part: what, n: left })) : "";
      const coming = !what ? "" : (soon || (!s.playing ? W.t("Next part: {part}", { part: what }) : "")) + ((soon || !s.playing) && next ? inKey : "");
      if ($("stComing").textContent !== coming) $("stComing").textContent = coming;
      // A key change inside the part (not where a part starts: the part line says that one) on its own line:
      // two bars ahead, on the bar, and stopped, where it is (spec 013).
      let keyLine = "";
      if (keyed) {
        // Not where a part starts (the part line says that one); stopped, only a change left in this part.
        const midPart = (change) => change && !list.some((p) => p.start === change.bar);
        const inside = (change) => midPart(change) && change.bar < sec.end;
        const ahead = song.changeAhead(u, 2, s.loopOn && s.loop);
        const now = song.keyChanges.find((c) => c.bar === u);
        if (s.playing && midPart(ahead)) {
          keyLine = ahead.bar - u === 1
            ? W.t("Key change next bar: {key}", { key: keyOf(ahead.region) })
            : W.t("Key change in {n} bars: {key}", { n: ahead.bar - u, key: keyOf(ahead.region) });
        } else if (s.playing && midPart(now)) keyLine = W.t("Now in {key}", { key: keyOf(now.region) });
        else if (!s.playing) {
          const rest = song.keyChanges.find((c) => c.bar > u && inside(c));
          if (rest) keyLine = W.t("Key change at bar {n}: {key}", { n: rest.bar + 1, key: keyOf(rest.region) });
        }
      }
      if ($("stKey").textContent !== keyLine) $("stKey").textContent = keyLine; // a live region: written on a change only
      renderLyrics(s, list, keyLine);
    }

    // The words on the stand: the line sung now, a bar showing how far into it, then the next
    // lines, with the name of the part they start. The singer gets them full width; guitar and
    // keys next to the chords; bass and drums keep the chords and the bars.
    // keyLine: the key change coming, also said above the words (the words stage hides the NEXT column on a
    // phone, and the voice stage at every width).
    function renderLyrics(s, list, keyLine) {
      const box = $("stLyrics");
      const words = app.words && app.sheetMode(s) === "lyrics" && s.inst !== "bass" && s.inst !== "drums";
      $("stage").classList.toggle("st-lyrics", !!words && s.inst !== "voice");
      $("stage").classList.toggle("st-voice", !!words && s.inst === "voice");
      box.hidden = !words;
      if (!words) return;
      const { rows } = app.words.rows();
      // Playing between lines (a solo), no line is lit: the next ones wait, with the part they start. Stopped,
      // the line to sing next comes first, "Next:" before it until the cursor is inside it.
      const at = s.playing ? app.lineNow(s) : null;
      const stopped = at ? null : app.lineStopped(rows, s);
      const from = at ? (at.now >= 0 ? at.now : at.next) : stopped.first;
      const k = at ? at.now : stopped.inside ? from : -1;
      // Another voice's line (an MC, a spoken intro: spec 028) is not the singer's: off the voice stage and "Next:".
      const sings = (r) => !(s.inst === "voice" && r.line.voice === "other");
      const shown = rows.slice(from).filter(sings).slice(0, 3);
      const out = keyLine ? [h("div", { class: "st-next-part st-key-words", "data-testid": "stage-key-words" }, keyLine)] : [];
      shown.forEach((r, i) => {
        const sec = app.sectionOf(r.firstBar);
        const before = i > 0 ? app.sectionOf(shown[i - 1].firstBar) : app.sectionOf(Math.floor(s.beat / song.per));
        if (sec && before && sec.name !== before.name) out.push(h("div", { class: "st-next-part" }, W.partName(sec)));
        const now = i === 0 && k >= 0 && r === rows[k];
        const ready = i === 0 && stopped && !now;
        // The chord still sounding (spec 027) on every line but the one sung (the big Now chord names it), "Next:"
        // included; never on the singer's stage, which keeps to the words.
        if (ready) out.push(h("div", { class: "st-next-label", "data-testid": "stage-next-label" }, W.t("Next:")));
        out.push(h("div", { class: "st-line" + (now ? " now" : ready ? " ready" : " later"), "data-testid": "stage-line" }, app.lyricLine(r, s, { stage: true, remind: s.inst !== "voice" && !now })));
        if (now) {
          const span = Math.max(0.1, (rows[k + 1] ? rows[k + 1].line.start : r.line.end) - r.line.start);
          const done = Math.max(0, Math.min(1, (s.time - r.line.start) / span));
          out.push(h("div", { class: "st-progress", "aria-hidden": "true" }, h("i", { style: { width: (done * 100).toFixed(1) + "%" } })));
        }
      });
      clear(box, out);
      app.unglueReminders(box);
    }
    // The stage's top (spec 031): the song's notes in one line (all of them on a tap) and, for a guitarist with a
    // capo, the same chord switch as the chart's. Drawn when they change, not on every beat.
    let noteOpen = false;
    $("stNote").addEventListener("click", () => {
      noteOpen = !noteOpen;
      renderTop(store.get());
    });
    function renderTop(s) {
      const lines = s.bandNote ? s.bandNote.split("\n") : [];
      $("stNote").hidden = !lines.length;
      $("stNote").setAttribute("aria-expanded", String(noteOpen));
      clear($("stNote"), (noteOpen ? lines : lines.slice(0, 1)).map((l) => h("span", { translate: "no" }, l)), !noteOpen && lines.length > 1 ? " …" : null);
      const capo = s.inst === "guitar" && s.pos === "open" && s.capo > 0;
      clear($("stView"), capo
        ? h("span", { class: "seg-ctl", role: "group", "aria-label": W.t("Chart shows") },
          h("button", { type: "button", class: s.view === "concert" ? "on" : "", "aria-pressed": String(s.view === "concert"), "data-testid": "stage-show-concert", onclick: () => store.set({ view: "concert" }) }, W.t("Real chords")),
          h("button", { type: "button", class: s.view === "shapes" ? "on" : "", "aria-pressed": String(s.view === "shapes"), "data-testid": "stage-show-shapes", onclick: () => store.set({ view: "shapes" }) }, W.t("Shapes, capo {n}", { n: s.capo })))
        : null);
    }
    store.on((s, changed) => {
      const keys = ["beat", "playing", "transpose", "capo", "pos", "bpm", "inst", "sheet", "view", "corrections", "pitchStatus"];
      if (changed.has("stage") || (s.stage && keys.some((key) => changed.has(key)))) render(s);
      if (["stage", "bandNote", "view", "capo", "inst", "pos"].some((key) => changed.has(key))) renderTop(s);
    });
    renderTop(store.get());
    return { render };
  };

  // Toast, menus and the doubt pop share one place and one way to close (Escape, click outside).
  W.views.popups = function popups(app) {
    const { song } = app;
    let toastTimer = 0;

    // `action`: {label, run}, a button in the toast (Undo), kept longer on screen.
    function toast(message, action) {
      const t = $("toast");
      clear(t, message, action ? h("button", { type: "button", class: "undo", "data-testid": "toast-action", onclick: () => {
        t.hidden = true;
        action.run();
      } }, action.label) : null);
      t.hidden = false;
      clearTimeout(toastTimer);
      // Kept while the keyboard is on its button (Undo).
      const hide = () => (t.contains(document.activeElement) ? (toastTimer = setTimeout(hide, 2000)) : (t.hidden = true));
      toastTimer = setTimeout(hide, action ? 8000 : 2600);
    }

    let opener = null;
    // restoreFocus: after Escape, the keyboard goes back to the control that opened the panel.
    function closeAll(restoreFocus) {
      const open = [...document.querySelectorAll(".menu, #pop")].some((m) => !m.hidden);
      document.querySelectorAll(".menu").forEach((m) => (m.hidden = true));
      $("pop").hidden = true;
      if (open && restoreFocus && opener && document.contains(opener)) opener.focus();
      if (open) opener = null;
    }

    function place(el, anchor, below) {
      const r = anchor.getBoundingClientRect();
      const w = el.offsetWidth;
      const hh = el.offsetHeight;
      const left = Math.min(Math.max(16, below ? r.left : r.right - w), window.innerWidth - w - 16);
      let top = below || r.top < window.innerHeight / 2 ? r.bottom + 8 : r.top - hh - 8;
      if (top + hh > window.innerHeight - 16) top = Math.max(16, r.top - hh - 8);
      el.style.left = left + "px";
      el.style.top = Math.max(16, top) + "px";
    }

    function openMenu(id, anchor) {
      const m = $(id);
      const wasOpen = !m.hidden;
      closeAll();
      if (wasOpen) return;
      m.hidden = false;
      opener = anchor;
      place(m, anchor, false);
      const f = m.querySelector("button, input");
      if (f) f.focus();
    }

    // The chord the chart shows comes from the whole song (what comes before and after, the key, the
    // same part played again); the shares come from this bar heard alone. When they disagree, say so,
    // and keep the analysis's chord in the list: a correction can always go back to it.
    // `from`: the control the keyboard goes back to (the bar holding a mark that is no button itself).
    // `toNext`: opened by "Next chord to check in this bar", the keyboard stays on that button.
    function openDoubt(button, from, toNext) {
      const [u, k] = button.getAttribute("data-ref").split("_").map(Number);
      const chord = song.bars[u].chords[k];
      const s = app.store.get();
      const same = song.same;
      const analysed = app.analysedChord(chord.doubt.id) || chord;
      const alts = chord.doubt.alternatives.slice();
      if (!alts.some((a) => same(a, analysed))) alts.push({ pc: analysed.pc, quality: analysed.quality, share: null });
      const node = (c) => W.chordNode(app.nameFor(c, 0, s, u)); // spelled in the bar's key (spec 012)
      const named = (c) => W.prettyText(app.nameFor(c, 0, s, u));
      let note;
      if (chord.fixed && same(chord, analysed)) note = W.nodes(W.t("You confirmed {chord}, the analysis's chord."), { chord: node(chord) });
      else if (chord.fixed) note = W.nodes(W.t("Your correction: {chord}. The analysis had {analysed}."), { chord: node(chord), analysed: node(analysed) });
      else if (same(alts[0], analysed)) note = W.t(chord.doubt.why); // one of the analysis's texts, in core/i18n-fr.js
      else {
        note = W.nodes(W.t("The chart keeps {chord}: the bars around it point to it. Heard alone, this bar sounds more like {top}."), {
          chord: node(analysed),
          top: node(alts[0]),
        });
      }
      const pop = $("pop");
      // Another chord to check in the same bar (the bar is one control): one press away, round and round.
      const chords = song.bars[u].chords;
      const later = [...chords.keys()].slice(k + 1).concat([...chords.keys()].slice(0, k));
      const j = later.find((i) => chords[i].doubt && !chords[i].fixed);
      const nextMark = j === undefined ? null : document.querySelector('.doubt[data-ref="' + u + "_" + j + '"]');
      clear(
        pop,
        h("h3", { id: "popTitle" }, W.t("Bar {n}: which one do you hear?", { n: u + 1 })),
        h("p", { "data-testid": "doubt-note" }, note),
        alts.map((alt, i) => {
          const tag = chord.fixed && same(alt, chord) ? W.t("yours") : same(alt, analysed) ? W.t("analysis") : null;
          const inUse = chord.fixed && same(alt, chord);
          const keep = !chord.fixed && same(alt, analysed); // the chart's chord, confirmed by ear
          return h(
            "div",
            { class: "alt" + (inUse ? " in-use" : ""), "data-testid": "alternative" },
            h("span", { class: "an" }, node(alt), tag ? h("span", { class: "tag" }, tag) : null),
            h("span", { class: "meter" }, alt.share === null ? null : h("i", { style: { width: alt.share + "%" } })),
            h("span", { class: "pc" }, alt.share === null ? "–" : W.t("{n}%", { n: alt.share })),
            h(
              "span",
              { class: "acts" },
              h("button", { type: "button", "aria-label": W.t("Hear {chord} in this bar", { chord: named(alt) }), "data-testid": "hear-alternative", onclick: () => app.audition(u, alt) }, "▶"),
              h(
                "button",
                {
                  type: "button", class: "pick", disabled: inUse ? "" : null, "data-testid": i === 0 ? "pick-first" : "pick", onclick: () => app.correct(u, k, alt),
                  "aria-label": keep ? W.t("Keep {chord}", { chord: named(alt) }) : W.t("Use {chord}", { chord: named(alt) }),
                },
                inUse ? W.t("In use") : keep ? W.t("Keep") : W.t("Use"),
              ),
            ),
          );
        }),
        chord.fixed
          ? h("p", { class: "pop-reset" }, h("button", {
              type: "button", class: "btn", "data-testid": "doubt-reset", onclick: () => app.uncorrect(chord.doubt.id),
              "aria-label": W.t("Back to the analysis: {chord}, to check by ear", { chord: named(analysed) }),
            }, W.t("Back to the analysis")))
          : null,
        h("p", null, W.t("▶ plays this bar of the recording with the candidate chord over it. Pick what matches your ear.")),
        nextMark ? h("p", null, h("button", { type: "button", class: "btn", "data-testid": "doubt-next", onclick: (e) => {
          e.stopPropagation(); // the button is gone with the pop drawn again: not a click outside it
          openDoubt(nextMark, opener, true);
        } }, W.t("Next chord to check in this bar"))) : null,
      );
      pop.hidden = false;
      pop.dataset.ref = u + "_" + k;
      opener = from || (button.matches("button") ? button : button.closest(".bar")) || button;
      button.scrollIntoView({ block: "nearest" }); // a chord half off screen: the pop sits by it, not at the top
      place(pop, button, true);
      const f = (toNext && pop.querySelector("[data-testid=doubt-next]")) || pop.querySelector(".pick:not([disabled])") || pop.querySelector("button");
      if (f) f.focus();
    }
    // A dialog keeps the keyboard: Tab from its last button comes back to its first, and Shift+Tab
    // the other way; Escape closes it (app.js).
    $("pop").addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      const list = [...$("pop").querySelectorAll("button:not([disabled])")];
      if (!list.length) return;
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

    return { toast, closeAll, openMenu, openDoubt };
  };
})();
