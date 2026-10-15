// The dock: play, waveform, loop, trainer, tempo, count-in and the tracks menu.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, clear, fmt } = W;

  W.views = W.views || {};

  W.views.dock = function dock(app) {
    const { song, store } = app;
    const duration = song.song.duration;
    const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
    const barStart = (i) => (i >= song.bars.length ? song.bars[song.bars.length - 1].end : song.bars[Math.max(0, i)].start);

    // The waveform, sections, loop and doubts are drawn once into a cached layer; each frame only
    // copies that layer and draws the playhead.
    let layer = null;
    let colours = null;

    function drawLayer(s, w, hgt, dpr) {
      colours = { accentSoft: css("--accent-soft"), accent: css("--accent"), wave: css("--wave"), warn: css("--warn"), muted: css("--muted"), font: css("--font-body") };
      layer = document.createElement("canvas");
      layer.width = Math.round(w * dpr);
      layer.height = Math.round(hgt * dpr);
      const g = layer.getContext("2d");
      g.scale(dpr, dpr);
      const X = (t) => (t / duration) * w;
      const sections = app.sections();
      g.fillStyle = colours.accentSoft;
      sections.forEach((sec, k) => {
        if (k % 2 === 0) g.fillRect(X(barStart(sec.start)), 0, X(barStart(sec.end)) - X(barStart(sec.start)), hgt);
      });
      if (s.loopOn && s.loop) {
        g.fillStyle = colours.accent;
        g.globalAlpha = 0.18;
        g.fillRect(X(barStart(s.loop[0])), 0, X(barStart(s.loop[1] + 1)) - X(barStart(s.loop[0])), hgt);
        g.globalAlpha = 1;
      }
      g.fillStyle = colours.wave;
      const energy = song.song.energy;
      for (let i = 0; i < energy.length; i++) {
        const t0 = energy[i][0];
        const t1 = i + 1 < energy.length ? energy[i + 1][0] : t0 + 0.6;
        const amp = Math.pow(10, energy[i][1] / 20);
        const a = Math.max(0.02, Math.min(1, amp)) * (hgt / 2 - 3);
        g.fillRect(X(t0), hgt / 2 - a, Math.max(1, X(t1) - X(t0) - 0.6), a * 2);
      }
      g.fillStyle = colours.warn;
      song.bars.forEach((b, i) => {
        if (b.chords.some((c) => c.doubt && c.doubt.kind === "chord" && !c.fixed)) g.fillRect(X(barStart(i)), hgt - 4, X(barStart(i + 1)) - X(barStart(i)), 4);
      });
      g.fillStyle = colours.muted;
      g.font = "11px " + colours.font;
      // Each section's name where it fits, else its first letters (V1 for Verse 1), else nothing.
      sections.forEach((sec) => {
        const x = X(barStart(sec.start));
        const room = X(barStart(sec.end)) - x - 5;
        const SHORT = { intro: "In", verse: "V", prechorus: "Pre", chorus: "C", bridge: "Br", instrumental: "Inst", outro: "Out" };
        const number = (sec.name.match(/ (\d+)$/) || ["", ""])[1];
        const short = SHORT[sec.role] ? SHORT[sec.role] + number : sec.letter;
        const text = [sec.name, short].find((t) => g.measureText(t).width <= room);
        if (text) g.fillText(text, x + 3, 12);
      });
    }

    function drawWave(s, rebuild) {
      const cv = $("wave");
      const dpr = window.devicePixelRatio || 1;
      const w = cv.clientWidth;
      const hgt = cv.clientHeight;
      if (!w || !hgt) return;
      // Canvas sizes are whole pixels: compare rounded, or fractional zooms (125 %) rebuild every frame.
      const pw = Math.round(w * dpr);
      const ph = Math.round(hgt * dpr);
      if (rebuild || !layer || layer.width !== pw || layer.height !== ph) {
        cv.width = pw;
        cv.height = ph;
        drawLayer(s, w, hgt, dpr);
      }
      const g = cv.getContext("2d");
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, cv.width, cv.height);
      g.drawImage(layer, 0, 0);
      g.fillStyle = colours.accent;
      g.fillRect((s.time / duration) * w * dpr - dpr, 0, 2 * dpr, hgt * dpr);
    }

    let shownTenth = -1;
    function renderPosition(s) {
      const tenth = Math.floor(s.time * 10);
      if (tenth !== shownTenth) clear($("posInfo"), h("b", null, fmt(s.time, true)), " / " + fmt(duration));
      shownTenth = tenth;
      const looped = s.loop && app.sections().find((sec) => sec.start === s.loop[0] && sec.end === s.loop[1] + 1);
      const what = !s.loop ? "" : looped ? looped.name : "bars " + (s.loop[0] + 1) + "–" + (s.loop[1] + 1);
      $("loopInfo").textContent = s.loopOn && s.loop ? "Looping " + what + (s.trainer ? " · trainer on" : "") : "No loop";
      $("loopBtn").classList.toggle("on", !!s.loopOn);
      $("trainBtn").classList.toggle("on", !!s.trainer);
      $("countBtn").classList.toggle("on", !!s.countIn);
      $("clickBtn").classList.toggle("on", !!s.click);
      const play = $("playBtn");
      play.textContent = s.playing ? "❚❚" : "▶";
      play.setAttribute("aria-label", s.playing ? "Pause" : "Play");
    }

    function renderTempo(s) {
      const slider = $("bpm");
      slider.min = String(app.minBpm);
      slider.max = String(app.maxBpm);
      slider.value = String(s.bpm);
      $("bpmVal").textContent = s.bpm + " BPM";
      $("bpmReset").classList.toggle("on", s.bpm === app.songBpm);
    }

    function renderTracks(s) {
      const existing = $("mixer").querySelectorAll("[data-track]");
      if (existing.length === song.tracks.length) {
        // Update in place: rebuilding would drop the keyboard focus inside the menu.
        existing.forEach((b) => {
          const on = b.getAttribute("data-track") === s.track;
          b.classList.toggle("cur", on);
          b.setAttribute("aria-pressed", String(on));
        });
        $("soundCtl").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.getAttribute("data-testid") === "sound-" + s.chordSound));
        return;
      }
      const rows = song.tracks.map((t) =>
        h(
          "button",
          { type: "button", class: "item" + (s.track === t.id ? " cur" : ""), "data-track": t.id, "data-testid": "track-" + t.id, "aria-pressed": String(s.track === t.id), onclick: () => app.setTrack(t.id) },
          h("span", null, t.label),
        ),
      );
      clear($("mixer"), rows);
      clear(
        $("soundCtl"),
        [["guitar", "Guitar"], ["rhodes", "Rhodes"], ["piano", "Piano"]].map(([id, label]) =>
          h("button", { type: "button", class: s.chordSound === id ? "on" : "", "data-testid": "sound-" + id, onclick: () => store.set({ chordSound: id }) }, label),
        ),
      );
      $("mixNote").textContent =
        song.tracks.length > 1
          ? "Tracks isolated on this computer. One plays at a time, so they never drift apart."
          : "Only the full mix: this page was made without stems.";
    }

    store.on((s, changed) => {
      const layerChanged = changed.has("loop") || changed.has("loopOn") || changed.has("corrections");
      if (layerChanged || changed.has("time")) drawWave(s, layerChanged);
      renderPosition(s);
      if (changed.has("bpm")) renderTempo(s);
      if (changed.has("track") || changed.has("chordSound")) renderTracks(s);
    });
    window.addEventListener("resize", () => drawWave(store.get(), true));
    window.addEventListener("woodshed:theme", () => drawWave(store.get(), true)); // the colours change
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      if (mq.addEventListener) mq.addEventListener("change", () => drawWave(store.get(), true));
    }

    return {
      render(s) {
        drawWave(s, true);
        renderPosition(s);
        renderTempo(s);
        renderTracks(s);
      },
      timeAt(clientX) {
        const r = $("wave").getBoundingClientRect();
        return ((clientX - r.left) / r.width) * duration;
      },
    };
  };
})();
