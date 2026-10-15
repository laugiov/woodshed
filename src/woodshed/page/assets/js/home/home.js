// The library home page (woodshed app): the songs ready to play, uploads and their progress.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, chordNode, fmt } = W;
  const token = document.querySelector('meta[name="woodshed-token"]').content;
  const STATUS = { queued: "Waiting", analysing: "Analysing", separating: "Separating the instruments", done: "Ready", failed: "Failed" };
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
        if (r.status === 403) toast("The library was restarted: reload this page.");
        else if (!r.ok) toast("The set list was not saved: " + answer.error);
        else setlist = answer.songs;
      } catch (err) {
        toast("The set list was not saved.");
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
          h("a", { href: link(folder) }, titles[folder] || folder.replace(/\.woodshed$/, "")),
          h(
            "span",
            { class: "set-tools" },
            h("button", { type: "button", class: "btn", "aria-label": "Earlier in the set", disabled: k === 0 ? "" : null, onclick: () => move(folder, -1), "data-testid": "set-up" }, "↑"),
            h("button", { type: "button", class: "btn", "aria-label": "Later in the set", disabled: k === setlist.length - 1 ? "" : null, onclick: () => move(folder, 1), "data-testid": "set-down" }, "↓"),
            h("button", { type: "button", class: "btn", "aria-label": "Out of the set", onclick: () => saveSet((next) => next.filter((x) => x !== folder)), "data-testid": "set-remove" }, "✕"),
          ),
        ),
      ),
    );
    $("setEmpty").hidden = setlist.length > 0;
  }

  function row(song, job) {
    let status;
    if (job && job.status !== "done") {
      status = job.status === "failed"
        ? h("span", { class: "warn" }, "Failed: " + job.message)
        : h("span", null, STATUS[job.status] + (job.status === "separating" ? " " + job.percent + " %" : job.step ? " (" + job.step + ")" : ""));
    } else status = song && song.complete ? h("span", { class: "okfact" }, song.stems ? "Ready, with parts" : "Ready") : h("span", null, "Mix only");
    const title = song ? h("a", { href: link(song.folder), "data-testid": "song-link" }, song.title) : h("span", null, job.name);
    return h(
      "tr",
      { "data-testid": "song-row" },
      h("td", null, title),
      h("td", null, song ? chordNode(song.key) : ""),
      h("td", { class: "num" }, song ? String(song.bpm) : ""),
      h("td", { class: "wide" }, song ? song.meter : ""),
      h("td", { class: "num wide" }, song ? fmt(song.duration) : ""),
      h("td", { class: "wide" }, song ? (song.doubts ? h("span", { class: "warn" }, String(song.doubts)) : "none") : ""),
      h("td", { "data-testid": "song-status" }, status),
      h(
        "td",
        null,
        song
          ? setlist.includes(song.folder)
            ? h("span", { class: "muted" }, "In the set")
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
    shown = data;
    render(data);
  }

  function render(data) {
    // A phone of the band can lead and follow, not add songs: the computer running the app does.
    const upload = data.can_upload !== false;
    $("drop").hidden = !upload;
    $("addBtn").hidden = !upload;
    for (const s of data.songs) titles[s.folder] = s.title;
    $("phones").textContent = data.addresses && data.addresses.length
      ? "Bandmates on the same Wi-Fi: open " + data.addresses.join(" or ") + " on their phones, and set them not to lock their screen while you play."
      : "Phones of the band: start the library with  woodshed app --host 0.0.0.0 --allow-network  and they can follow.";
    const jobs = data.jobs;
    const byFolder = new Map(jobs.filter((j) => j.page).map((j) => [j.page, j]));
    const rows = data.songs.map((s) => row(s, byFolder.get(s.folder)));
    for (const j of jobs) if (!j.page || !data.songs.some((s) => s.folder === j.page)) rows.unshift(row(null, j));
    clear($("rows"), rows);
    $("empty").hidden = rows.length > 0;
    const ready = data.songs.length;
    $("summary").textContent = ready + " song" + (ready === 1 ? "" : "s") + (jobs.some((j) => !["done", "failed"].includes(j.status)) ? ", working…" : "");
    busy = jobs.some((j) => !["done", "failed"].includes(j.status));
  }

  async function upload(files) {
    const params = new URLSearchParams();
    params.set("beats_per_bar", $("beats").value);
    if ($("bpm").value) params.set("bpm", $("bpm").value);
    if ($("sevenths").checked) params.set("sevenths", "1");
    for (const file of files) {
      params.set("name", file.name);
      toast("Sending " + file.name + "…");
      try {
        const r = await fetch("/api/songs?" + params.toString(), { method: "POST", headers: { "X-Woodshed-Token": token }, body: file });
        const answer = await r.json();
        if (r.status === 403 && answer.error === "missing or wrong token") toast("The library was restarted: reload this page, then add the file again.");
        else if (r.status === 403) toast(answer.error);
        else if (!r.ok) toast(file.name + ": " + answer.error);
      } catch (err) {
        toast(file.name + ": the upload failed");
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
      refresh();
    })
    .catch(() => {});
  refresh();
  setInterval(() => (busy || document.visibilityState === "visible") && refresh(), 1500);
  W.ready = true;
})();
