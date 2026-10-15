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
      renderSet();
      if (shown) render(shown);
    });
    return saving;
  }
  function move(folder, by) {
    saveSet((next) => {
      const k = next.indexOf(folder);
      if (k < 0) return null;
      next.splice(k, 1);
      next.splice(Math.max(0, Math.min(next.length, k + by)), 0, folder);
      return next;
    });
  }
  function renderSet() {
    clear(
      $("setlist"),
      setlist.map((folder, k) =>
        h(
          "li",
          { "data-testid": "set-item" },
          h("a", { href: link(folder), translate: "no" }, titles[folder] || folder.replace(/\.woodshed$/, "")),
          h(
            "span",
            { class: "set-tools" },
            h("button", { type: "button", class: "btn", "aria-label": W.t("Earlier in the set"), disabled: k === 0 ? "" : null, onclick: () => move(folder, -1), "data-testid": "set-up" }, "↑"),
            h("button", { type: "button", class: "btn", "aria-label": W.t("Later in the set"), disabled: k === setlist.length - 1 ? "" : null, onclick: () => move(folder, 1), "data-testid": "set-down" }, "↓"),
            h("button", { type: "button", class: "btn", "aria-label": W.t("Out of the set"), onclick: () => saveSet((next) => next.filter((x) => x !== folder)), "data-testid": "set-remove" }, "✕"),
          ),
        ),
      ),
    );
    $("setEmpty").hidden = setlist.length > 0;
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
    for (const s of data.songs) titles[s.folder] = s.title;
    $("phones").textContent = data.addresses && data.addresses.length
      ? W.t("Bandmates on the same Wi-Fi: open {addresses} on their phones, and set them not to lock their screen while you play.", { addresses: data.addresses.join(" " + W.t("or") + " ") })
      : data.container
        ? W.t("Bandmates on the same Wi-Fi: open this computer's network address on their phones, with the port of compose.yaml (for example 192.168.1.20:8000). The port must be published to the network: compose.yaml says how.")
        : W.t("Phones of the band: start the library with  woodshed app --host 0.0.0.0 --allow-network  and they can follow.");
    const jobs = data.jobs;
    const byFolder = new Map(jobs.filter((j) => j.page).map((j) => [j.page, j]));
    const rows = data.songs.map((s) => row(s, byFolder.get(s.folder)));
    for (const j of jobs) if (!j.page || !data.songs.some((s) => s.folder === j.page)) rows.unshift(row(null, j));
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
