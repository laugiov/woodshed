// Playback of the real recording. One <audio> element per pre-mixed track, one playing at a time,
// so instruments never drift apart. Speed changes keep the pitch (the browser's own stretching).
(function () {
  "use strict";
  const W = window.Woodshed;
  const EDGE = 0.05; // a loop never reaches the very end of the file, where "ended" would stop it

  W.createTransport = function createTransport(tracks, { onTime, onEnded, onError, onLoop }) {
    const els = {}; // by track id and file: a track can be played from another file (the singer's key)
    const files = Object.fromEntries(tracks.map((t) => [t.id, t.file])); // the file each track plays from
    let current = tracks[0].id;
    let rate = 1;
    let loop = null; // [start, end] in seconds
    let raf = 0;
    let timer = 0;
    let switching = Promise.resolve();

    function element(id, file = files[id]) {
      const key = id + "|" + file;
      if (!els[key]) {
        const t = tracks.find((x) => x.id === id);
        if (!t) throw new Error(W.t("No track {id}", { id }));
        const el = document.createElement("audio");
        el.preload = id === current ? "auto" : "none";
        el.src = file;
        el.setAttribute("data-track", id);
        el.setAttribute("data-file", file);
        el.addEventListener("ended", () => {
          if (el !== active()) return;
          if (loop) {
            el.currentTime = loop[0];
            el.play().catch(() => {});
            onLoop && onLoop();
            return;
          }
          stopWatching();
          onEnded && onEnded();
        });
        el.addEventListener("error", () => onError && onError(new Error(W.t("The track {file} could not be read.", { file })), id, file));
        // Throttled tabs run no animation frames: timeupdate still checks the loop.
        el.addEventListener("timeupdate", () => el === active() && checkLoop(el));
        document.body.appendChild(el);
        els[key] = el;
      }
      return els[key];
    }

    const active = () => element(current);

    function applyRate(el) {
      el.preservesPitch = true;
      el.mozPreservesPitch = true;
      el.webkitPreservesPitch = true;
      el.playbackRate = rate;
    }

    function loopEnd(el) {
      const end = loop[1];
      return Number.isFinite(el.duration) ? Math.min(end, el.duration - EDGE) : end;
    }

    // Only a wrap during playback counts as a pass: a seek while paused must not step the trainer.
    function checkLoop(el) {
      if (loop && !el.paused && el.currentTime >= loopEnd(el)) {
        el.currentTime = loop[0];
        onLoop && onLoop();
      }
    }

    function tick() {
      const el = active();
      checkLoop(el);
      onTime && onTime(el.currentTime);
    }

    function frame() {
      tick();
      if (!active().paused) raf = requestAnimationFrame(frame);
    }

    function watch() {
      stopWatching();
      raf = requestAnimationFrame(frame);
      timer = setInterval(tick, 100); // in the background, frames stop but intervals still run
    }

    function stopWatching() {
      cancelAnimationFrame(raf);
      clearInterval(timer);
      raf = 0;
      timer = 0;
    }

    // Resolves true once the element can play from its position, false if its file fails to load.
    // A slow disk is not a failure: after 3 s the switch goes ahead and the browser catches up.
    function ready(el) {
      if (el.error) return Promise.resolve(false);
      if (el.readyState >= 3 && !el.seeking) return Promise.resolve(true);
      return new Promise((resolve) => {
        const finish = (ok) => () => {
          el.removeEventListener("canplay", yes);
          el.removeEventListener("seeked", yes);
          el.removeEventListener("error", no);
          clearTimeout(limit);
          resolve(ok);
        };
        const yes = finish(true);
        const no = finish(false);
        const limit = setTimeout(yes, 3000);
        el.addEventListener("canplay", yes);
        el.addEventListener("seeked", yes);
        el.addEventListener("error", no);
      });
    }

    async function play() {
      const el = active();
      applyRate(el);
      if (loop && (el.currentTime < loop[0] || el.currentTime >= loopEnd(el))) el.currentTime = loop[0];
      try {
        await el.play();
      } catch (err) {
        onError && onError(err);
        return false;
      }
      watch();
      return true;
    }

    function pause() {
      active().pause();
      stopWatching();
      onTime && onTime(active().currentTime);
    }

    // Switch to another track at the same position. The new track is loaded and positioned first,
    // then started, then the old one stops: no gap, and only a few milliseconds of overlap.
    // Switches queue up, so quick successive clicks end on the last one.
    // Resolves true when the switch happened, false when the new track could not be read (the
    // current track then keeps playing).
    function setTrack(id) {
      switching = switching.then(async () => {
        if (id === current) return true;
        const from = active();
        const to = element(id);
        to.preload = "auto";
        applyRate(to);
        to.currentTime = from.currentTime;
        if (!(await ready(to))) {
          to.preload = "none";
          return false;
        }
        to.currentTime = from.currentTime; // the old track kept playing while the new one loaded
        current = id;
        if (!from.paused) {
          try {
            await to.play();
          } catch (err) {
            onError && onError(err);
          }
          watch();
        }
        from.pause();
        from.preload = "none";
        return true;
      });
      return switching;
    }

    // The same track from another file (the recording in another key, rendered by the library), at
    // the same position without stopping, as a switch of track does. Resolves false (the old file
    // still playing) when the new one cannot be read.
    function setFile(id, file) {
      switching = switching.then(async () => {
        if (files[id] === file) return true;
        if (id !== current) {
          files[id] = file; // played from it when the track is chosen
          return true;
        }
        const from = active();
        const to = element(id, file); // the old file plays on until the new one can take over
        to.preload = "auto";
        applyRate(to);
        to.currentTime = from.currentTime;
        if (!(await ready(to))) {
          to.remove(); // a file that failed is asked afresh next time, not from a broken element
          delete els[id + "|" + file];
          return false;
        }
        to.currentTime = from.currentTime;
        files[id] = file;
        if (!from.paused) {
          try {
            await to.play();
          } catch (err) {
            onError && onError(err);
          }
          watch();
        }
        from.pause();
        from.preload = "none";
        return true;
      });
      return switching;
    }

    return {
      play,
      pause,
      setTrack,
      setFile,
      fileOf: (id) => files[id],
      get playing() {
        return !active().paused;
      },
      get time() {
        return active().currentTime;
      },
      get track() {
        return current;
      },
      seek(t) {
        active().currentTime = Math.max(0, t);
        onTime && onTime(active().currentTime);
      },
      setRate(r) {
        rate = r;
        applyRate(active());
      },
      setLoop(range) {
        loop = range;
      },
      elements: () => els,
    };
  };
})();
