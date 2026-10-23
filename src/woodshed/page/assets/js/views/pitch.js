// The recording in the chart's key (spec 007, the singer's key). The library renders the page's tracks
// in another key (ffmpeg's Rubber Band filter, `woodshed app`); the page asks for the track it plays and
// the role's tracks, plays the originals meanwhile, and swaps each file in place when it is ready. Off,
// or with no library, the original files play, untouched.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, clear } = W;
  const CHOICE = "woodshed:pitch"; // "on" or "off": this device's own choice, whatever the role
  const POLL_MS = 2000;
  const SETTLE_MS = 1500; // the key stepper pressed three times asks for one key, not three

  W.views.pitch = function pitch(app) {
    const { song, store, transport } = app;
    const served = location.protocol === "http:" || location.protocol === "https:";
    const folder = decodeURIComponent(location.pathname.split("/").slice(-2)[0] || "");
    const originals = Object.fromEntries(song.tracks.map((t) => [t.id, t.file]));
    let lib = null; // the library's answer: {can, off, keys, failed, eta}
    let reason = served ? "asking" : "disk"; // why it cannot: disk, library (none or older), filter, off
    const asked = new Set(); // "up2|mix": asked by this page
    const broken = new Set(); // "up2|mix": a rendered file this browser could not play
    let poll = 0;
    let settle = 0;

    const keyOf = (n) => (n > 0 ? "up" + n : "down" + -n);
    const pitched = (id) => !!originals[id] && id !== "solo-drums"; // drums: nothing to transpose
    function choice() {
      try {
        return localStorage.getItem(CHOICE);
      } catch (err) {
        return null;
      }
    }
    // On by default for the voice (choosing a key is what a singer asks), and for every role in the
    // band's own key; a choice made on this device wins.
    function wanted(s) {
      if (!s.transpose) return false;
      const c = choice();
      if (c) return c === "on";
      return s.inst === "voice" || (s.bandKey !== null && s.bandKey === s.transpose);
    }
    const stateOf = (key, id) => (broken.has(key + "|" + id) || refused.has(key + "|" + id) ? "failed" : lib && lib.keys[key] ? lib.keys[key][id] : undefined);

    // What the page says about the recording's key: none, cannot, off, drums, preparing, on, failed.
    function status(s) {
      if (!s.transpose || reason === "asking") return { state: "none" }; // the library not heard yet: nothing said
      if (reason) return { state: "cannot", why: reason };
      if (!wanted(s)) return { state: "off" };
      if (!pitched(s.track)) return { state: "drums" };
      const key = keyOf(s.transpose);
      const st = stateOf(key, s.track);
      if (st === "ready" && transport.fileOf(s.track) === rendered(key, s.track)) return { state: "on" };
      if (st === "failed") {
        const why = refused.get(key + "|" + s.track) || (lib && lib.failed[key] && lib.failed[key][s.track]) || "the browser could not play it";
        return { state: "failed", why };
      }
      return { state: "preparing", eta: lib && lib.eta && typeof lib.eta[key] === "number" ? lib.eta[key] : null };
    }
    const rendered = (key, id) => {
      const v = lib && lib.versions && lib.versions[key] ? lib.versions[key][id] : null;
      return "audio/key/" + key + "/" + id + ".flac" + (v ? "?v=" + v : ""); // rendered again: a new URL
    };

    function publish() {
      const st = status(store.get());
      const before = store.get().pitchStatus;
      if (!before || JSON.stringify(before) !== JSON.stringify(st)) store.set({ pitchStatus: st });
      renderRow();
    }

    async function load() {
      if (!served) return publish();
      try {
        const r = await fetch("/api/pitch?page=" + encodeURIComponent(folder), { cache: "no-store" });
        if (!r.ok) throw new Error(String(r.status));
        lib = await r.json();
        reason = lib.off ? "off" : lib.can ? null : "filter";
        // A render the library no longer knows (a page rebuilt, the app restarted): asked again.
        for (const k of [...asked]) {
          const [key, id] = k.split("|");
          if (!stateOf(key, id)) asked.delete(k);
        }
      } catch (err) {
        lib = null;
        reason = "library"; // a page served elsewhere, or a library that does not render keys
      }
      swap();
      askNeeded();
    }

    const refused = new Map(); // "up2|mix" -> why the library said no (not a busy queue)
    async function ask(id, semitones, wait, force) {
      const k = keyOf(semitones) + "|" + id;
      try {
        const token = (await (await fetch("/api/token", { cache: "no-store" })).json()).token;
        const r = await fetch("/api/pitch", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Woodshed-Token": token },
          body: JSON.stringify({ page: folder, track: id, semitones, wait, force }),
        });
        if (r.status === 429) asked.delete(k); // the library is busy: asked again at the next poll
        if (r.ok || r.status === 429) {
          clearTimeout(poll);
          poll = setTimeout(load, POLL_MS); // the library's answer said where it is: follow it
        } else {
          const data = await r.json().catch(() => ({}));
          refused.set(k, data.error || "the library refused it");
          publish();
        }
      } catch (err) {
        asked.delete(k); // no answer: asked again at the next poll
      }
    }

    // Each track plays its rendered file when it is ready and wanted, else the original.
    function swap() {
      const s = store.get();
      const on = !reason && wanted(s);
      const key = s.transpose ? keyOf(s.transpose) : "";
      for (const id of Object.keys(originals)) {
        const file = on && pitched(id) && stateOf(key, id) === "ready" ? rendered(key, id) : originals[id];
        if (transport.fileOf(id) === file) continue;
        const wantedNow = () => store.get().transpose === s.transpose; // a key changed meanwhile: drop it
        transport.setFile(id, file, wantedNow).then((ok) => {
          if (ok === "refused") return waitForTap(); // iOS: the rendered file starts after the next tap
          if (!ok && file !== originals[id]) failed(id, file);
          publish();
        });
      }
      publish();
    }

    // The browser would not start the rendered file without a tap (iOS): asked once, swapped on the next tap.
    let tapAsked = false;
    function waitForTap() {
      publish();
      if (tapAsked) return;
      tapAsked = true;
      app.toast(W.t("Tap the page to hear the recording in the new key."));
      const again = () => {
        tapAsked = false;
        for (const type of ["touchend", "click", "keydown"]) document.removeEventListener(type, again, true);
        swap();
      };
      for (const type of ["touchend", "click", "keydown"]) document.addEventListener(type, again, true);
    }

    // The track playing first, then the role's tracks; asked again while they are on their way.
    function askNeeded() {
      clearTimeout(poll);
      const s = store.get();
      if (reason || !wanted(s)) return publish();
      const key = keyOf(s.transpose);
      const stem = app.stemOf(s.inst);
      const want = [s.track, "mix", "solo-" + stem, "minus-" + stem].filter((id, i, all) => pitched(id) && all.indexOf(id) === i);
      for (const id of want) {
        const k = key + "|" + id;
        const st = stateOf(key, id);
        // Not asked yet by this page: asked; a failure the library keeps is asked again after a Retry.
        if ((!st || (st === "failed" && !broken.has(k) && !refused.has(k))) && !asked.has(k)) {
          asked.add(k);
          ask(id, s.transpose, id === s.track);
        }
      }
      if (want.some((id) => !["ready", "failed"].includes(stateOf(key, id)))) poll = setTimeout(load, POLL_MS);
      publish();
    }

    // A rendered file this browser cannot play: the original again, and Retry.
    function failed(id, file) {
      const key = file.split("/")[2];
      broken.add(key + "|" + id);
      if (transport.fileOf(id) !== originals[id]) transport.setFile(id, originals[id]);
      publish();
    }
    app.pitchFailed = (id, file) => file && file.indexOf("audio/key/") === 0 && failed(id, file);

    app.setPitch = (on) => {
      try {
        localStorage.setItem(CHOICE, on ? "on" : "off");
      } catch (err) {
        /* this visit only */
      }
      swap();
      askNeeded();
    };
    app.retryPitch = () => {
      const s = store.get();
      const key = keyOf(s.transpose);
      for (const k of [...broken]) {
        if (!k.startsWith(key + "|")) continue;
        broken.delete(k);
        asked.add(k);
        ask(k.split("|")[1], s.transpose, true, true); // the file is there but this browser could not play it: again
      }
      for (const k of [...refused.keys(), ...asked]) if (k.startsWith(key + "|") && !broken.has(k)) (refused.delete(k), asked.delete(k));
      load(); // the library says again where each file is, then the missing ones are asked
    };
    // For the sentences that say the recording's key (the chart, the toasts): will it follow the chart?
    app.pitchFollows = () => !reason && wanted(store.get());

    store.on((_, changed) => {
      if (changed.has("transpose") || changed.has("bandKey")) {
        swap(); // at once: the old key's files are no longer the chart's
        clearTimeout(settle);
        settle = setTimeout(askNeeded, SETTLE_MS);
      } else if (changed.has("inst") || changed.has("track")) {
        swap();
        askNeeded();
      }
    });

    const counted = (n, one, many) => (n === 1 ? W.t(one) : W.t(many, { n }));
    function shift(n) {
      return n > 0 ? counted(n, "1 semitone up", "{n} semitones up") : counted(-n, "1 semitone down", "{n} semitones down");
    }

    // The row under Listen to (views/desk.js gives it its place): the switch and what it is doing.
    function renderRow() {
      const s = store.get();
      const st = s.pitchStatus || status(s);
      const mark = document.getElementById("keyMark");
      if (mark) {
        const on = st.state === "on";
        mark.hidden = !on;
        mark.textContent = on ? "♪ " + (s.transpose > 0 ? "+" : "−") + Math.abs(s.transpose) : "";
        if (on) mark.setAttribute("aria-label", W.t("The recording plays {shift}", { shift: shift(s.transpose) }));
        else mark.removeAttribute("aria-label");
      }
      const box = document.querySelector("#yourPart [data-part=pitch]");
      if (!box) return;
      if (st.state === "none") return clear(box);
      const keyName = W.prettyText(song.keyName(s.transpose));
      if (st.state === "cannot") {
        const why = {
          disk: W.t("The recording keeps its key. Open the page from the woodshed library to hear it in another key."),
          library: W.t("The recording keeps its key. Open the page from the woodshed library to hear it in another key."),
          filter: W.t("This library cannot change the key: install the full ffmpeg (with Rubber Band), then restart woodshed."),
          off: W.t("Changing the recording's key is off in this library."),
        }[st.why];
        return clear(box, h("p", { class: "part-note", "data-testid": "pitch-cannot" }, why));
      }
      const on = st.state !== "off";
      const line = {
        off: W.t("The recording keeps its key."),
        drums: W.t("Drums have no pitch: played as recorded."),
        preparing: st.eta ? W.t("Preparing the recording {shift}… about {n} s", { shift: shift(s.transpose), n: Math.max(1, st.eta) }).replace(/ s$/, "\u00a0s") : W.t("Preparing the recording {shift}…", { shift: shift(s.transpose) }),
        on: W.t("{shift}.", { shift: shift(s.transpose) }).replace(/^./, (c) => c.toUpperCase()),
        failed: W.t("The recording could not be changed to this key."),
      }[st.state];
      clear(
        box,
        h("button", { type: "button", class: "btn pitch-switch", "aria-pressed": String(on), "data-testid": "pitch-switch", onclick: () => app.setPitch(!on) },
          W.t("Play the recording {shift}", { shift: shift(s.transpose) }), " ", h("span", { class: "key-name" }, "(" + W.t("in {key}", { key: keyName }) + ")"),
          h("b", { class: "state", "aria-hidden": "true" }, on ? W.t("On") : W.t("Off"))),
        h("span", { class: "pitch-line", "aria-live": "polite", "data-testid": "pitch-line", title: st.state === "failed" ? st.why : null }, line),
        st.state === "failed" ? h("button", { type: "button", class: "btn", "data-testid": "pitch-retry", onclick: () => app.retryPitch() }, W.t("Retry")) : null,
      );
    }
    app.renderPitch = renderRow;

    load();
    return { render: renderRow };
  };
})();
