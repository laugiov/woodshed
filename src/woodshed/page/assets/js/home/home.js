// The library home page (woodshed app): the songs ready to play, uploads and their progress.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, chordNode, fmt } = W;
  const token = document.querySelector('meta[name="woodshed-token"]').content;
  // Said through W.t: every value is in core/i18n-fr.js, as are the analysis steps (analysis.analyze:
  // decode, stems, beats, chords, structure, parts, done).
  const STATUS = { queued: "Waiting", analysing: "Analysing", separating: "Separating the instruments", placing: "Placing the words", done: "Ready", failed: "Failed" };
  let toastTimer = 0;

  function toast(message) {
    const t = $("toast");
    t.textContent = message;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 4000);
  }

  // "./" and a fully encoded folder: a name with # or ? (or "javascript:") stays a relative path.
  const link = (folder) => "./" + encodeURIComponent(folder) + "/index.html";

  // The set list: the order the band plays in, saved in the library.
  let setlist = [];
  let titles = {};
  let info = {}; // page folder -> the library's facts on it: key, BPM, length, the band's choices
  let editing = null; // the song whose note is being written: the set list waits to be drawn again
  let shown = null; // the last /api/songs answer, to redraw the rows at once
  // One save at a time, each made from the list as the previous save left it: two quick clicks
  // never start from the same list.
  let saving = Promise.resolve();
  function saveSet(change) {
    saving = saving.then(async () => {
      const next = change(setlist.slice());
      if (!next) return;
      try {
        const r = await fetch("/api/setlist", { method: "POST", headers: { "X-Woodshed-Token": token, "Content-Type": "application/json" }, body: JSON.stringify({ songs: next }) });
        const answer = await r.json();
        if (r.status === 403) toast(W.t("The library was restarted: reload this page."));
        else if (!r.ok) toast(W.t("The set list was not saved: {why}", { why: answer.error }));
        else setlist = answer.songs;
      } catch (err) {
        toast(W.t("The set list was not saved."));
      }
      renderSet({ again: true });
      if (shown) render(shown);
    });
    return saving;
  }
  // To a place in the set: one step with the arrows, or straight to a position.
  function moveTo(folder, place) {
    saveSet((next) => {
      const k = next.indexOf(folder);
      if (k < 0 || place === k) return null;
      next.splice(k, 1);
      next.splice(Math.max(0, Math.min(next.length, place)), 0, folder);
      return next;
    }).then(() => {
      const moved = document.querySelector('[data-set-song="' + CSS.escape(folder) + '"] [data-testid="set-place"]');
      if (moved) moved.focus(); // the keyboard goes with the song
    });
  }
  // A set of 40 songs is over an hour: hours and minutes.
  const setLength = (t) => {
    const minutes = Math.round(t / 60);
    return t >= 3600 ? W.t("{h} h {m} min", { h: Math.floor(minutes / 60), m: minutes % 60 }) : fmt(t);
  };
  // The leader's note on a song ("capo 2, starts on the chorus"): kept by the library with the song,
  // shown on its page on every device.
  async function saveNote(folder, note) {
    try {
      const r = await fetch("/api/band", { method: "POST", headers: { "X-Woodshed-Token": token, "Content-Type": "application/json" }, body: JSON.stringify({ page: folder, note }) });
      const answer = await r.json();
      if (r.status === 403) toast(W.t("The library was restarted: reload this page."));
      else if (!r.ok) toast(W.t("The note was not saved: {why}", { why: W.t(answer.error) }));
      else info[folder] = { ...(info[folder] || {}), band: answer.band };
    } catch (err) {
      toast(W.t("The note was not saved."));
    }
  }
  function noteEditor(folder, note) {
    const input = h("input", { type: "text", class: "set-note-input", maxlength: "300", value: note, "aria-label": W.t("Note for {song}", { song: titles[folder] || folder }), "data-testid": "set-note-input" });
    let done = false;
    const finish = async (keep) => {
      if (done) return;
      done = true;
      if (keep && input.value.trim() !== note) await saveNote(folder, input.value);
      // Drawn after the click that ended the editing: the button under the pointer gets that click.
      setTimeout(() => {
        if (editing !== folder) return; // another song's note was opened meanwhile: left as it is
        editing = null;
        renderSet({ again: true, editor: true });
        const again = document.querySelector('[data-set-song="' + CSS.escape(folder) + '"] [data-testid="set-note"]');
        if (again) again.focus();
      }, 0);
    };
    input.addEventListener("keydown", (e) => {
      if (e.isComposing) return; // Enter picks a word in an input method, it does not save
      if (e.key === "Enter") finish(true);
      else if (e.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
    return input;
  }
  // Drawn again only when what it shows changes: the 1.5 s poll would close an open menu under the
  // pointer and take the keyboard's place away.
  let setShown = "";
  // `again`: drawn even if nothing changed (a save refused leaves a menu to put back); `editor`: drawn
  // although a note is being written (opening or closing it).
  function renderSet({ again = false, editor = false } = {}) {
    if (editing && !editor) return; // drawn again when the note is written: the text stays as typed
    const shows = JSON.stringify([setlist, setlist.map((f) => [titles[f], info[f] && [info[f].key, info[f].bpm, info[f].duration, info[f].band]]), editing, W.lang()]);
    if (shows === setShown && !again) return;
    setShown = shows;
    const known = setlist.filter((f) => info[f]);
    const total = known.reduce((n, f) => n + (info[f].duration || 0), 0);
    $("setSummary").textContent = setlist.length
      ? (setlist.length === 1 ? W.t("1 song") : W.t("{n} songs", { n: setlist.length })) + " · " + setLength(total)
      : "";
    $("printSet").hidden = setlist.length === 0;
    clear(
      $("setlist"),
      setlist.map((folder, k) => {
        const s = info[folder] || {};
        const band = s.band || {};
        const facts = [];
        if (s.key) facts.push(h("span", { class: band.key ? "band-key" : "" }, chordNode(band.key || s.key), band.key ? " " + W.t("(the band's key)") : ""));
        if (s.bpm) facts.push(h("span", null, s.bpm + " BPM"));
        if (s.duration) facts.push(h("span", null, fmt(s.duration)));
        const noteEl = editing === folder
          ? noteEditor(folder, band.note || "")
          : h("button", { type: "button", class: "set-note" + (band.note ? "" : " empty"), "data-testid": "set-note", onclick: () => {
              editing = folder;
              renderSet({ again: true, editor: true });
            } }, band.note ? h("span", { translate: "no" }, band.note) : W.t("+ Note"));
        return h(
          "li",
          { "data-testid": "set-item", "data-set-song": folder },
          h("span", { class: "set-n" }, String(k + 1)),
          h("div", { class: "set-song" },
            h("a", { href: link(folder), translate: "no" }, titles[folder] || folder.replace(/\.woodshed$/, "")),
            h("span", { class: "set-facts" }, facts),
            noteEl),
          h(
            "span",
            { class: "set-tools" },
            h("select", { class: "set-place", "aria-label": W.t("Place in the set"), "data-testid": "set-place", onchange: (e) => moveTo(folder, Number(e.target.value)) },
              setlist.map((x, j) => h("option", { value: String(j), selected: j === k ? "" : null }, String(j + 1)))),
            h("button", { type: "button", class: "btn", "aria-label": W.t("Earlier in the set"), disabled: k === 0 ? "" : null, onclick: () => moveTo(folder, k - 1), "data-testid": "set-up" }, "↑"),
            h("button", { type: "button", class: "btn", "aria-label": W.t("Later in the set"), disabled: k === setlist.length - 1 ? "" : null, onclick: () => moveTo(folder, k + 1), "data-testid": "set-down" }, "↓"),
            h("button", { type: "button", class: "btn", "aria-label": W.t("Out of the set"), onclick: () => saveSet((next) => next.filter((x) => x !== folder)), "data-testid": "set-remove" }, "✕"),
          ),
        );
      }),
    );
    $("setEmpty").hidden = setlist.length > 0;
    const input = document.querySelector('[data-testid="set-note-input"]');
    if (input) input.focus();
  }


  function row(song, job) {
    let status;
    if (job && job.status !== "done") {
      // The reason of a failure is the library's own, in English.
      status = job.status === "failed"
        ? h("span", { class: "warn" }, job.kind === "words" ? W.t("Words not placed: {why}", { why: job.message }) : W.t("Failed: {why}", { why: job.message }))
        : h("span", null, W.t(STATUS[job.status]) + (job.status === "separating" || job.status === "placing" ? " " + job.percent + " %" : job.step ? " (" + W.t(job.step) + ")" : ""));
    } else status = song && song.complete ? h("span", { class: "okfact" }, song.stems ? W.t("Ready, with parts") : W.t("Ready")) : h("span", null, W.t("Mix only"));
    // The words go on the singer's track: offered once the song has its parts.
    const addWords = song && song.complete && song.stems && !song.words && !(job && !["done", "failed"].includes(job.status))
      ? [" · ", h("a", { href: link(song.folder) + "#words", "data-testid": "add-words" }, W.t("add the words"))]
      : null;
    const title = song ? h("a", { href: link(song.folder), "data-testid": "song-link", translate: "no" }, song.title) : h("span", { translate: "no" }, job.name);
    return h(
      "tr",
      { "data-testid": "song-row" },
      h("td", null, title),
      h("td", null, song ? chordNode(song.key) : ""),
      h("td", { class: "num" }, song ? String(song.bpm) : ""),
      h("td", { class: "wide", translate: "no" }, song ? song.meter : ""),
      h("td", { class: "num wide" }, song ? fmt(song.duration) : ""),
      h("td", { class: "wide" }, song ? (song.doubts ? h("span", { class: "warn" }, String(song.doubts)) : W.t("none")) : ""),
      h("td", { "data-testid": "song-status" }, status, addWords),
      h(
        "td",
        null,
        song
          ? setlist.includes(song.folder)
            ? h("span", { class: "muted" }, W.t("In the set"))
            : h("button", { type: "button", class: "btn", onclick: () => saveSet((next) => (next.includes(song.folder) ? null : [...next, song.folder])), "data-testid": "set-add" }, "+ Set")
          : "",
      ),
    );
  }

  // The band's phones: a switch lets them in on this computer's network address, with a code to scan.
  const ROLES = "On a song page, Lead plays for the whole band, Follow plays along with the device that leads, Alone plays on its own.";
  function qrCode(text) {
    const qr = window.qrcode && window.qrcode(0, "M");
    if (!qr) return null;
    qr.addData(text);
    qr.make();
    const n = qr.getModuleCount();
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += "M" + (c + 4) + " " + (r + 4) + "h1v1h-1z";
    // Dark on light in both themes: a camera reads it so.
    return W.s("svg", { viewBox: "0 0 " + (n + 8) + " " + (n + 8), class: "qr", role: "img", "aria-label": W.t("Code to scan: {address}", { address: text }), "data-testid": "network-qr" },
      W.s("rect", { width: n + 8, height: n + 8, fill: "#fff" }), W.s("path", { d, fill: "#000" }));
  }
  let switching = false;
  async function setNet(on) {
    if (switching) return;
    switching = true;
    try {
      const r = await fetch("/api/network", { method: "POST", headers: { "X-Woodshed-Token": token, "Content-Type": "application/json" }, body: JSON.stringify({ on }) });
      const answer = await r.json();
      if (r.status === 403 && answer.error === "missing or wrong token") toast(W.t("The library was restarted: reload this page."));
      else if (!r.ok) toast(W.t("The phones were not let in: {why}", { why: W.t(answer.error) }));
    } catch (err) {
      toast(W.t("The app did not answer."));
    }
    switching = false;
    await refresh();
    const again = document.querySelector('[data-testid="network-switch"]');
    if (again) again.focus(); // the button was drawn again: the keyboard stays on it
  }
  let netShown = "";
  function renderNet(data) {
    const shows = JSON.stringify([data.container, data.network, data.addresses, W.lang()]);
    if (shows === netShown) return;
    netShown = shows;
    const net = data.network || { on: false, fixed: false, can_switch: false };
    const addresses = data.addresses || [];
    const out = [];
    if (data.container) {
      out.push(h("p", { class: "hint" }, W.t("Bandmates on the same Wi-Fi: open this computer's network address on their phones, with the port of compose.yaml (for example 192.168.1.20:8000). The port must be published to the network: compose.yaml says how.")));
    } else if (!net.can_switch) {
      out.push(h("p", { class: "hint" }, W.t("This device joined the band: open a song and press Follow.")));
    } else {
      if (!net.fixed) {
        out.push(h("button", { type: "button", class: "btn net-switch" + (net.on ? " on" : ""), role: "switch", "aria-checked": String(!!net.on), onclick: () => setNet(!net.on), "data-testid": "network-switch" },
          net.on ? W.t("Phones let in: switch off") : W.t("Let the band's phones join")));
      }
      if (net.on && addresses.length) {
        const code = qrCode(addresses[0]);
        out.push(h("div", { class: "net-on" }, code,
          h("div", null,
            h("p", null, W.t("On each phone, on the same Wi-Fi: scan the code with the camera, or type")),
            h("p", { class: "net-addr", translate: "no", "data-testid": "network-address" }, addresses.join("  ·  ")),
            h("p", { class: "hint" }, W.t(ROLES)),
            h("p", { class: "hint" }, W.t("The phones can play, lead and follow, not add songs. Set them not to lock their screen while you play.")))));
      } else if (net.on) {
        out.push(h("p", { class: "hint" }, W.t("Let in, but this computer has no network address: is it on the band's Wi-Fi?")));
      } else {
        out.push(h("p", { class: "hint" }, W.t("Phones on this Wi-Fi then open the library, lead and follow. The first time, your computer may ask whether woodshed (or Python) may accept incoming connections: allow it on private networks.")));
      }
    }
    clear($("net"), out);
  }

  let busy = false;
  async function refresh() {
    let data;
    try {
      const r = await fetch("/api/songs", { cache: "no-store" });
      data = await r.json();
    } catch (err) {
      return;
    }
    const same = shown && JSON.stringify(shown) === JSON.stringify(data);
    shown = data;
    if (!same) render(data); // redrawn only when something changed: a link under the pointer or the focus stays
  }

  function render(data) {
    // A phone of the band can lead and follow, not add songs: the computer running the app does.
    const upload = data.can_upload !== false;
    $("drop").hidden = !upload;
    $("addBtn").hidden = !upload;
    info = {};
    for (const s of data.songs) {
      titles[s.folder] = s.title;
      info[s.folder] = s;
    }
    renderSet();
    renderNet(data);
    const jobs = data.jobs;
    const byFolder = new Map(jobs.filter((j) => j.page).map((j) => [j.page, j]));
    const wanted = fold($("find").value);
    const rows = data.songs.filter((s) => !wanted || fold(s.title).includes(wanted)).map((s) => row(s, byFolder.get(s.folder)));
    for (const j of jobs) if (!j.page || !data.songs.some((s) => s.folder === j.page)) rows.unshift(row(null, j));
    if (wanted && !rows.length) rows.push(h("tr", null, h("td", { colspan: "8", class: "muted", "data-testid": "no-match" }, W.t("No song matches this search."))));
    clear($("rows"), rows);
    $("empty").hidden = rows.length > 0;
    const ready = data.songs.length;
    const songs = ready === 1 ? W.t("1 song") : ready === 0 ? W.t("0 songs") : W.t("{n} songs", { n: ready });
    $("summary").textContent = jobs.some((j) => !["done", "failed"].includes(j.status)) ? W.t("{songs}, working…", { songs }) : songs;
    busy = jobs.some((j) => !["done", "failed"].includes(j.status));
  }

  async function upload(files) {
    const params = new URLSearchParams();
    params.set("beats_per_bar", $("beats").value);
    if ($("bpm").value) params.set("bpm", $("bpm").value);
    if ($("sevenths").checked) params.set("sevenths", "1");
    for (const file of files) {
      params.set("name", file.name);
      toast(W.t("Sending {file}…", { file: file.name }));
      try {
        const r = await fetch("/api/songs?" + params.toString(), { method: "POST", headers: { "X-Woodshed-Token": token }, body: file });
        const answer = await r.json();
        if (r.status === 403 && answer.error === "missing or wrong token") toast(W.t("The library was restarted: reload this page, then add the file again."));
        else if (r.status === 403) toast(W.t(answer.error)); // the app's fixed reasons are in core/i18n-fr.js
        else if (!r.ok) toast(W.t("{file}: {why}", { file: file.name, why: W.t(answer.error) }));
      } catch (err) {
        toast(W.t("{file}: the upload failed", { file: file.name }));
      }
      refresh();
    }
  }

  // "beyonce" finds "Beyoncé": accents and case aside.
  const fold = (text) => String(text).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  $("find").addEventListener("input", () => shown && render(shown));
  $("printSet").addEventListener("click", () => window.print());
  $("addBtn").addEventListener("click", () => $("files").click());
  $("files").addEventListener("change", (e) => {
    upload([...e.target.files]);
    e.target.value = "";
  });
  const drop = $("drop");
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    upload([...e.dataTransfer.files]);
  });

  fetch("/api/setlist", { cache: "no-store" })
    .then((r) => r.json())
    .then((d) => {
      setlist = Array.isArray(d.songs) ? d.songs : [];
      renderSet();
      if (shown) render(shown); // the rows drawn before the set list came say "In the set" now
    })
    .catch(() => {});
  refresh();
  setInterval(() => (busy || document.visibilityState === "visible") && refresh(), 1500);
  W.onLang.push(() => {
    $("toast").hidden = true; // said in the other language
    document.title = W.t("Library · woodshed");
    if (shown) render(shown);
    renderSet();
  });
  document.title = W.t("Library · woodshed");
  W.ready = true;
})();
