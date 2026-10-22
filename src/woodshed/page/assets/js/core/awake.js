// A phone on the music stand stays awake while the band follows, leads or plays on stage (spec 008).
// Screen Wake Lock where the browser has it (a secure page: localhost, HTTPS); elsewhere, the band's
// Wi-Fi over plain HTTP, a tiny muted video looping in the page, the technique of NoSleep.js
// (github.com/richtr/NoSleep.js, MIT), written here: its built-in data: video would need the CSP to
// allow data: media. Best effort: what keeps a screen on is the phone's system to decide.
(function () {
  "use strict";
  const W = window.Woodshed;

  W.createAwake = function createAwake(onChange) {
    let wanted = false;
    let lock = null; // the WakeLockSentinel held
    let asking = null; // a request in flight
    let video = null;
    let retry = null; // the next touch or key tries the video again (a play refused without a gesture)

    const holding = () => !!lock || !!(video && !video.paused);
    const changed = () => onChange && onChange(holding());

    function theVideo() {
      if (video) return video;
      video = document.createElement("video");
      video.className = "awake-video";
      video.setAttribute("data-testid", "awake-video");
      video.muted = true;
      video.loop = true;
      video.playsInline = true;
      for (const [file, type] of [["assets/awake/awake.mp4", "video/mp4"], ["assets/awake/awake.webm", "video/webm"]]) {
        const source = document.createElement("source");
        source.src = file;
        source.type = type;
        video.appendChild(source);
      }
      for (const name of ["muted", "loop", "playsinline"]) video.setAttribute(name, "");
      video.setAttribute("aria-hidden", "true");
      video.addEventListener("pause", () => wanted && !lock && !document.hidden && playVideo()); // paused by the system
      video.addEventListener("playing", changed);
      document.body.appendChild(video); // in the page and in view: a hidden or detached video is paused
      return video;
    }

    function armRetry() {
      if (retry) return;
      retry = () => {
        disarm();
        if (wanted && !lock) playVideo();
      };
      document.addEventListener("pointerdown", retry, true);
      document.addEventListener("keydown", retry, true);
    }

    function disarm() {
      if (!retry) return;
      document.removeEventListener("pointerdown", retry, true);
      document.removeEventListener("keydown", retry, true);
      retry = null;
    }

    function playVideo() {
      const v = theVideo();
      const p = v.play();
      if (p && p.catch) {
        p.catch(() => {
          armRetry(); // no gesture yet (a page loaded on a song change): the next touch
          changed();
        });
      }
    }

    async function ask() {
      if (!navigator.wakeLock || !navigator.wakeLock.request) return false;
      if (lock) return true; // held already: never two
      if (asking) return asking;
      asking = (async () => {
        try {
          const sentinel = await navigator.wakeLock.request("screen");
          if (!wanted) {
            sentinel.release().catch(() => {}); // released while it was asked
            return false;
          }
          lock = sentinel;
          sentinel.addEventListener("release", () => {
            if (lock === sentinel) lock = null;
            changed();
            if (wanted && !document.hidden) hold(); // dropped by the system, the page still in view
          });
          return true;
        } catch (err) {
          return false; // refused: Battery Saver, Low Power Mode, a page not in view
        } finally {
          asking = null;
        }
      })();
      return asking;
    }

    async function hold() {
      if (await ask()) {
        if (video && !video.paused) video.pause();
        disarm();
      } else if (wanted) playVideo();
      changed();
    }

    function release() {
      disarm();
      if (lock) {
        const l = lock;
        lock = null;
        l.release().catch(() => {});
      }
      if (video && !video.paused) video.pause();
      changed();
    }

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && wanted) hold(); // the browser lets the lock go while the page is hidden
    });

    return {
      want(on) {
        if (on === wanted) return;
        wanted = on;
        if (on) hold();
        else release();
      },
      wanted: () => wanted,
      holding,
      locked: () => !!lock, // the browser's Wake Lock itself, not the video's best effort
    };
  };
})();
