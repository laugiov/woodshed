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
        if (r.status === 403) toast("The library was restarted: reload this page, then add the file again.");
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

  refresh();
  setInterval(() => (busy || document.visibilityState === "visible") && refresh(), 1500);
  W.ready = true;
})();
