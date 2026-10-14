// Sampled previews: hear a chord shape, a bass riff, the groove, a candidate chord, the count-in.
// FluidR3_GM samples (MIT), loaded per instrument on first use; only the notes needed are decoded,
// from the original files, never re-encoded.
(function () {
  "use strict";
  const W = window.Woodshed;

  W.createSounds = function createSounds(onMessage) {
    let ctx = null;
    let master = null;
    const bus = {};
    const decoded = {};
    const loading = {};
    const keysOf = {};
    const scripts = {};

    function ensureContext() {
      if (ctx) return ctx;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) throw new Error("Audio is not available in this browser.");
      ctx = new AC();
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -18;
      comp.knee.value = 10;
      comp.ratio.value = 4;
      comp.attack.value = 0.004;
      comp.release.value = 0.16;
      master = ctx.createGain();
      master.gain.value = 0.9;
      master.connect(comp);
      comp.connect(ctx.destination);
      const verb = ctx.createConvolver();
      const verbIn = ctx.createGain();
      const verbOut = ctx.createGain();
      verb.buffer = impulse(1.7);
      verbIn.gain.value = 0.22;
      verbOut.gain.value = 0.7;
      verbIn.connect(verb);
      verb.connect(verbOut);
      verbOut.connect(master);
      for (const [name, level] of [["preview", 0.9], ["click", 0.7]]) {
        const g = ctx.createGain();
        g.gain.value = level;
        g.connect(master);
        if (name === "preview") g.connect(verbIn);
        bus[name] = g;
      }
      return ctx;
    }

    function impulse(seconds) {
      const sr = ctx.sampleRate;
      const len = Math.floor(sr * seconds);
      const buf = ctx.createBuffer(2, len, sr);
      for (let c = 0; c < 2; c++) {
        const d = buf.getChannelData(c);
        let lp = 0;
        for (let i = 0; i < len; i++) {
          lp = lp * 0.55 + (Math.random() * 2 - 1) * 0.45;
          d[i] = lp * Math.pow(1 - i / len, 3.2);
        }
      }
      return buf;
    }

    function loadScript(src) {
      if (!scripts[src]) {
        scripts[src] = new Promise((resolve, reject) => {
          const el = document.createElement("script");
          el.src = src;
          el.onload = () => resolve();
          el.onerror = () => {
            delete scripts[src];
            reject(new Error("Could not load " + src));
          };
          document.head.appendChild(el);
        });
      }
      return scripts[src];
    }

    function bytes(b64) {
      const bin = atob(b64);
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out.buffer;
    }

    const nearest = (keys, midi) => keys.reduce((best, k) => (best === null || Math.abs(k - midi) < Math.abs(best - midi) ? k : best), null);

    async function ensureNotes(name, midis) {
      ensureContext();
      if (!loading[name]) {
        loading[name] = loadScript("assets/samples/samples-" + name + ".js").then(() => {
          const src = window.WOODSHED_SAMPLES && window.WOODSHED_SAMPLES[name];
          if (!src) throw new Error("Samples missing for " + name);
          decoded[name] = {};
          return src;
        });
        loading[name].catch(() => delete loading[name]);
      }
      const src = await loading[name];
      const available = Object.keys(src).map(Number);
      const wanted = [...new Set(midis.map((m) => nearest(available, m)))].filter((k) => k !== null && !decoded[name][k]);
      await Promise.all(
        wanted.map((k) =>
          ctx.decodeAudioData(bytes(src[k])).then(
            (b) => (decoded[name][k] = b),
            () => null,
          ),
        ),
      );
      keysOf[name] = Object.keys(decoded[name]).map(Number).sort((a, b) => a - b);
      if (!keysOf[name].length) throw new Error("No playable samples for " + name);
    }

    function note(name, midi, t, dur, vel, out, release) {
      const keys = keysOf[name];
      if (!keys || !keys.length) return;
      const k = nearest(keys, midi);
      const src = ctx.createBufferSource();
      const g = ctx.createGain();
      const rel = release || 0.08;
      src.buffer = decoded[name][k];
      src.playbackRate.value = Math.pow(2, (midi - k) / 12);
      const v = vel * (0.92 + Math.random() * 0.16);
      g.gain.setValueAtTime(v, t);
      g.gain.setValueAtTime(v, t + dur);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur + rel);
      src.connect(g);
      g.connect(out || bus.preview);
      src.start(t);
      src.stop(t + dur + rel + 0.05);
      return src;
    }

    let countClicks = [];

    // Load what is needed, then schedule: fn(startTime) gets a time slightly in the future.
    async function play(names, needs, fn) {
      try {
        ensureContext();
        if (ctx.state === "suspended") await ctx.resume();
        const pending = names.filter((n) => !loading[n]);
        if (pending.length && onMessage) onMessage("Loading sounds: " + pending.join(", ") + "…");
        await Promise.all(names.map((n) => ensureNotes(n, needs[n] || [])));
        fn(ctx.currentTime + 0.05);
        return true;
      } catch (err) {
        if (onMessage) onMessage(err.message || String(err));
        return false;
      }
    }

    return {
      play,
      note,
      now: () => (ctx ? ctx.currentTime : 0),
      bus: (name) => bus[name],
      strum(name, midis, t, dur, vel, up, gap) {
        (up ? midis.slice().reverse() : midis).forEach((m, i) => note(name, m, t + i * (gap || 0.012), dur, vel * (up ? 0.85 : 1), bus.preview, 0.06));
      },
      // Clicks for a count-in: n beats, `beat` seconds apart, the first one louder. Resolves with
      // the seconds left until the bar is over, or null when the clicks could not play.
      async clicks(n, beat) {
        let left = null;
        const ok = await play(["drums"], { drums: [37] }, (t) => {
          countClicks = [];
          for (let i = 0; i < n; i++) countClicks.push(note("drums", 37, t + i * beat, 0.08, i === 0 ? 0.7 : 0.45, bus.click));
          left = t - ctx.currentTime + n * beat;
        });
        return ok ? left : null;
      },
      loaded: (name) => !!(keysOf[name] && keysOf[name].length),
      // A cancelled count-in stops at once, without its remaining clicks.
      stopClicks() {
        for (const src of countClicks) if (src) src.stop();
        countClicks = [];
      },
      // Metronome tick `delay` seconds from now (the clicks must already be loaded).
      tick(delay, accent) {
        if (!ctx || !keysOf.drums) return;
        note("drums", 37, ctx.currentTime + Math.max(0, delay), 0.08, accent ? 0.6 : 0.32, bus.click);
      },
    };
  };
})();
