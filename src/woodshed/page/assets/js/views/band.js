// The band in the room, when the page is served by `woodshed app`: one device leads (it plays,
// seeks, loops, changes the tempo or the song), the others follow its position without sound.
// The set list gives the next song. Opened from disk, none of this shows.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear } = W;

  const HEARTBEAT_MS = 1000; // the leader repeats where it is while playing
  const STALE = 3.5; // seconds without a word from a playing leader: it is gone (tab closed, asleep)
  const JUMP = 0.4; // seconds: a position further than this from the expected one is a seek
  const OFFSETS = 10; // clock samples kept: the delivery delay only makes a sample smaller

  W.views = W.views || {};

  W.views.band = function band(app) {
    const { song, store } = app;
    const served = location.protocol === "http:" || location.protocol === "https:";
    if (!served) return { render() {} };

    // What the address asked for, then a clean address: a reload or Back must not lead again.
    const params = new URLSearchParams(location.search);
    const asked = params.get("follow") === "1" ? "follow" : params.get("lead") === "1" ? "lead" : "";
    const stage = params.get("stage") === "1";
    if (location.search) history.replaceState(null, "", location.pathname + location.hash);

    const folder = decodeURIComponent(location.pathname.split("/").slice(-2)[0] || "");
    let id = "";
    try {
      id = sessionStorage.getItem("woodshed:device") || "";
    } catch (err) {
      /* storage off: a new id per page */
    }
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
      const bytes = new Uint8Array(12);
      crypto.getRandomValues(bytes);
      id = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
      try {
        sessionStorage.setItem("woodshed:device", id);
      } catch (err) {
        /* see above */
      }
    }

    let token = null;
    let mode = "alone"; // alone, lead, follow
    let stream = null;
    let retry = 1000;
    let last = null; // the last live state heard
    const offsets = []; // server clock minus this device's clock, in seconds, last samples
    let setlist = [];
    const titles = {};
    let heartbeat = 0;
    let sent = null; // what the leader last said: {time, at, playing, rate}
    let handingOver = false; // the leader is taking the band to the next song: no release
    let leadChecked = false;

    const offset = () => (offsets.length ? Math.max(...offsets) : 0);
    const nowServer = () => Date.now() / 1000 + offset();

    async function api(path, body, again = true) {
      let res;
      try {
        res = await fetch(path, body === undefined ? { cache: "no-store" } : {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Woodshed-Token": token },
          body: JSON.stringify(body),
        });
      } catch (err) {
        return { ok: false, status: 0, data: { error: "the app did not answer" } };
      }
      const data = await res.json().catch(() => ({}));
      if (res.status === 403 && body !== undefined && again && (await fetchToken())) return api(path, body, false);
      return { ok: res.ok, status: res.status, data };
    }

    // The token changes when the app restarts: fetched again then, and the stream reopened.
    async function fetchToken() {
      const r = await api("/api/token");
      if (!r.ok || typeof r.data.token !== "string") return false;
      const changed = token !== null && token !== r.data.token;
      token = r.data.token;
      if (changed && stream) {
        stream.close();
        stream = null;
        listen();
      }
      return true;
    }

    function goTo(target, extra) {
      const q = new URLSearchParams(extra);
      if (store.get().stage) q.set("stage", "1");
      const query = q.toString();
      location.href = "../" + encodeURIComponent(target) + "/index.html" + (query ? "?" + query : "");
    }

    // Leading: say where the band is. "Playing" is the audio's: a count-in has not started it yet.
    function say(claim) {
      const s = store.get();
      const body = {
        id, song: folder, playing: !!app.transport.playing, time: Math.max(0, app.transport.time),
        rate: s.bpm / app.songBpm, loop: s.loopOn && s.loop ? s.loop : null,
      };
      if (claim) body.lead = true;
      sent = { time: body.time, at: Date.now() / 1000, playing: body.playing, rate: body.rate };
      return api("/api/live", body).then((r) => {
        if (r.status === 409) setMode("follow", "Another device leads the band now: you follow it.");
        return r;
      });
    }

    function startHeartbeat() {
      clearInterval(heartbeat);
      heartbeat = setInterval(() => mode === "lead" && app.transport.playing && say(false), HEARTBEAT_MS);
    }

    store.on((_s, changed) => {
      if (mode !== "lead") return;
      const big = ["playing", "bpm", "loop", "loopOn"].some((k) => changed.has(k));
      let moved = false;
      if (changed.has("time") && sent) {
        const expected = sent.playing ? sent.time + (Date.now() / 1000 - sent.at) * sent.rate : sent.time;
        moved = Math.abs(app.transport.time - expected) > JUMP || sent.playing !== app.transport.playing;
      }
      if (big || moved) say(false);
    });

    function release() {
      if (mode !== "lead" || handingOver || !token) return;
      // keepalive: the request outlives the page that closes.
      fetch("/api/live", {
        method: "POST", keepalive: true, body: JSON.stringify({ id, release: true }),
        headers: { "Content-Type": "application/json", "X-Woodshed-Token": token },
      }).catch(() => {});
    }
    window.addEventListener("pagehide", release);

    // Following: the leader's position, computed on this device's clock.
    let frame = 0;
    const stale = () => !!(last && last.leader && last.playing && nowServer() - last.at > STALE);
    function follow() {
      cancelAnimationFrame(frame);
      const tick = () => {
        if (mode !== "follow") return;
        if (last && last.leader && last.song === folder) {
          const gone = stale();
          const until = gone ? last.at + STALE : nowServer();
          const t = last.playing ? last.time + (until - last.at) * last.rate : last.time;
          const time = Math.max(0, Math.min(song.song.duration, t));
          store.set({ time, beat: song.beatAt(time), playing: last.playing && !gone });
          if (gone !== $("bandBanner").hasAttribute("data-stale")) renderBand();
        } else if (store.get().playing) store.set({ playing: false }); // no leader: the band stops
        frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    }

    function heard(state) {
      const sample = state.now - Date.now() / 1000;
      if (offsets.length && Math.abs(sample - offset()) > 2) offsets.length = 0; // this device's clock jumped
      offsets.push(sample);
      if (offsets.length > OFFSETS) offsets.shift();
      last = state;
      if (mode === "lead") {
        if (state.leader && state.leader !== id) setMode("follow", "Another device leads the band now: you follow it.");
        else if (!state.leader) {
          say(true); // the app restarted: lead again
          app.toast("The band had no leader: this device leads again.");
        }
        return;
      }
      if (asked === "lead" && mode === "alone" && !leadChecked) {
        leadChecked = true;
        if (state.leader === id) setMode("lead"); // the band followed this device to this song
      }
      if (mode !== "follow") return renderBand();
      if (state.leader && state.song && state.song !== folder) {
        goTo(state.song, { follow: "1" });
        return;
      }
      if (state.leader) {
        store.set({ loop: state.loop, loopOn: !!state.loop, bpm: Math.round(app.songBpm * state.rate) });
      }
      renderBand();
    }

    function listen() {
      if (stream || !token) return;
      stream = new EventSource("/api/live?t=" + encodeURIComponent(token));
      stream.onopen = () => (retry = 1000);
      stream.onmessage = (e) => {
        try {
          heard(JSON.parse(e.data));
        } catch (err) {
          /* a broken event is skipped */
        }
      };
      // EventSource retries a dropped stream by itself, but not after an error answer (the app
      // restarted with a new token, too many devices): then start over, a little later each time.
      stream.onerror = () => {
        if (stream && stream.readyState === EventSource.CLOSED) {
          stream = null;
          setTimeout(() => fetchToken().then(listen), retry);
          retry = Math.min(15000, retry * 2);
        }
      };
    }
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && token && (!stream || stream.readyState === EventSource.CLOSED)) {
        stream = null;
        fetchToken().then(listen);
      }
    });

    async function setMode(next, message) {
      if (next === mode) return;
      const before = mode;
      mode = next;
      cancelAnimationFrame(frame);
      clearInterval(heartbeat);
      if (before === "lead" && next === "alone") api("/api/live", { id, release: true });
      if (before === "follow") {
        // Back on its own: the device plays from where the band was, at the band's tempo.
        const s = store.get();
        app.transport.seek(s.time);
        app.setBpm(s.bpm);
        app.setLoop(s.loopOn ? s.loop : null, s.loopOn);
        store.set({ playing: false });
      }
      if (next === "lead") {
        const r = await say(true);
        if (!r.ok) {
          mode = "alone";
          app.toast("Could not lead the band: " + (r.data.error || "the app did not answer") + ".");
        } else startHeartbeat();
      }
      if (next === "follow") {
        if (app.transport.playing) app.transport.pause();
        follow();
      }
      listen();
      document.body.classList.toggle("following", mode === "follow");
      renderBand();
      if (message) app.toast(message);
    }

    // The next song of the set.
    function nextSong() {
      const k = setlist.indexOf(folder);
      return k >= 0 && k + 1 < setlist.length ? setlist[k + 1] : null;
    }
    app.nextSong = () => {
      const target = nextSong();
      if (!target) return false;
      if (mode === "follow") {
        app.toast("The leader chooses the next song.");
        return true;
      }
      if (mode === "lead") {
        // The followers go when they hear the new song; this page goes once the app has it.
        handingOver = true;
        api("/api/live", { id, song: target, playing: false, time: 0, rate: 1, loop: null }).then((r) => {
          if (!r.ok) handingOver = false; // not handed over: the page releases the lead as it goes
          goTo(target, r.ok ? { lead: "1" } : {});
        });
      } else goTo(target, {});
      return true;
    };

    const titleOf = (f) => titles[f] || f.replace(/\.woodshed$/, "");

    function renderBand() {
      const box = $("band");
      if (!box || !token) return;
      box.hidden = false;
      clear(
        box,
        h("span", { class: "label" }, "Band"),
        h(
          "div",
          { class: "seg-ctl", role: "group", "aria-label": "Band" },
          [["alone", "Alone"], ["lead", "Lead"], ["follow", "Follow"]].map(([m, text]) =>
            h("button", { type: "button", class: mode === m ? "on" : "", "data-testid": "band-" + m, "aria-pressed": String(mode === m), onclick: () => setMode(m) }, text),
          ),
        ),
      );
      const banner = $("bandBanner");
      if (mode === "follow") {
        const sec = app.sectionOf(Math.floor(store.get().beat / song.per));
        const gone = stale();
        banner.hidden = false;
        banner.toggleAttribute("data-stale", gone);
        const status = !last || !last.leader
          ? [h("b", null, "Waiting for a leader"), h("span", null, " · another device presses Lead")]
          : gone
            ? [h("b", null, "The leader is silent"), h("span", null, " · its page closed or its screen locked")]
            : [h("b", null, "Following the leader"), h("span", null, (last.playing ? " · playing" : " · stopped") + (sec ? " · " + sec.name : ""))];
        clear(banner, status, h("button", { type: "button", class: "linkbtn", onclick: () => setMode("alone") }, "Stop following"));
      } else banner.hidden = true;
      const next = nextSong();
      const link = $("nextSong");
      link.hidden = !next;
      if (next) clear(link, "Next: ", h("b", null, titleOf(next)), " →");
      $("stNextSong").textContent = next ? "Next song: " + titleOf(next) + " (N, or → at the end)" : "";
    }

    store.on((s, changed) => {
      if (mode === "follow" && changed.has("beat")) {
        const sec = app.sectionOf(Math.floor(s.beat / song.per));
        const shown = $("bandBanner").getAttribute("data-section");
        if (sec && sec.name !== shown) {
          $("bandBanner").setAttribute("data-section", sec.name);
          renderBand();
        }
      }
    });

    async function start() {
      if (!(await fetchToken())) return; // an old app, or none
      const [set, songs] = await Promise.all([api("/api/setlist"), api("/api/songs")]);
      if (set.ok && Array.isArray(set.data.songs)) setlist = set.data.songs;
      if (songs.ok && Array.isArray(songs.data.songs)) for (const x of songs.data.songs) titles[x.folder] = x.title;
      $("nextSong").addEventListener("click", (e) => {
        e.preventDefault();
        app.nextSong();
      });
      renderBand();
      if (stage) app.setStage(true, false);
      if (asked === "follow") setMode("follow");
      else listen(); // a "lead" asked by the address is checked against the band first (heard)
    }
    start();

    W.band = { mode: () => mode, id: () => id, state: () => last };
    return { render: renderBand };
  };
})();
